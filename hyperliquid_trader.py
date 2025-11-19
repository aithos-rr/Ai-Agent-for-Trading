import json
from decimal import Decimal, ROUND_DOWN
from typing import Dict, Any

import eth_account
from eth_account.signers.local import LocalAccount

from hyperliquid.info import Info
from hyperliquid.exchange import Exchange
from hyperliquid.utils import constants


class HyperLiquidTrader:
    def __init__(
        self,
        secret_key: str,
        account_address: str,
        testnet: bool = True,
        skip_ws: bool = True,
    ):
        self.secret_key = secret_key
        self.account_address = account_address

        base_url = constants.TESTNET_API_URL if testnet else constants.MAINNET_API_URL
        self.base_url = base_url

        # crea account signer
        account: LocalAccount = eth_account.Account.from_key(secret_key)

        self.info = Info(base_url, skip_ws=skip_ws)
        self.exchange = Exchange(account, base_url, account_address=account_address)

        # cache meta per tick-size e min-size
        self.meta = self.info.meta()

    def _to_hl_size(self, size_decimal: Decimal) -> str:
        # HL accetta max 8 decimali
        size_clamped = size_decimal.quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
        return format(size_clamped, "f")   # HL vuole stringa decimale perfetta

    # ----------------------------------------------------------------------
    #                            VALIDAZIONE INPUT
    # ----------------------------------------------------------------------
    def _validate_order_input(self, order_json: Dict[str, Any]):
        required_fields = [
            "operation",
            "symbol",
            "direction",
            "target_portion_of_balance",
            "leverage",
            "reason",
        ]

        for f in required_fields:
            if f not in order_json:
                raise ValueError(f"Missing required field: {f}")

        if order_json["operation"] not in ("open", "close", "hold"):
            raise ValueError("operation must be 'open', 'close', or 'hold'")

        if order_json["direction"] not in ("long", "short"):
            raise ValueError("direction must be 'long' or 'short'")

        try:
            float(order_json["target_portion_of_balance"])
        except:
            raise ValueError("target_portion_of_balance must be a number")

    # ----------------------------------------------------------------------
    #                           MIN SIZE / TICK SIZE
    # ----------------------------------------------------------------------
    def _get_min_tick_for_symbol(self, symbol: str) -> Decimal:
        """
        Hyperliquid definisce per ogni asset un tick size.
        Lo leggiamo da meta().
        """
        for perp in self.meta["universe"]:
            if perp["name"] == symbol:
                return Decimal(str(perp["szDecimals"]))
        return Decimal("0.00000001")  # fallback a 1e-8

    def _round_size(self, size: Decimal, decimals: int) -> float:
        """
        Hyperliquid accetta massimo 8 decimali.
        Inoltre dobbiamo rispettare il tick size.
        """
        # prima clamp a 8 decimali
        size = size.quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)

        # poi count of decimals per il tick
        fmt = f"{{0:.{decimals}f}}"
        return float(fmt.format(size))

    # ----------------------------------------------------------------------
    #                        GESTIONE LEVA
    # ----------------------------------------------------------------------
    def get_current_leverage(self, symbol: str) -> Dict[str, Any]:
        """Ottieni info sulla leva corrente per un simbolo"""
        try:
            user_state = self.info.user_state(self.account_address)
            
            # Cerca nelle posizioni aperte
            for position in user_state.get('assetPositions', []):
                pos = position.get('position', {})
                coin = pos.get('coin', '')
                if coin == symbol:
                    leverage_info = pos.get('leverage', {})
                    return {
                        'value': leverage_info.get('value', 0),
                        'type': leverage_info.get('type', 'unknown'),
                        'coin': coin
                    }
            
            # Se non c'è posizione aperta, controlla cross leverage default
            cross_leverage = user_state.get('crossLeverage', 20)
            return {
                'value': cross_leverage,
                'type': 'cross',
                'coin': symbol,
                'note': 'No open position, showing account default'
            }
            
        except Exception as e:
            print(f"Errore ottenendo leva corrente: {e}")
            return {'value': 20, 'type': 'unknown', 'error': str(e)}

    def set_leverage_for_symbol(self, symbol: str, leverage: int, is_cross: bool = True) -> Dict[str, Any]:
        """Imposta la leva per un simbolo specifico usando il metodo corretto"""
        try:
            print(f"🔧 Impostando leva {leverage}x per {symbol} ({'cross' if is_cross else 'isolated'} margin)")
            
            # Usa il metodo update_leverage con i parametri corretti
            result = self.exchange.update_leverage(
                leverage=leverage,      # int
                name=symbol,           # str - nome del simbolo come "BTC"
                is_cross=is_cross      # bool
            )
            
            if result.get('status') == 'ok':
                print(f"✅ Leva impostata con successo a {leverage}x per {symbol}")
            else:
                print(f"⚠️ Risposta dall'exchange: {result}")
                
            return result
            
        except Exception as e:
            print(f"❌ Errore impostando leva per {symbol}: {e}")
            return {"status": "error", "error": str(e)}

    # ----------------------------------------------------------------------
    #                        ESECUZIONE SEGNALE AI
    # ----------------------------------------------------------------------
        # ----------------------------------------------------------------------
    #                        ESECUZIONE SEGNALE AI
    # ----------------------------------------------------------------------
    def execute_signal(self, order_json: Dict[str, Any]) -> Dict[str, Any]:
        """
        Esegue il segnale generato dall'AI su Hyperliquid e ritorna
        un dizionario trade_info con tutti i dati necessari per logging
        e simulazione costi/tasse.

        ATTENZIONE:
        - Si aspetta un dict come quello ritornato da previsione_trading_agent:
          {
            "operation": "open" | "close" | "hold",
            "symbol": "BTC",
            "direction": "long" | "short",
            "target_portion_of_balance": 0.2,
            "leverage": 5,
            ...
          }
        """
        from decimal import Decimal, ROUND_DOWN

        # 1) Validazione di base (già presente)
        self._validate_order_input(order_json)

        op = order_json["operation"]
        symbol = order_json["symbol"]
        direction = order_json["direction"]
        portion = Decimal(str(order_json["target_portion_of_balance"]))
        leverage = int(order_json.get("leverage", 1))

        # Operazione HOLD → nessuna azione
        if op == "hold":
            print(f"[HyperLiquidTrader] HOLD — nessuna azione per {symbol}.")
            return {
                "status": "hold",
                "symbol": symbol,
                "direction": direction,
                "message": "No action taken.",
            }

        # Se devi prima chiudere eventuali posizioni esistenti
        if op == "close":
            print(f"[HyperLiquidTrader] Market CLOSE per {symbol}")
            # QUI lasci tutto il codice che avevi già per chiudere la posizione.
            # Se non hai filler precise sull'output dell'ordine di close, puoi
            # per ora ritornare solo lo status.
            # TODO: se vuoi loggare fee anche in chiusura, estrai i dati come
            # per l'apertura (vedi sotto).
            # Esempio minimal:
            close_res = self._close_position(symbol=symbol, direction=direction, leverage=leverage)
            return close_res
                

        # Da qui, op == "open"
        print(f"[HyperLiquidTrader] OPEN {symbol} {direction} portion={portion}, leverage={leverage}")

        # 2) Imposta o controlla la leva (riusa il tuo codice esistente)
        current = self.get_current_leverage(symbol)
        print(f"📊 Leva attuale per {symbol}: {current}")

        self.set_leverage_for_symbol(symbol, leverage, is_cross=True)


        # 3) Calcola notional e size come già fai
        user = self.info.user_state(self.account_address)
        balance_usd = Decimal(str(user["marginSummary"]["accountValue"]))
        if balance_usd <= 0:
            raise RuntimeError("Balance account = 0")

        notional = balance_usd * portion * Decimal(str(leverage))

        mids = self.info.all_mids()
        if symbol not in mids:
            raise RuntimeError(f"Symbol {symbol} non presente in mids")

        mark_px = Decimal(str(mids[symbol]))
        raw_size = notional / mark_px

        # 3b) Applica i constraint di minimum size come fai già
        symbol_info = None
        for perp in self.meta["universe"]:
            if perp["name"] == symbol:
                symbol_info = perp
                break

        if not symbol_info:
            raise RuntimeError(f"Symbol {symbol} non trovato nella meta universe")

        min_size = Decimal(str(symbol_info["szDecimals"]))
        # QUI: se nel tuo codice attuale usi un altro campo (es. "szIncrement"),
        # sostituisci.

        # Adatta raw_size al minimo consentito (riusa la tua logica attuale)
        size_decimal = raw_size.quantize(min_size, rounding=ROUND_DOWN)
        if size_decimal <= 0:
            # fallback: usa minimo size
            size_decimal = min_size

        size_float = float(size_decimal)
        is_buy = (direction == "long")

        print(
            f"\n[HyperLiquidTrader] Market {'BUY' if is_buy else 'SELL'} "
            f"{size_float} {symbol}\n"
            f"  💰 Prezzo stimato: ${mark_px}\n"
            f"  📊 Notional: ${notional:.2f}\n"
            f"  🎯 Leva target: {leverage}x\n"
        )

        # 4) Chiamata effettiva all'API Hyperliquid
        try:
            res = self.exchange.market_open(
                symbol,
                is_buy,
                size_float,
                None,      # limit price -> market
                0.01       # slippage tollerata (adatta al tuo codice se diverso)
            )
        except Exception as e:
            print(f"❌ Errore durante market_open su Hyperliquid: {e}")
            return {
                "status": "error",
                "symbol": symbol,
                "direction": direction,
                "error": str(e),
            }

        # 5) Costruzione trade_info (fee, PnL ecc.)
        trade_info = self._build_trade_info_from_response(
            symbol=symbol,
            direction=direction,
            is_buy=is_buy,
            size=size_float,
            leverage=leverage,
            mark_price=float(mark_px),
            order_result=res,
        )

        return trade_info

    # ----------------------------------------------------------------------
    # Helper per estrarre fee, PnL ecc. dalla risposta di Hyperliquid
    # ----------------------------------------------------------------------
    def _build_trade_info_from_response(
        self,
        *,
        symbol: str,
        direction: str,
        is_buy: bool,
        size: float,
        leverage: int,
        mark_price: float,
        order_result: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Estrae dai dati dell'ordine di Hyperliquid:
        - size eseguita (totalSz)
        - prezzo medio eseguito (avgPx)
        - (per ora) fee e PnL non disponibili → li lasciamo a 0/None

        Esempio di risposta reale:

        {
          "status": "ok",
          "response": {
            "type": "order",
            "data": {
              "statuses": [
                {
                  "filled": {
                    "totalSz": "2.149",
                    "avgPx": "925.817",
                    "oid": 43455754247
                  }
                }
              ]
            }
          }
        }
        """
        status = order_result.get("status", "ok")

        exec_size = size           # fallback: size richiesta
        exec_price = mark_price    # fallback: prezzo stimato

        # Estrazione dal JSON reale
        response = order_result.get("response") or {}
        data = response.get("data") or {}
        statuses = data.get("statuses") or []

        if statuses:
            st0 = statuses[0]
            filled = st0.get("filled") or {}

            total_sz = filled.get("totalSz")
            avg_px = filled.get("avgPx")

            if total_sz is not None:
                try:
                    exec_size = float(total_sz)
                except Exception:
                    pass

            if avg_px is not None:
                try:
                    exec_price = float(avg_px)
                except Exception:
                    pass

        # Per ora: fee & PnL non forniti dalla response → 0/None
        fee_asset = "USDC"
        fee_amount = 0.0
        fee_usd = 0.0
        realized_pnl_usd = None

        side = "buy" if is_buy else "sell"

        trade_info: Dict[str, Any] = {
            "status": status,
            "symbol": symbol,
            "side": side,
            "direction": direction,
            "size": exec_size,       # 👈 2.149
            "price": exec_price,     # 👈 925.817
            "leverage": leverage,
            "fee_asset": fee_asset,
            "fee_amount": fee_amount,
            "fee_usd": fee_usd,
            "realized_pnl_usd": realized_pnl_usd,
            "raw": order_result,
        }
        return trade_info

    # ----------------------------------------------------------------------
    #                           close position
    # ----------------------------------------------------------------------
    def _close_position(self, symbol: str, direction: str, leverage: int) -> Dict[str, Any]:
        """
        Chiude una posizione long/short usando market_close e ritorna un trade_info completo.
        """
        print(f"[HyperLiquidTrader] CLOSE {symbol} ({direction}) via market_close")

        # Direzione di chiusura:
        # - se chiudo una LONG → SELL → is_buy = False
        # - se chiudo una SHORT → BUY → is_buy = True
        is_buy = True if direction == "short" else False

        # mark price solo per fallback
        mids = self.info.all_mids()
        mark_price = float(mids.get(symbol, 0.0))

        try:
            order_result = self.exchange.market_close(symbol)
        except Exception as e:
            print(f"❌ Errore durante market_close: {e}")
            return {
                "status": "error",
                "symbol": symbol,
                "direction": direction,
                "error": str(e)
            }

        # Costruzione trade_info dai dati reali (filled)
        trade_info = self._build_trade_info_from_response(
            symbol=symbol,
            direction=direction,
            is_buy=is_buy,
            size=0.0,
            leverage=leverage,
            mark_price=mark_price,
            order_result=order_result,
        )

        trade_info["status"] = "close"
        return trade_info



    # ----------------------------------------------------------------------
    #                           STATO ACCOUNT
    # ----------------------------------------------------------------------
    def get_account_status(self) -> Dict[str, Any]:
        data = self.info.user_state(self.account_address)
        balance = float(data["marginSummary"]["accountValue"])

        mids = self.info.all_mids()
        positions = []

        # Gestisci il formato corretto dei dati
        asset_positions = data.get("assetPositions", [])
        
        for p in asset_positions:
            # Estrai la posizione dal formato corretto
            if isinstance(p, dict) and "position" in p:
                pos = p["position"]
                coin = pos.get("coin", "")
            else:
                # Se il formato è diverso, prova ad adattarti
                pos = p
                coin = p.get("coin", p.get("symbol", ""))
                
            if not pos or not coin:
                continue
                
            size = float(pos.get("szi", 0))
            if size == 0:
                continue

            entry = float(pos.get("entryPx", 0))
            mark = float(mids.get(coin, entry))

            # Calcola P&L
            pnl = (mark - entry) * size
            
            # Estrai info sulla leva
            leverage_info = pos.get("leverage", {})
            leverage_value = leverage_info.get("value", "N/A")
            leverage_type = leverage_info.get("type", "unknown")

            positions.append({
                "symbol": coin,
                "side": "long" if size > 0 else "short",
                "size": abs(size),
                "entry_price": entry,
                "mark_price": mark,
                "pnl_usd": round(pnl, 4),
                "leverage": f"{leverage_value}x ({leverage_type})"
            })

        return {
            "balance_usd": balance,
            "open_positions": positions,
        }
    
    # ----------------------------------------------------------------------
    #                           UTILITY DEBUG
    # ----------------------------------------------------------------------
    def debug_symbol_limits(self, symbol: str = None):
        """Mostra i limiti di trading per un simbolo o tutti"""
        print("\n📊 LIMITI TRADING HYPERLIQUID")
        print("-" * 60)
        
        for perp in self.meta["universe"]:
            if symbol and perp["name"] != symbol:
                continue
                
            print(f"\nSymbol: {perp['name']}")
            print(f"  Min Size: {perp.get('minSz', 'N/A')}")
            print(f"  Size Decimals: {perp.get('szDecimals', 'N/A')}")
            print(f"  Price Decimals: {perp.get('pxDecimals', 'N/A')}")
            print(f"  Max Leverage: {perp.get('maxLeverage', 'N/A')}")
            print(f"  Only Isolated: {perp.get('onlyIsolated', False)}")