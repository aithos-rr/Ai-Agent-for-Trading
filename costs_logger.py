from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, Optional
from datetime import datetime, timezone

from psycopg2.extras import Json

from db_utils import get_connection, _normalize_for_json, _to_plain_number


# ====================================================
# 1. Schema tabella costi
# ====================================================

COSTS_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS cost_events (
    id                  BIGSERIAL PRIMARY KEY,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Collegamento opzionale all'operazione del bot
    bot_operation_id    BIGINT REFERENCES bot_operations(id) ON DELETE SET NULL,

    -- Tipo di costo: es. 'trade_fee', 'model_cost', 'tax'
    cost_type           TEXT NOT NULL,

    -- Info trade / exchange
    exchange            TEXT,
    symbol              TEXT,
    fee_asset           TEXT,
    fee_amount          NUMERIC(30, 10),
    fee_usd             NUMERIC(30, 10),

    -- Info modelli LLM
    model_name          TEXT,
    tokens_input        INTEGER,
    tokens_output       INTEGER,
    tokens_total        INTEGER,
    token_cost_usd      NUMERIC(30, 10),

    -- Tassazione
    tax_rate            NUMERIC(10, 4),
    tax_amount          NUMERIC(30, 10),

    -- Costo totale combinato (es. fee + tax + token_cost)
    total_cost_usd      NUMERIC(30, 10),

    -- Payload raw (risposta completa exchange / modello / calcolo)
    raw_payload         JSONB
);

CREATE INDEX IF NOT EXISTS idx_cost_events_created_at
    ON cost_events(created_at);

CREATE INDEX IF NOT EXISTS idx_cost_events_type
    ON cost_events(cost_type);
"""


def init_costs_db() -> None:
    """
    Crea la tabella cost_events se non esiste.
    Puoi chiamarla:
        - una volta all'avvio del programma
        - oppure in uno script separato di setup.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(COSTS_SCHEMA_SQL)
        conn.commit()


# ====================================================
# 2. Dataclass di comodo (opzionali, per chiarezza)
# ====================================================

@dataclass
class TradeFeeRecord:
    bot_operation_id: Optional[int]
    exchange: Optional[str]
    symbol: Optional[str]
    fee_asset: Optional[str]
    fee_amount: Optional[float]
    fee_usd: Optional[float]
    tax_rate: Optional[float] = None
    tax_amount: Optional[float] = None
    raw_payload: Optional[Dict[str, Any]] = None


@dataclass
class ModelCostRecord:
    bot_operation_id: Optional[int]
    model_name: str
    tokens_input: int
    tokens_output: int
    tokens_total: Optional[int] = None
    token_cost_usd: Optional[float] = None
    raw_payload: Optional[Dict[str, Any]] = None


# ====================================================
# 3. Funzioni di logging
# ====================================================

def log_trade_fee(record: TradeFeeRecord) -> int:
    """
    Logga le fee di uno specifico trade (es. Hyperliquid).

    Esempio di utilizzo (pseudocodice):

        fee_rec = TradeFeeRecord(
            bot_operation_id=op_id,       # id di bot_operations (se ce l'hai)
            exchange="hyperliquid",
            symbol="BTC",
            fee_asset="USDC",
            fee_amount=0.25,
            fee_usd=0.25,                 # se l'asset è già USD
            tax_rate=0.26,                # opzionale, es. tassazione Italia 26%
            tax_amount=0.065,             # opzionale, calcolata da te
            raw_payload=full_exchange_resp
        )
        cost_id = log_trade_fee(fee_rec)
    """

    fee_amount = _to_plain_number(record.fee_amount)
    fee_usd = _to_plain_number(record.fee_usd)
    tax_rate = _to_plain_number(record.tax_rate)
    tax_amount = _to_plain_number(record.tax_amount)

    # Costo totale = fee + eventuale tassazione
    total_cost = 0.0
    if fee_usd is not None:
        total_cost += fee_usd
    if tax_amount is not None:
        total_cost += tax_amount

    raw_norm = _normalize_for_json(record.raw_payload) if record.raw_payload is not None else None

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO cost_events (
                    bot_operation_id,
                    cost_type,
                    exchange,
                    symbol,
                    fee_asset,
                    fee_amount,
                    fee_usd,
                    model_name,
                    tokens_input,
                    tokens_output,
                    tokens_total,
                    token_cost_usd,
                    tax_rate,
                    tax_amount,
                    total_cost_usd,
                    raw_payload
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s,
                        NULL, NULL, NULL, NULL, NULL,
                        %s, %s, %s, %s)
                RETURNING id;
                """,
                (
                    record.bot_operation_id,
                    "trade_fee",
                    record.exchange,
                    record.symbol,
                    record.fee_asset,
                    fee_amount,
                    fee_usd,
                    tax_rate,
                    tax_amount,
                    _to_plain_number(total_cost),
                    Json(raw_norm) if raw_norm is not None else None,
                ),
            )
            new_id = cur.fetchone()[0]
        conn.commit()
    return new_id


def log_model_cost(record: ModelCostRecord) -> int:
    """
    Logga il costo in token (e in USD) di una chiamata modello (es. GPT-5.1).

    NOTA: il calcolo del costo in USD lo fai tu fuori (in base al pricing),
    qui lo salviamo soltanto.

    Esempio:

        cost_rec = ModelCostRecord(
            bot_operation_id=op_id,
            model_name="gpt-5.1",
            tokens_input=1500,
            tokens_output=500,
            tokens_total=2000,
            token_cost_usd=0.0123,
            raw_payload=openai_response_dict
        )
        cost_id = log_model_cost(cost_rec)
    """

    tokens_input = record.tokens_input or 0
    tokens_output = record.tokens_output or 0

    tokens_total = record.tokens_total
    if tokens_total is None:
        tokens_total = tokens_input + tokens_output

    token_cost_usd = _to_plain_number(record.token_cost_usd)
    total_cost = token_cost_usd  # per ora coincidente, ma in futuro puoi sommare altro

    raw_norm = _normalize_for_json(record.raw_payload) if record.raw_payload is not None else None

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO cost_events (
                    bot_operation_id,
                    cost_type,
                    exchange,
                    symbol,
                    fee_asset,
                    fee_amount,
                    fee_usd,
                    model_name,
                    tokens_input,
                    tokens_output,
                    tokens_total,
                    token_cost_usd,
                    tax_rate,
                    tax_amount,
                    total_cost_usd,
                    raw_payload
                )
                VALUES (%s, %s,
                        NULL, NULL, NULL, NULL, NULL,
                        %s, %s, %s, %s, %s,
                        NULL, NULL, %s, %s)
                RETURNING id;
                """,
                (
                    record.bot_operation_id,
                    "model_cost",
                    record.model_name,
                    tokens_input,
                    tokens_output,
                    tokens_total,
                    token_cost_usd,
                    _to_plain_number(total_cost),
                    Json(raw_norm) if raw_norm is not None else None,
                ),
            )
            new_id = cur.fetchone()[0]
        conn.commit()
    return new_id


# Opzionale: funzione rapida per loggare una tassazione “solo tax”
def log_tax_event(
    bot_operation_id: Optional[int],
    tax_rate: float,
    tax_amount: float,
    description: Optional[Dict[str, Any]] = None,
) -> int:
    """
    Logga un evento di sola tassazione (es. a fine mese/anno, calcolo imposte).

        log_tax_event(
            bot_operation_id=None,
            tax_rate=0.26,
            tax_amount=123.45,
            description={"note": "Tassazione capital gain Italia 26% su P&L aggregato"}
        )
    """

    tax_rate_n = _to_plain_number(tax_rate)
    tax_amount_n = _to_plain_number(tax_amount)
    total_cost = tax_amount_n

    raw_norm = _normalize_for_json(description) if description is not None else None

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO cost_events (
                    bot_operation_id,
                    cost_type,
                    exchange,
                    symbol,
                    fee_asset,
                    fee_amount,
                    fee_usd,
                    model_name,
                    tokens_input,
                    tokens_output,
                    tokens_total,
                    token_cost_usd,
                    tax_rate,
                    tax_amount,
                    total_cost_usd,
                    raw_payload
                )
                VALUES (%s, %s,
                        NULL, NULL, NULL, NULL, NULL,
                        NULL, NULL, NULL, NULL, NULL,
                        %s, %s, %s, %s)
                RETURNING id;
                """,
                (
                    bot_operation_id,
                    "tax",
                    tax_rate_n,
                    tax_amount_n,
                    _to_plain_number(total_cost),
                    Json(raw_norm) if raw_norm is not None else None,
                ),
            )
            new_id = cur.fetchone()[0]
        conn.commit()
    return new_id


if __name__ == "__main__":
    # Se lanci questo file da solo, inizializza la tabella dei costi
    init_costs_db()
    print("[costs_logger] Tabella cost_events inizializzata (se non esiste già).")
