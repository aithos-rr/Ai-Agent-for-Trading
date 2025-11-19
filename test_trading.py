from hyperliquid_trader import HyperLiquidTrader
import os
from dotenv import load_dotenv
import json
import time

load_dotenv()

# -------------------------------------------------------------------
#                    CONFIG PANEL
# -------------------------------------------------------------------
TESTNET = True   # True = testnet, False = mainnet (occhio!)
VERBOSE = True    # stampa informazioni extra

PRIVATE_KEY = os.getenv("PRIVATE_KEY")
WALLET_ADDRESS = os.getenv("WALLET_ADDRESS")

if not PRIVATE_KEY or not WALLET_ADDRESS:
    raise RuntimeError("PRIVATE_KEY o WALLET_ADDRESS mancanti nel .env")

# -------------------------------------------------------------------
#                    INIT BOT
# -------------------------------------------------------------------
bot = HyperLiquidTrader(
    secret_key=PRIVATE_KEY,
    account_address=WALLET_ADDRESS,
    testnet=TESTNET
)

bot.debug_symbol_limits("BNB")

# Prima del test
print(f"🔧 Leva corrente per BNB: {bot.get_current_leverage('BNB')}x")

# Dopo l'apertura della posizione
status = bot.get_account_status()
if status['open_positions']:
    pos = status['open_positions'][0]
    print(f"📊 Posizione aperta: {pos['size']} {pos['symbol']} con leva {pos.get('leverage', 'N/A')}")

def pretty(obj):
    return json.dumps(obj, indent=2)

print(bot.get_account_status())
print("\n---------------------------------------------------")
print("🔄 Testing HyperLiquidTrader")
print("---------------------------------------------------\n")

# -------------------------------------------------------------------
#                    TEST 1 — OPEN ORDER
# -------------------------------------------------------------------
#signal_open = {
#    "operation": "open",
 ##   "symbol": "BNB",
   # "direction": "long",
    #"target_portion_of_balance": 0.05,
   # "leverage": 2,
  #  "reason": "Test apertura posizione long"
#}

#print("📌 TEST 1 — OPEN ORDER (BNB LONG)")
#try:
#    result_open = bot.execute_signal(signal_open)
#    print("Risultato OPEN:\n", pretty(result_open))
#except Exception as e:
#    print("❌ ERRORE durante apertura:", e)

#print(bot.get_account_status())
# # aspetta un attimo per evitare race
# time.sleep(5)

# # -------------------------------------------------------------------
# #                    TEST 2 — STATUS CHECK
# # -------------------------------------------------------------------
#print("\n📌 TEST 2 — ACCOUNT STATUS")
#try:
#     status = bot.get_account_status()
#     print("Stato account:\n", pretty(status))
#except Exception as e:
#     print("❌ ERRORE durante status check:", e)

# # -------------------------------------------------------------------
# #                    TEST 3 — HOLD (should do nothing)
# # -------------------------------------------------------------------
#signal_hold = {
#     "operation": "hold",
 #    "symbol": "BNB",
  #   "direction": "long",
   #  "target_portion_of_balance": 0.1,
    # "leverage": 1,
 #    "reason": "Test hold"
# }

#print("\n📌 TEST 3 — HOLD")
#try:
#     result_hold = bot.execute_signal(signal_hold)
#     print("Risultato HOLD:\n", pretty(result_hold))
#except Exception as e:
#     print("❌ ERRORE durante HOLD:", e)

# # -------------------------------------------------------------------
# #                    TEST 4 — CLOSE POSITION
# # -------------------------------------------------------------------
#signal_close = {
   #  "operation": "close",
  #   "symbol": "BNB",
  #   "direction": "long",
  #   "target_portion_of_balance": 0.2,
  #   "leverage": 1,
  #   "reason": "Test chiusura posizione"
 #}

#print("\n📌 TEST 4 — CLOSE ORDER (BNB)")
#try:
   #  result_close = bot.execute_signal(signal_close)
   #  print("Risultato CLOSE:\n", pretty(result_close))
   #  print("\n--- campi chiave trade_info ---")
   #  print("\n--- campi chiave trade_info ---")
   #  print("status:", result_close.get("status"))
   #  print("symbol:", result_close.get("symbol"))
   #  print("side:", result_close.get("side"))
   #  print("direction:", result_close.get("direction"))
   #  print("size:", result_close.get("size"))
   #  print("price:", result_close.get("price"))
   #  print("leverage:", result_close.get("leverage"))
   #  print("fee_asset:", result_close.get("fee_asset"))
   #  print("fee_amount:", result_close.get("fee_amount"))
   #  print("fee_usd:", result_close.get("fee_usd"))
   #  print("realized_pnl_usd:", result_close.get("realized_pnl_usd"))

#except Exception as e:
    # print("❌ ERRORE durante close:", e)

# # -------------------------------------------------------------------
# #                    FINAL STATUS
# # -------------------------------------------------------------------
time.sleep(2)
print("\n📌 STATUS FINALE")
try:
     final_status = bot.get_account_status()
     print("Stato finale:\n", pretty(final_status))
except Exception as e:
     print("❌ ERRORE durante final status:", e)

print("\n---------------------------------------------------")
print("🏁 Testing completato.")
print("---------------------------------------------------\n")
