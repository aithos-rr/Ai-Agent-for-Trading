from indicators import analyze_multiple_tickers
from news_feed import fetch_latest_news
from trading_agent import previsione_trading_agent
from whalealert import format_whale_alerts_to_string
from sentiment import get_sentiment
from forecaster import get_crypto_forecasts
from hyperliquid_trader import HyperLiquidTrader
from costs_logger import (
    TradeFeeRecord, ModelCostRecord,
    log_trade_fee, log_model_cost, log_tax_event
)
import os
import json
import db_utils
from dotenv import load_dotenv

load_dotenv()

# -------------------------------------------------------
# 1️⃣ — CARICO SUBITO IL SYSTEM PROMPT BASE
#     (necessario per non crashare nel blocco except)
# -------------------------------------------------------
with open("system_prompt.txt", "r") as f:
    base_system_prompt = f.read()

# valori placeholder temporanei
portfolio_data = "{}"
msg_info = "{}"

# prompt "di emergenza" per non crashare in try/except
system_prompt = base_system_prompt.format(portfolio_data, msg_info)

# Fee taker simulata
FEE_RATE = 0.0005  

# Hyperliquid
TESTNET = True
VERBOSE = True
PRIVATE_KEY = os.getenv("PRIVATE_KEY")
WALLET_ADDRESS = os.getenv("WALLET_ADDRESS")

if not PRIVATE_KEY or not WALLET_ADDRESS:
    raise RuntimeError("PRIVATE_KEY o WALLET_ADDRESS mancanti nel file .env")


# -------------------------------------------------------
# 2️⃣ — BLOCCO PRINCIPALE
# -------------------------------------------------------
try:
    # Connessione HL
    bot = HyperLiquidTrader(
        secret_key=PRIVATE_KEY,
        account_address=WALLET_ADDRESS,
        testnet=TESTNET
    )

    # --- Indicatori per i ticker ---
    tickers = ["BTC", "ETH", "BNB", "SOL", "DOGE"]
    indicators_txt, indicators_json = analyze_multiple_tickers(tickers)

    # --- News ---
    news_txt = fetch_latest_news()

    # --- Sentiment ---
    sentiment_txt, sentiment_json = get_sentiment()

    # --- Previsioni ---
    forecasts_txt, forecasts_json = get_crypto_forecasts()

    # --- Composizione del messaggio informativo ---
    msg_info = (
        f"<indicatori>\n{indicators_txt}\n</indicatori>\n\n"
        f"<news>\n{news_txt}\n</news>\n\n"
        f"<sentiment>\n{sentiment_txt}\n</sentiment>\n\n"
        f"<forecast>\n{forecasts_txt}\n</forecast>\n\n"
    )

    # --- Portfolio HL ---
    account_status = bot.get_account_status()
    portfolio_data = json.dumps(account_status)

    # Log DB stato account
    snapshot_id = db_utils.log_account_status(account_status)
    print(f"[db_utils] Snapshot inserito con id={snapshot_id}")

    # --- Ricostruisco il prompt COMPLETO e DINAMICO ---
    system_prompt = base_system_prompt.format(portfolio_data, msg_info)

    print("L'agente sta decidendo la sua azione...")

    # Chiamata al modello LLM
    out, usage, raw_response = previsione_trading_agent(system_prompt)

    # Esecuzione del segnale di trading
    trade_info = bot.execute_signal(out)

    # Log operazione nel DB
    op_id = db_utils.log_bot_operation(
        out,
        system_prompt=system_prompt,
        indicators=indicators_json,
        news_text=news_txt,
        sentiment=sentiment_json,
        forecasts=forecasts_json
    )
    print(f"[db_utils] Operazione inserita con id={op_id}")


    # -------------------------------------------------------
    # 3️⃣ — LOGGING COSTI DEL MODELLO
    # -------------------------------------------------------
    try:
        input_tokens = usage["input_tokens"]
        output_tokens = usage["output_tokens"]
        total_tokens = usage["total_tokens"]

        MODEL_NAME = "gpt-5.1"
        INPUT_COST_PER_1K = 0.002
        OUTPUT_COST_PER_1K = 0.006

        usd_cost = (
            (input_tokens / 1000) * INPUT_COST_PER_1K +
            (output_tokens / 1000) * OUTPUT_COST_PER_1K
        )

        cost_record = ModelCostRecord(
            bot_operation_id=op_id,
            model_name=MODEL_NAME,
            tokens_input=input_tokens,
            tokens_output=output_tokens,
            tokens_total=total_tokens,
            token_cost_usd=usd_cost,
            raw_payload={
                "usage": usage,
                "response_id": getattr(raw_response, "id", None),
            },
        )

        log_model_cost(cost_record)
        if VERBOSE:
            print(f"[costs_logger] Costo modello loggato: {usd_cost:.6f} USD")

    except Exception as e_cost:
        print(f"[costs_logger] Errore logging costo modello: {e_cost}")


    # -------------------------------------------------------
    # 4️⃣ — LOGGING FEE HYPERLIQUID + TASSE
    # -------------------------------------------------------
    try:
        if trade_info and trade_info.get("status") not in ("hold", "error"):

            exec_size = float(trade_info.get("size") or 0.0)
            exec_price = float(trade_info.get("price") or 0.0)
            notional = exec_size * exec_price

            simulated_fee_usd = notional * FEE_RATE

            trade_info["fee_asset"] = "USDC"
            trade_info["fee_amount"] = simulated_fee_usd
            trade_info["fee_usd"] = simulated_fee_usd

            fee_record = TradeFeeRecord(
                bot_operation_id=op_id,
                exchange="hyperliquid",
                symbol=trade_info["symbol"],
                fee_asset="USDC",
                fee_amount=simulated_fee_usd,
                fee_usd=simulated_fee_usd,
                tax_rate=None,
                tax_amount=None,
                raw_payload=trade_info.get("raw")
            )

            log_trade_fee(fee_record)

            if VERBOSE:
                print(f"[costs_logger] Fee simulata: {simulated_fee_usd:.6f} USD")

    except Exception as e_fee:
        print(f"[costs_logger] Errore logging fee/tasse: {e_fee}")


# -------------------------------------------------------
# 5️⃣ — GESTIONE ERRORI TOP-LEVEL
# -------------------------------------------------------
except Exception as e:
    db_utils.log_error(
        e,
        context={
            "prompt": system_prompt,
            "tickers": tickers if 'tickers' in locals() else None,
            "indicators": indicators_json if 'indicators_json' in locals() else None,
            "news": news_txt if 'news_txt' in locals() else None,
            "sentiment": sentiment_json if 'sentiment_json' in locals() else None,
            "forecasts": forecasts_json if 'forecasts_json' in locals() else None,
            "portfolio": portfolio_data,
        },
        source="main"
    )
    print(f"❌ ERRORE GENERALE: {e}")
