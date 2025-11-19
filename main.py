from indicators import analyze_multiple_tickers
from news_feed import fetch_latest_news
from trading_agent import previsione_trading_agent
from whalealert import format_whale_alerts_to_string
from sentiment import get_sentiment
from forecaster import get_crypto_forecasts
from hyperliquid_trader import HyperLiquidTrader
from costs_logger import (TradeFeeRecord, ModelCostRecord, log_trade_fee, log_model_cost, log_tax_event,)
import os
import json
import db_utils
from dotenv import load_dotenv
load_dotenv()

FEE_RATE = 0.0005  # 0.05% di taker fee simulata (esempio, adatta se vuoi)

# Collegamento ad Hyperliquid
TESTNET = True   # True = testnet, False = mainnet (occhio!)
VERBOSE = True    # stampa informazioni extra
PRIVATE_KEY = os.getenv("PRIVATE_KEY")
WALLET_ADDRESS = os.getenv("WALLET_ADDRESS")

if not PRIVATE_KEY or not WALLET_ADDRESS:
    raise RuntimeError("PRIVATE_KEY o WALLET_ADDRESS mancanti nel .env")
try:
    bot = HyperLiquidTrader(
        secret_key=PRIVATE_KEY,
        account_address=WALLET_ADDRESS,
        testnet=TESTNET
    )

    # Calcolo delle informazioni in input per Ticker
    tickers = ["BTC", "ETH", "BNB", "SOL", "XRP", "DOGE"]
    indicators_txt, indicators_json  = analyze_multiple_tickers(tickers)
    news_txt = fetch_latest_news()
    # whale_alerts_txt = format_whale_alerts_to_string()
    sentiment_txt, sentiment_json  = get_sentiment()
    forecasts_txt, forecasts_json = get_crypto_forecasts()


    msg_info=f"""<indicatori>\n{indicators_txt}\n</indicatori>\n\n
    <news>\n{news_txt}</news>\n\n
    <sentiment>\n{sentiment_txt}\n</sentiment>\n\n
    <forecast>\n{forecasts_txt}\n</forecast>\n\n"""

    account_status = bot.get_account_status()
    portfolio_data = f"{json.dumps(account_status)}"
    snapshot_id = db_utils.log_account_status(account_status)
    print(f"[db_utils] Operazione inserita con id={snapshot_id}")


    # Creating System prompt
    with open('system_prompt.txt', 'r') as f:
        system_prompt = f.read()

    # Sostituisci SOLO i primi due {}: prima il portfolio, poi il contesto
    system_prompt = system_prompt.replace("{}", portfolio_data, 1)
    system_prompt = system_prompt.replace("{}", msg_info, 1)

        
    print("L'agente sta decidendo la sua azione!")
    out, usage, raw_response = previsione_trading_agent(system_prompt)
    trade_info = bot.execute_signal(out)


    op_id = db_utils.log_bot_operation(out, system_prompt=system_prompt, indicators=indicators_json, news_text=news_txt, sentiment=sentiment_json, forecasts=forecasts_json)
    print(f"[db_utils] Operazione inserita con id={op_id}")

    # === Logging dei costi del modello LLM ===
    try:
        # Token usati dal modello
        input_tokens = usage["input_tokens"]
        output_tokens = usage["output_tokens"]
        total_tokens = usage["total_tokens"]

        # ⚠️ Valori di esempio: li aggiusterai quando definiremo
        # i prezzi reali del modello usato nella tesi
        MODEL_NAME = "gpt-5.1"
        INPUT_COST_PER_1K = 0.002   # USD per 1000 token input (esempio)
        OUTPUT_COST_PER_1K = 0.006  # USD per 1000 token output (esempio)

        usd_cost = (
            (input_tokens / 1000) * INPUT_COST_PER_1K
             + (output_tokens / 1000) * OUTPUT_COST_PER_1K
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
            print(f"[costs_logger] Costo modello loggato (USD): {usd_cost:.6f}")
    except Exception as e_cost:
        # non bloccare il bot se il logging dei costi fallisce
        print(f"[costs_logger] Errore nel logging del costo modello: {e_cost}")

    # === Logging fee Hyperliquid + tassazione simulata ===
    try:
        # trade_info può essere None o contenere solo status=hold/error
        if trade_info is not None and trade_info.get("status") not in ("hold", "error"):
            # 1) Calcolo notional eseguito
            exec_size = float(trade_info.get("size", 0.0) or 0.0)
            exec_price = float(trade_info.get("price", 0.0) or 0.0)
            notional = exec_size * exec_price

            # 2) Fee simulata (in USD, pagata in stable)
            simulated_fee_usd = notional * FEE_RATE  # es. 0.05%

            # 3) Scrivo la fee simulata DENTRO trade_info
            trade_info["fee_asset"] = "USDC"
            trade_info["fee_amount"] = simulated_fee_usd
            trade_info["fee_usd"] = simulated_fee_usd

            fee_asset = trade_info["fee_asset"]
            fee_amount = trade_info["fee_amount"]
            fee_usd = trade_info["fee_usd"]

            # 4) Tassazione simulata su PnL REALIZZATO (per ora solo se lo hai)
            realized_pnl = trade_info.get("realized_pnl_usd")
            realized_pnl = float(realized_pnl) if realized_pnl is not None else 0.0

            tax_rate = None
            tax_amount = None
            if realized_pnl > 0:
                tax_rate = 0.26
                tax_amount = round(realized_pnl * tax_rate, 2)

            # 5) Log in cost_events come trade_fee (fee + eventuale tax)
            fee_record = TradeFeeRecord(
                bot_operation_id=op_id,
                exchange="hyperliquid",
                symbol=trade_info["symbol"],
                fee_asset=fee_asset,
                fee_amount=fee_amount,
                fee_usd=fee_usd,
                tax_rate=tax_rate,
                tax_amount=tax_amount,
                raw_payload=trade_info.get("raw"),
            )
            log_trade_fee(fee_record)

            # (Opzionale) log separato di sola tassa come cost_type="tax"
            if tax_amount is not None:
                log_tax_event(
                    bot_operation_id=op_id,
                    tax_rate=tax_rate,
                    tax_amount=tax_amount,
                    description={
                        "symbol": trade_info["symbol"],
                        "realized_pnl_usd": realized_pnl,
                        "note": "Simulazione tassazione italiana 26% trade-by-trade",
                    },
                )

            if VERBOSE:
                print(
                    f"[costs_logger] Fee simulata={fee_usd:.6f} USD, "
                    f"Tax={tax_amount if tax_amount is not None else 0:.6f} USD"
                )
    except Exception as e_fee:
        print(f"[costs_logger] Errore nel logging fee/tasse: {e_fee}")


    except Exception as e:
        db_utils.log_error(
            e,
            context={
                "prompt": system_prompt,
                "tickers": tickers,
                "indicators": indicators_json,
                "news": news_txt,
                "sentiment": sentiment_json,
                "forecasts": forecasts_json,
                "balance": account_status,
            },
            source="trading_agent",
        )
        print(f"An error occurred: {e}")



except Exception as e:
    db_utils.log_error(e, context={"prompt": system_prompt, "tickers": tickers,
                                    "indicators":indicators_json, "news":news_txt,
                                    "sentiment":sentiment_json, "forecasts":forecasts_json,
                                    "balance":account_status
                                    }, source="trading_agent")
    print(f"An error occurred: {e}")