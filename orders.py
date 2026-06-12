import time
import hmac
import hashlib
import requests
from config import *

class OrderManager:

    def __init__(self):
        self._session = requests.Session()
        self._sym_info = {}

    def _update_headers(self):
        self._session.headers.update({
            "X-MBX-APIKEY": API_KEY,
            "Content-Type": (
                "application/"
                "x-www-form-urlencoded"
            ),
        })

    def _sign(self, params):
        query = "&".join(
            f"{k}={v}"
            for k, v in params.items()
        )
        sig = hmac.new(
            API_SECRET.encode(),
            query.encode(),
            hashlib.sha256
        ).hexdigest()
        return query + f"&signature={sig}"

    def _get(self, path, params=None, signed=False):
        self._update_headers()
        params = params or {}
        if signed:
            params["timestamp"] = int(
                time.time() * 1000
            )
            url = (
                f"{BASE_URL}{path}"
                f"?{self._sign(params)}"
            )
        else:
            url = f"{BASE_URL}{path}"
            if params:
                url += "?" + "&".join(
                    f"{k}={v}"
                    for k, v in params.items()
                )
        try:
            r = self._session.get(
                url, timeout=5
            )
            return r.json()
        except Exception as e:
            print(f"[GET ERR] {e}")
            return None

    def _post(self, path, params):
        self._update_headers()
        params["timestamp"] = int(
            time.time() * 1000
        )
        body = self._sign(params)
        try:
            r = self._session.post(
                f"{BASE_URL}{path}",
                data=body,
                timeout=5
            )
            return r.json()
        except Exception as e:
            print(f"[POST ERR] {e}")
            return None

    def _delete(self, path, params):
        self._update_headers()
        params["timestamp"] = int(
            time.time() * 1000
        )
        body = self._sign(params)
        try:
            r = self._session.delete(
                f"{BASE_URL}{path}",
                data=body,
                timeout=5
            )
            return r.json()
        except Exception as e:
            print(f"[DEL ERR] {e}")
            return None

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  SETUP
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def setup_exchange(self):
        print("[SETUP] Exchange configure...")

        r = self._post("/fapi/v1/leverage", {
            "symbol"  : SYMBOL,
            "leverage": LEVERAGE,
        })
        if r and "leverage" in r:
            print(f"[LEVERAGE] {LEVERAGE}x ✅")
        else:
            print(f"[LEVERAGE ERR] {r}")

        try:
            self._post("/fapi/v1/marginType", {
                "symbol"    : SYMBOL,
                "marginType": "ISOLATED",
            })
            print("[MARGIN] Isolated ✅")
        except Exception:
            pass

        self._sym_info = self._get_sym_info()

    def _get_sym_info(self):
        try:
            r = self._get("/fapi/v1/exchangeInfo")
            if r:
                for s in r.get("symbols", []):
                    if s["symbol"] == SYMBOL:
                        for f in s["filters"]:
                            if f["filterType"] == "LOT_SIZE":
                                return {
                                    "min_qty": float(
                                        f["minQty"]
                                    ),
                                    "step": float(
                                        f["stepSize"]
                                    ),
                                    "max_qty": float(
                                        f["maxQty"]
                                    ),
                                }
        except Exception as e:
            print(f"[SYM ERR] {e}")
        return {
            "min_qty": 0.001,
            "step"   : 0.001,
            "max_qty": 1000.0,
        }

    def get_balance(self):
        try:
            r = self._get(
                "/fapi/v2/balance",
                signed=True
            )
            if r:
                for asset in r:
                    if asset.get("asset") == "USDT":
                        bal = float(
                            asset.get(
                                "availableBalance",
                                0
                            )
                        )
                        print(
                            f"[BAL] {bal:.4f} USDT"
                        )
                        return bal
        except Exception as e:
            print(f"[BAL ERR] {e}")
        return 0.0

    def calc_qty(self, capital, price):
        trade_cap = capital * CAPITAL_PCT / 100
        raw_qty   = trade_cap * LEVERAGE / price
        step      = self._sym_info.get(
            "step", 0.001
        )
        qty       = int(raw_qty / step) * step
        qty       = round(qty, 3)
        min_q     = self._sym_info.get(
            "min_qty", 0.001
        )
        max_q     = self._sym_info.get(
            "max_qty", 1000.0
        )
        return max(min_q, min(max_q, qty))

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  ORDERS
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def place_limit_entry(self, side, price, qty):
        params = {
            "symbol"     : SYMBOL,
            "side"       : side,
            "type"       : "LIMIT",
            "timeInForce": "GTX",
            "price"      : f"{price:.2f}",
            "quantity"   : f"{qty:.3f}",
        }
        r = self._post("/fapi/v1/order", params)
        if r and "orderId" in r:
            print(
                f"[ENTRY] {side} "
                f"{qty}@{price:.2f} ✅"
            )
            return r["orderId"]
        print(f"[ENTRY ERR] {r}")
        return None

    def place_limit_tp(self, side, price, qty):
        params = {
            "symbol"     : SYMBOL,
            "side"       : side,
            "type"       : "LIMIT",
            "timeInForce": "GTX",
            "price"      : f"{price:.2f}",
            "quantity"   : f"{qty:.3f}",
            "reduceOnly" : "true",
        }
        r = self._post("/fapi/v1/order", params)
        if r and "orderId" in r:
            print(
                f"[TP] {side} "
                f"{qty}@{price:.2f} ✅"
            )
            return r["orderId"]
        print(f"[TP ERR] {r}")
        return None

    def place_market_sl(self, side, qty):
        params = {
            "symbol"    : SYMBOL,
            "side"      : side,
            "type"      : "MARKET",
            "quantity"  : f"{qty:.3f}",
            "reduceOnly": "true",
        }
        r = self._post("/fapi/v1/order", params)
        if r and "orderId" in r:
            fill = float(r.get("avgPrice", 0))
            print(
                f"[SL] {side} "
                f"{qty}@{fill:.2f} ✅"
            )
            return r["orderId"], fill
        print(f"[SL ERR] {r}")
        return None, 0.0

    def get_order(self, order_id):
        return self._get(
            "/fapi/v1/order",
            {
                "symbol" : SYMBOL,
                "orderId": order_id,
            },
            signed=True
        )

    def cancel_order(self, order_id):
        r = self._delete(
            "/fapi/v1/order",
            {
                "symbol" : SYMBOL,
                "orderId": order_id,
            }
        )
        if r and r.get("status") == "CANCELED":
            print(f"[CANCEL] {order_id} ✅")
            return True
        return False

    def cancel_all(self):
        self._delete(
            "/fapi/v1/allOpenOrders",
            {"symbol": SYMBOL}
        )
        print("[CANCEL ALL] ✅")

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  FEE CALCULATOR
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def calc_fees(
        self, entry_price,
        exit_price, qty, is_tp
    ):
        entry_rebate = (
            entry_price * qty * MAKER_FEE
        )
        if is_tp:
            exit_rebate = (
                exit_price * qty * MAKER_FEE
            )
            net_fee = -(
                entry_rebate + exit_rebate
            )
        else:
            exit_cost = (
                exit_price * qty * TAKER_FEE
            )
            net_fee = exit_cost - entry_rebate
        return net_fee
