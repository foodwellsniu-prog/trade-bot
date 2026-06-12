import json
import time
import threading
import websocket
from collections import deque
from config import *

class SignalEngine:

    def __init__(self):
        # Order Book
        self._ob_lock  = threading.Lock()
        self._ob_bids  = {}
        self._ob_asks  = {}
        self._ob_ready = False

        # Trade Flow
        self._flow_lock = threading.Lock()
        self._flow_data = deque(maxlen=1000)

        # Price
        self._price_lock = threading.Lock()
        self._price_hist = deque(maxlen=200)
        self._cur_price  = 0.0

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  PRICE
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def get_price(self):
        with self._price_lock:
            return self._cur_price

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  WEBSOCKET HANDLERS
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _on_ob_msg(self, ws, msg):
        try:
            data = json.loads(msg)
            with self._ob_lock:
                for b in data.get("b", []):
                    p = float(b[0])
                    q = float(b[1])
                    if q == 0:
                        self._ob_bids.pop(p, None)
                    else:
                        self._ob_bids[p] = q
                for a in data.get("a", []):
                    p = float(a[0])
                    q = float(a[1])
                    if q == 0:
                        self._ob_asks.pop(p, None)
                    else:
                        self._ob_asks[p] = q
                self._ob_ready = True
        except Exception as e:
            print(f"[OB MSG] {e}")

    def _on_trade_msg(self, ws, msg):
        try:
            data    = json.loads(msg)
            price   = float(data["p"])
            qty     = float(data["q"])
            is_sell = data["m"]

            with self._flow_lock:
                self._flow_data.append({
                    "price"  : price,
                    "qty"    : qty,
                    "is_sell": is_sell,
                    "time"   : time.time(),
                })

            with self._price_lock:
                self._cur_price = price
                self._price_hist.append({
                    "price": price,
                    "time" : time.time(),
                })
        except Exception as e:
            print(f"[TRADE MSG] {e}")

    def _start_ws(self, stream, handler, name):
        url = f"{WS_BASE}/{stream}"

        def run():
            while True:
                try:
                    print(
                        f"[WS] {name} "
                        f"connecting..."
                    )
                    ws = websocket.WebSocketApp(
                        url,
                        on_message=handler,
                        on_error=lambda w, e: print(
                            f"[WS {name}] {e}"
                        ),
                        on_close=lambda w, c, m: print(
                            f"[WS {name}] Closed"
                        ),
                        on_open=lambda w: print(
                            f"[WS {name}] ✅"
                        ),
                    )
                    ws.run_forever(
                        ping_interval=20,
                        ping_timeout=10,
                    )
                except Exception as e:
                    print(f"[WS {name}] {e}")
                print(
                    f"[WS {name}] "
                    f"Reconnect 3s..."
                )
                time.sleep(3)

        t = threading.Thread(
            target=run,
            name=f"WS_{name}",
            daemon=True
        )
        t.start()

    def start_websockets(self):
        self._start_ws(
            stream  = f"{SYMBOL_WS}@depth@100ms",
            handler = self._on_ob_msg,
            name    = "OrderBook"
        )
        self._start_ws(
            stream  = f"{SYMBOL_WS}@aggTrade",
            handler = self._on_trade_msg,
            name    = "TradeFlow"
        )
        print("[WS] Websockets started ✅")

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  ORDER BOOK SIGNAL
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _ob_signal(self):
        with self._ob_lock:
            if not self._ob_ready:
                return "FLAT", 0.0

            if not self._ob_bids or not self._ob_asks:
                return "FLAT", 0.0

            top_bids = sorted(
                self._ob_bids.keys(),
                reverse=True
            )[:OB_LEVELS]
            top_asks = sorted(
                self._ob_asks.keys()
            )[:OB_LEVELS]

            if not top_bids or not top_asks:
                return "FLAT", 0.0

            best_bid = top_bids[0]
            best_ask = top_asks[0]
            spread   = (
                (best_ask - best_bid) /
                best_bid * 100
            )

            if spread > MAX_SPREAD:
                return "FLAT", 0.0

            bid_vol = sum(
                self._ob_bids[p]
                for p in top_bids
            )
            ask_vol = sum(
                self._ob_asks[p]
                for p in top_asks
            )

            if ask_vol == 0:
                return "FLAT", 0.0

            ratio = bid_vol / ask_vol

            if ratio >= OB_IMBALANCE:
                sig = "BUY"
            elif ratio <= (1 / OB_IMBALANCE):
                sig = "SELL"
            else:
                sig = "FLAT"

            print(
                f"[OB] {sig} | "
                f"Bid={bid_vol:.0f} "
                f"Ask={ask_vol:.0f} "
                f"R={ratio:.2f}"
            )
            return sig, ratio

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  FLOW SIGNAL
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _flow_signal(self):
        with self._flow_lock:
            if len(self._flow_data) < 5:
                return "FLAT", 0.0

            now    = time.time()
            recent = [
                t for t in self._flow_data
                if now - t["time"] <= 10.0
            ]

            if len(recent) < 3:
                return "FLAT", 0.0

            buy_vol  = sum(
                t["qty"] for t in recent
                if not t["is_sell"]
            )
            sell_vol = sum(
                t["qty"] for t in recent
                if t["is_sell"]
            )
            total = buy_vol + sell_vol

            if total == 0:
                return "FLAT", 0.0

            buy_pct = buy_vol / total * 100

            if buy_pct >= FLOW_PCT:
                sig = "BUY"
            elif buy_pct <= (100 - FLOW_PCT):
                sig = "SELL"
            else:
                sig = "FLAT"

            print(
                f"[FLOW] {sig} | "
                f"Buy={buy_pct:.1f}%"
            )
            return sig, buy_pct

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  VELOCITY SIGNAL
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _vel_signal(self):
        with self._price_lock:
            if len(self._price_hist) < 3:
                return "FLAT", 0.0

            now    = time.time()
            recent = [
                p for p in self._price_hist
                if now - p["time"] <= 5.0
            ]

            if len(recent) < 2:
                return "FLAT", 0.0

            first  = recent[0]["price"]
            last   = recent[-1]["price"]

            if first == 0:
                return "FLAT", 0.0

            change = (last - first) / first * 100

            if change >= VEL_THRESHOLD:
                sig = "BUY"
            elif change <= -VEL_THRESHOLD:
                sig = "SELL"
            else:
                sig = "FLAT"

            print(
                f"[VEL] {sig} | "
                f"Change={change:.4f}%"
            )
            return sig, change

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  COMBINED - LOOSE 1/3 RULE
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def get_signal(self):
        """
        LOOSE Signal:
        1/3 signal = Trade lo
        Zyada trades = 100-110/day
        """
        ob_sig,   _ = self._ob_signal()
        flow_sig, _ = self._flow_signal()
        vel_sig,  _ = self._vel_signal()

        signals    = [ob_sig, flow_sig, vel_sig]
        buy_count  = signals.count("BUY")
        sell_count = signals.count("SELL")

        print(
            f"[SIG] OB={ob_sig} "
            f"FL={flow_sig} "
            f"VL={vel_sig} | "
            f"B={buy_count} S={sell_count}"
        )

        # 1/3 = Loose (zyada trades)
        if buy_count >= 1 and sell_count == 0:
            return (
                "BUY", buy_count,
                ob_sig, flow_sig, vel_sig
            )
        elif sell_count >= 1 and buy_count == 0:
            return (
                "SELL", sell_count,
                ob_sig, flow_sig, vel_sig
            )
        else:
            return (
                "FLAT", 0,
                ob_sig, flow_sig, vel_sig
            )
