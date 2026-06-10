"""
ETH High Frequency Scalping Bot v4.0
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Strategy : Order Book + Trade Flow
           + Price Velocity
           2/3 signals = Entry
Symbol   : ETH/USDT Futures
Exchange : Binance
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import os
import json
import time
import hmac
import hashlib
import threading
import requests
import websocket
from flask import Flask
from datetime import datetime, timezone, timedelta
from collections import deque

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  CONFIG
#  Render Environment Variables se aayega
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

MODE       = os.environ.get("MODE", "TESTNET")
API_KEY    = os.environ.get("API_KEY", "")
API_SECRET = os.environ.get("API_SECRET", "")
BOT_TOKEN  = os.environ.get("BOT_TOKEN", "")
CHAT_ID    = os.environ.get("CHAT_ID", "")

IS_TEST    = MODE == "TESTNET"

# ── URLs ──────────────────────────────────
if IS_TEST:
    BASE_URL = "https://testnet.binancefuture.com"
    WS_BASE  = "wss://stream.binancefuture.com/ws"
else:
    BASE_URL = "https://fapi.binance.com"
    WS_BASE  = "wss://fstream.binance.com/ws"

# ── Symbol ────────────────────────────────
SYMBOL    = "ETH/USDT"
SYMBOL_WS = "ethusdt"

# ── Capital ───────────────────────────────
CAPITAL_PCT = 90      # 90% per trade
LEVERAGE    = 5       # 5x leverage

# ── Trade Config ──────────────────────────
TP_PCT      = 0.05    # 0.05% take profit
SL_PCT      = 0.03    # 0.03% stop loss
MAX_HOLD    = 10      # 10 seconds max hold
ENTRY_WAIT  = 3       # 3 sec limit wait

# ── Fees ──────────────────────────────────
MAKER_FEE   = -0.0002  # -0.02% rebate
TAKER_FEE   =  0.0005  # +0.05% cost

# ── Signal Config ─────────────────────────
OB_LEVELS     = 10    # Order book levels
OB_IMBALANCE  = 1.5   # Imbalance threshold
FLOW_PCT      = 60    # Flow pressure %
VEL_THRESHOLD = 0.01  # Velocity threshold %
MAX_SPREAD    = 0.05  # Max spread %

# ── Cooldown ──────────────────────────────
COOLDOWN_WIN   = 2    # Win ke baad
COOLDOWN_LOSS  = 5    # Loss ke baad
COOLDOWN_2LOSS = 10   # 2 loss ke baad

# ── Risk Management ───────────────────────
MAX_DAILY_LOSS_PCT = 5   # 5% daily loss
MAX_CONSEC_LOSS    = 5   # 5 consecutive
MAX_DAILY_TRADES   = 500

# ── Update ────────────────────────────────
UPDATE_MIN = 30

# ── Files ─────────────────────────────────
CAP_FILE  = "capital_eth.txt"
HIST_FILE = "history_eth.json"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  FLASK SERVER
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

app = Flask(__name__)

@app.route('/')
def home():
    st = get_state()
    return json.dumps({
        "status"  : "running",
        "mode"    : MODE,
        "capital" : st["capital"],
        "trades"  : st["trades"],
        "wins"    : st["wins"],
        "losses"  : st["losses"],
        "net_pnl" : st["net_pnl"],
        "position": st["position"],
    })

def run_server():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  STATE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_lock  = threading.Lock()
_state = {
    "capital"     : 0.0,
    "start_cap"   : 0.0,
    "position"    : None,
    "side"        : None,
    "entry_price" : 0.0,
    "entry_time"  : None,
    "tp_price"    : 0.0,
    "sl_price"    : 0.0,
    "pos_size"    : 0.0,
    "last_price"  : 0.0,
    "ob_signal"   : "FLAT",
    "flow_signal" : "FLAT",
    "vel_signal"  : "FLAT",
    "trades"      : 0,
    "wins"        : 0,
    "losses"      : 0,
    "net_pnl"     : 0.0,
    "best"        : 0.0,
    "worst"       : 0.0,
    "consec_loss" : 0,
    "daily_loss"  : 0.0,
    "daily_trades": 0,
    "bot_active"  : True,
    "pause_reason": "",
}

def get_state():
    with _lock:
        return dict(_state)

def set_state(**kw):
    with _lock:
        for k, v in kw.items():
            if k in _state:
                _state[k] = v

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  CAPITAL
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def load_capital():
    try:
        with open(CAP_FILE, "r") as f:
            cap = float(f.read().strip())
            if cap > 0:
                print(f"[CAP] Loaded: {cap:.4f}")
                return cap
    except Exception:
        pass
    return None

def save_capital(cap):
    try:
        with open(CAP_FILE, "w") as f:
            f.write(str(round(cap, 6)))
    except Exception as e:
        print(f"[CAP ERR] {e}")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  HISTORY
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_hist_lock = threading.Lock()

def save_trade(data):
    try:
        with _hist_lock:
            try:
                with open(
                    HIST_FILE, "r",
                    encoding="utf-8"
                ) as f:
                    h = json.load(f)
            except Exception:
                h = []

            h.append(data)
            if len(h) > 100000:
                h = h[-100000:]

            with open(
                HIST_FILE, "w",
                encoding="utf-8"
            ) as f:
                json.dump(h, f, indent=2)
    except Exception as e:
        print(f"[HIST ERR] {e}")

def get_daily_stats():
    try:
        with open(
            HIST_FILE, "r",
            encoding="utf-8"
        ) as f:
            h = json.load(f)
    except Exception:
        return None

    today  = datetime.now().strftime("%d/%m/%Y")
    trades = [t for t in h if t["date"] == today]

    if not trades:
        return None

    pnls   = [t["net_pnl"] for t in trades]
    wins   = len([t for t in trades if t["result"] == "WIN"])
    losses = len(trades) - wins

    return {
        "total"   : len(trades),
        "wins"    : wins,
        "losses"  : losses,
        "win_rate": round(wins/len(trades)*100, 1),
        "pnl"     : round(sum(pnls), 4),
        "best"    : round(max(pnls), 4),
        "worst"   : round(min(pnls), 4),
        "capital" : trades[-1]["capital"],
    }

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  TELEGRAM
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_tg_queue = deque()
_tg_lock  = threading.Lock()

def send_tg(msg, urgent=False):
    with _tg_lock:
        if urgent:
            _tg_queue.appendleft(str(msg))
        else:
            _tg_queue.append(str(msg))

def tg_worker():
    url = (
        f"https://api.telegram.org"
        f"/bot{BOT_TOKEN}/sendMessage"
    )
    while True:
        try:
            msg = None
            with _tg_lock:
                if _tg_queue:
                    msg = _tg_queue.popleft()
            if msg:
                for _ in range(3):
                    try:
                        requests.post(
                            url,
                            data={
                                "chat_id": CHAT_ID,
                                "text"   : msg,
                            },
                            timeout=10
                        )
                        break
                    except Exception:
                        time.sleep(2)
            else:
                time.sleep(0.1)
        except Exception as e:
            print(f"[TG ERR] {e}")
            time.sleep(2)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  BINANCE API - DIRECT (Fast)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_session = requests.Session()
_session.headers.update({
    "X-MBX-APIKEY": API_KEY
})

def _sign(params):
    query = "&".join(f"{k}={v}" for k, v in params.items())
    sig   = hmac.new(
        API_SECRET.encode(),
        query.encode(),
        hashlib.sha256
    ).hexdigest()
    return query + f"&signature={sig}"

def api_get(path, params=None, signed=False):
    params = params or {}
    if signed:
        params["timestamp"] = int(time.time() * 1000)
        url = f"{BASE_URL}{path}?{_sign(params)}"
    else:
        url = f"{BASE_URL}{path}"
        if params:
            url += "?" + "&".join(
                f"{k}={v}" for k, v in params.items()
            )
    try:
        r = _session.get(url, timeout=5)
        return r.json()
    except Exception as e:
        print(f"[GET ERR] {e}")
        return None

def api_post(path, params):
    params["timestamp"] = int(time.time() * 1000)
    body = _sign(params)
    try:
        r = _session.post(
            f"{BASE_URL}{path}",
            data=body,
            timeout=5,
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
        return r.json()
    except Exception as e:
        print(f"[POST ERR] {e}")
        return None

def api_delete(path, params):
    params["timestamp"] = int(time.time() * 1000)
    body = _sign(params)
    try:
        r = _session.delete(
            f"{BASE_URL}{path}",
            data=body,
            timeout=5,
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
        return r.json()
    except Exception as e:
        print(f"[DEL ERR] {e}")
        return None

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  EXCHANGE SETUP
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def setup_exchange():
    print("[SETUP] Exchange configure...")

    # Leverage
    r = api_post("/fapi/v1/leverage", {
        "symbol"  : "ETHUSDT",
        "leverage": LEVERAGE,
    })
    if r and "leverage" in r:
        print(f"[LEVERAGE] {LEVERAGE}x ✅")
    else:
        print(f"[LEVERAGE ERR] {r}")

    # Margin type
    try:
        api_post("/fapi/v1/marginType", {
            "symbol"    : "ETHUSDT",
            "marginType": "ISOLATED",
        })
        print("[MARGIN] Isolated ✅")
    except Exception:
        pass

def get_balance():
    try:
        r = api_get("/fapi/v2/balance", signed=True)
        if r:
            for asset in r:
                if asset.get("asset") == "USDT":
                    bal = float(
                        asset.get("availableBalance", 0)
                    )
                    print(f"[BAL] {bal:.4f} USDT")
                    return bal
    except Exception as e:
        print(f"[BAL ERR] {e}")
    return 0.0

def get_symbol_info():
    try:
        r = api_get("/fapi/v1/exchangeInfo")
        if r:
            for s in r.get("symbols", []):
                if s["symbol"] == "ETHUSDT":
                    for f in s["filters"]:
                        if f["filterType"] == "LOT_SIZE":
                            return {
                                "min_qty": float(f["minQty"]),
                                "step"   : float(f["stepSize"]),
                                "max_qty": float(f["maxQty"]),
                            }
    except Exception as e:
        print(f"[SYM ERR] {e}")
    return {"min_qty": 0.001, "step": 0.001, "max_qty": 1000.0}

def calc_qty(capital, price, sym_info):
    trade_cap = capital * CAPITAL_PCT / 100
    raw_qty   = trade_cap * LEVERAGE / price
    step      = sym_info.get("step", 0.001)
    qty       = int(raw_qty / step) * step
    qty       = round(qty, 3)
    min_q     = sym_info.get("min_qty", 0.001)
    max_q     = sym_info.get("max_qty", 1000.0)
    return max(min_q, min(max_q, qty))

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  ORDERS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def place_limit_entry(side, price, qty):
    """Limit entry order - Maker rebate milega"""
    params = {
        "symbol"     : "ETHUSDT",
        "side"       : side,
        "type"       : "LIMIT",
        "timeInForce": "GTX",
        "price"      : f"{price:.2f}",
        "quantity"   : f"{qty:.3f}",
    }
    r = api_post("/fapi/v1/order", params)
    if r and "orderId" in r:
        print(f"[LIMIT] {side} {qty}@{price:.2f} ID={r['orderId']}")
        return r["orderId"]
    print(f"[LIMIT ERR] {r}")
    return None

def place_limit_tp(side, price, qty):
    """Limit TP order - Maker rebate milega"""
    params = {
        "symbol"     : "ETHUSDT",
        "side"       : side,
        "type"       : "LIMIT",
        "timeInForce": "GTX",
        "price"      : f"{price:.2f}",
        "quantity"   : f"{qty:.3f}",
        "reduceOnly" : "true",
    }
    r = api_post("/fapi/v1/order", params)
    if r and "orderId" in r:
        print(f"[TP] {side} {qty}@{price:.2f} ID={r['orderId']}")
        return r["orderId"]
    print(f"[TP ERR] {r}")
    return None

def place_market_sl(side, qty):
    """Market SL order - Fast exit"""
    params = {
        "symbol"    : "ETHUSDT",
        "side"      : side,
        "type"      : "MARKET",
        "quantity"  : f"{qty:.3f}",
        "reduceOnly": "true",
    }
    r = api_post("/fapi/v1/order", params)
    if r and "orderId" in r:
        fill = float(r.get("avgPrice", 0))
        print(f"[SL] {side} {qty}@{fill:.2f}")
        return r["orderId"], fill
    print(f"[SL ERR] {r}")
    return None, 0.0

def get_order(order_id):
    return api_get("/fapi/v1/order", {
        "symbol" : "ETHUSDT",
        "orderId": order_id,
    }, signed=True)

def cancel_order(order_id):
    r = api_delete("/fapi/v1/order", {
        "symbol" : "ETHUSDT",
        "orderId": order_id,
    })
    if r and r.get("status") == "CANCELED":
        print(f"[CANCEL] {order_id} ✅")
        return True
    return False

def cancel_all():
    api_delete("/fapi/v1/allOpenOrders", {
        "symbol": "ETHUSDT"
    })
    print("[CANCEL ALL] Done")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  WEBSOCKET - REAL TIME DATA
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Order Book
_ob_lock  = threading.Lock()
_ob_bids  = {}
_ob_asks  = {}
_ob_ready = False

# Trade Flow
_flow_lock  = threading.Lock()
_flow_data  = deque(maxlen=500)

# Price
_price_lock = threading.Lock()
_price_hist = deque(maxlen=100)
_cur_price  = 0.0

def on_ob_msg(ws, msg):
    global _ob_ready
    try:
        data = json.loads(msg)
        with _ob_lock:
            for b in data.get("b", []):
                p = float(b[0])
                q = float(b[1])
                if q == 0:
                    _ob_bids.pop(p, None)
                else:
                    _ob_bids[p] = q
            for a in data.get("a", []):
                p = float(a[0])
                q = float(a[1])
                if q == 0:
                    _ob_asks.pop(p, None)
                else:
                    _ob_asks[p] = q
            _ob_ready = True
    except Exception as e:
        print(f"[OB MSG ERR] {e}")

def on_trade_msg(ws, msg):
    global _cur_price
    try:
        data  = json.loads(msg)
        price = float(data["p"])
        qty   = float(data["q"])
        is_sell = data["m"]

        with _flow_lock:
            _flow_data.append({
                "price"  : price,
                "qty"    : qty,
                "is_sell": is_sell,
                "time"   : time.time(),
            })

        with _price_lock:
            _cur_price = price
            _price_hist.append({
                "price": price,
                "time" : time.time(),
            })

    except Exception as e:
        print(f"[TRADE MSG ERR] {e}")

def start_ws(stream, handler, name):
    url = f"{WS_BASE}/{stream}"

    def run():
        while True:
            try:
                print(f"[WS] {name} connecting...")
                ws = websocket.WebSocketApp(
                    url,
                    on_message=handler,
                    on_error=lambda w, e: print(
                        f"[WS {name} ERR] {e}"
                    ),
                    on_close=lambda w, c, m: print(
                        f"[WS {name}] Closed"
                    ),
                    on_open=lambda w: print(
                        f"[WS {name}] Connected ✅"
                    ),
                )
                ws.run_forever(
                    ping_interval=20,
                    ping_timeout=10,
                )
            except Exception as e:
                print(f"[WS {name}] {e}")
            print(f"[WS {name}] Reconnect 3s...")
            time.sleep(3)

    t = threading.Thread(
        target=run,
        name=f"WS_{name}",
        daemon=True
    )
    t.start()

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  SIGNAL ENGINE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def get_ob_signal():
    """Order Book Imbalance"""
    with _ob_lock:
        if not _ob_ready:
            return "FLAT", 0.0, 0.0

        if not _ob_bids or not _ob_asks:
            return "FLAT", 0.0, 0.0

        top_bids = sorted(
            _ob_bids.keys(), reverse=True
        )[:OB_LEVELS]
        top_asks = sorted(
            _ob_asks.keys()
        )[:OB_LEVELS]

        bid_vol = sum(_ob_bids[p] for p in top_bids)
        ask_vol = sum(_ob_asks[p] for p in top_asks)

        # Spread check
        if top_bids and top_asks:
            best_bid = top_bids[0]
            best_ask = top_asks[0]
            spread   = (
                (best_ask - best_bid) /
                best_bid * 100
            )
            if spread > MAX_SPREAD:
                return "FLAT", 0.0, spread
        else:
            spread = 0.0

        if ask_vol == 0:
            return "FLAT", 0.0, spread

        ratio = bid_vol / ask_vol

        if ratio >= OB_IMBALANCE:
            signal = "BUY"
        elif ratio <= (1 / OB_IMBALANCE):
            signal = "SELL"
        else:
            signal = "FLAT"

        print(
            f"[OB] {signal} | "
            f"Bid={bid_vol:.2f} "
            f"Ask={ask_vol:.2f} "
            f"Ratio={ratio:.2f}"
        )
        return signal, ratio, spread

def get_flow_signal():
    """Trade Flow Analysis"""
    with _flow_lock:
        if len(_flow_data) < 10:
            return "FLAT", 0.0

        now    = time.time()
        recent = [
            t for t in _flow_data
            if now - t["time"] <= 5.0
        ]

        if len(recent) < 5:
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
            signal = "BUY"
        elif buy_pct <= (100 - FLOW_PCT):
            signal = "SELL"
        else:
            signal = "FLAT"

        print(
            f"[FLOW] {signal} | "
            f"Buy={buy_pct:.1f}%"
        )
        return signal, buy_pct

def get_vel_signal():
    """Price Velocity"""
    with _price_lock:
        if len(_price_hist) < 3:
            return "FLAT", 0.0

        now    = time.time()
        recent = [
            p for p in _price_hist
            if now - p["time"] <= 2.0
        ]

        if len(recent) < 2:
            return "FLAT", 0.0

        first  = recent[0]["price"]
        last   = recent[-1]["price"]
        change = (last - first) / first * 100

        if change >= VEL_THRESHOLD:
            signal = "BUY"
        elif change <= -VEL_THRESHOLD:
            signal = "SELL"
        else:
            signal = "FLAT"

        print(
            f"[VEL] {signal} | "
            f"Change={change:.4f}%"
        )
        return signal, change

def get_combined_signal():
    """2/3 Rule"""
    ob_sig,   ob_ratio, spread = get_ob_signal()
    flow_sig, flow_pct         = get_flow_signal()
    vel_sig,  vel_change       = get_vel_signal()

    set_state(
        ob_signal=ob_sig,
        flow_signal=flow_sig,
        vel_signal=vel_sig,
    )

    signals   = [ob_sig, flow_sig, vel_sig]
    buy_count  = signals.count("BUY")
    sell_count = signals.count("SELL")

    if buy_count >= 2:
        return "BUY", buy_count, ob_sig, flow_sig, vel_sig, spread
    elif sell_count >= 2:
        return "SELL", sell_count, ob_sig, flow_sig, vel_sig, spread
    else:
        return "FLAT", 0, ob_sig, flow_sig, vel_sig, spread

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  RISK MANAGER
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def check_risk():
    st = get_state()

    if not st["bot_active"]:
        return False, st["pause_reason"]

    # Daily loss check
    cap       = st["capital"]
    daily_lim = cap * MAX_DAILY_LOSS_PCT / 100

    if st["daily_loss"] >= daily_lim:
        reason = (
            f"Daily loss limit! "
            f"{st['daily_loss']:.2f} USDT"
        )
        set_state(
            bot_active=False,
            pause_reason=reason
        )
        send_tg(
            f"🛑 BOT PAUSED\n{reason}",
            urgent=True
        )
        return False, reason

    # Consecutive loss check
    if st["consec_loss"] >= MAX_CONSEC_LOSS:
        reason = (
            f"Max consecutive losses! "
            f"({MAX_CONSEC_LOSS})"
        )
        set_state(
            bot_active=False,
            pause_reason=reason
        )
        send_tg(
            f"🛑 BOT PAUSED\n{reason}",
            urgent=True
        )
        return False, reason

    # Daily trade limit
    if st["daily_trades"] >= MAX_DAILY_TRADES:
        reason = f"Daily trade limit hit!"
        set_state(
            bot_active=False,
            pause_reason=reason
        )
        return False, reason

    return True, ""

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  TRADE EXECUTOR
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def execute_trade(signal, price, capital, sym_info):
    qty = calc_qty(capital, price, sym_info)
    if qty <= 0:
        print("[EXEC] Qty = 0")
        return capital

    # Entry price (limit - thoda better)
    if signal == "BUY":
        entry_px = round(price - 0.01, 2)
        tp_px    = round(entry_px * (1 + TP_PCT/100), 2)
        sl_px    = round(entry_px * (1 - SL_PCT/100), 2)
        tp_side  = "SELL"
        sl_side  = "SELL"
    else:
        entry_px = round(price + 0.01, 2)
        tp_px    = round(entry_px * (1 - TP_PCT/100), 2)
        sl_px    = round(entry_px * (1 + SL_PCT/100), 2)
        tp_side  = "BUY"
        sl_side  = "BUY"

    # Entry limit order
    entry_id = place_limit_entry(signal, entry_px, qty)
    if not entry_id:
        return capital

    set_state(position="PENDING")

    # 3 sec wait for fill
    filled     = False
    fill_price = entry_px

    for _ in range(30):
        time.sleep(0.1)
        status = get_order(entry_id)
        if not status:
            continue
        if status.get("status") == "FILLED":
            fill_price = float(
                status.get("avgPrice", entry_px)
            )
            filled = True
            break
        elif status.get("status") in [
            "CANCELED", "EXPIRED", "REJECTED"
        ]:
            break

    if not filled:
        cancel_order(entry_id)
        set_state(position=None)
        print("[EXEC] Entry miss - canceled")
        return capital

    # Fill hua!
    print(f"[FILLED] {signal} {qty}@{fill_price:.2f} ✅")

    # Recalculate TP/SL
    if signal == "BUY":
        tp_px = round(fill_price * (1 + TP_PCT/100), 2)
        sl_px = round(fill_price * (1 - SL_PCT/100), 2)
    else:
        tp_px = round(fill_price * (1 - TP_PCT/100), 2)
        sl_px = round(fill_price * (1 + SL_PCT/100), 2)

    entry_fee = fill_price * qty * MAKER_FEE

    # TP limit order
    tp_id = place_limit_tp(tp_side, tp_px, qty)

    set_state(
        position="OPEN",
        side=signal,
        entry_price=fill_price,
        tp_price=tp_px,
        sl_price=sl_px,
        pos_size=qty,
        entry_time=time.time(),
    )

    exp_win  = round(fill_price * qty * TP_PCT/100, 4)
    exp_loss = round(fill_price * qty * SL_PCT/100, 4)
    st       = get_state()

    send_tg(
        f"🚀 ENTRY #{st['trades']+1}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Mode    : {MODE}\n"
        f"Side    : {signal}\n"
        f"Entry   : {fill_price:.2f}\n"
        f"TP      : {tp_px:.2f}\n"
        f"SL      : {sl_px:.2f}\n"
        f"Qty     : {qty}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Exp Win : +{exp_win} USDT\n"
        f"Exp Loss: -{exp_loss} USDT\n"
        f"━━━━━━━━━━━━━━━━━━━━━━"
    )

    # Monitor position
    new_capital = monitor_position(
        signal, fill_price,
        tp_px, sl_px,
        tp_side, sl_side,
        tp_id, qty,
        entry_fee, capital
    )

    return new_capital

def monitor_position(
    side, fill_price,
    tp_px, sl_px,
    tp_side, sl_side,
    tp_id, qty,
    entry_fee, capital
):
    start_time = time.time()
    st         = get_state()
    trade_num  = st["trades"] + 1

    while True:
        elapsed = time.time() - start_time

        with _price_lock:
            cur_price = _cur_price

        # TP check
        if tp_id:
            tp_status = get_order(tp_id)
            if tp_status and tp_status.get(
                "status"
            ) == "FILLED":
                exit_px  = float(
                    tp_status.get("avgPrice", tp_px)
                )
                exit_fee = exit_px * qty * MAKER_FEE
                return finish_trade(
                    side, fill_price, exit_px,
                    qty, entry_fee, exit_fee,
                    "TP ✅", elapsed, capital,
                    trade_num
                )

        # SL check
        sl_hit = (
            (side == "BUY" and cur_price <= sl_px) or
            (side == "SELL" and cur_price >= sl_px)
        )
        max_hit = elapsed >= MAX_HOLD

        if sl_hit or max_hit:
            reason = "SL ❌" if sl_hit else "MAX HOLD ⏰"

            if tp_id:
                cancel_order(tp_id)

            _, exit_px = place_market_sl(sl_side, qty)
            if not exit_px or exit_px == 0:
                exit_px = cur_price

            exit_fee = exit_px * qty * TAKER_FEE
            return finish_trade(
                side, fill_price, exit_px,
                qty, entry_fee, exit_fee,
                reason, elapsed, capital,
                trade_num
            )

        time.sleep(0.05)

def finish_trade(
    side, entry, exit_p,
    qty, entry_fee, exit_fee,
    reason, elapsed, capital,
    trade_num
):
    # PnL
    if side == "BUY":
        gross = (exit_p - entry) * qty
    else:
        gross = (entry - exit_p) * qty

    total_fee   = entry_fee + exit_fee
    net_pnl     = gross - total_fee
    new_capital = capital + net_pnl

    # State update
    st      = get_state()
    trades  = st["trades"] + 1
    wins    = st["wins"]
    losses  = st["losses"]
    consec  = st["consec_loss"]
    d_loss  = st["daily_loss"]
    net     = st["net_pnl"] + net_pnl
    best    = st["best"]
    worst   = st["worst"]

    is_win = net_pnl > 0

    if is_win:
        wins  += 1
        consec = 0
        icon   = "✅"
        label  = "WIN"
    else:
        losses += 1
        consec += 1
        icon    = "❌"
        label   = "LOSS"
        d_loss += abs(net_pnl)

    if net_pnl > best:
        best = net_pnl
    if worst == 0 or net_pnl < worst:
        worst = net_pnl

    wr = round(wins / max(1, trades) * 100, 1)

    set_state(
        capital=new_capital,
        trades=trades,
        wins=wins,
        losses=losses,
        consec_loss=consec,
        daily_loss=d_loss,
        daily_trades=st["daily_trades"] + 1,
        net_pnl=net,
        best=best,
        worst=worst,
        position=None,
        side=None,
        entry_price=0.0,
        tp_price=0.0,
        sl_price=0.0,
        pos_size=0.0,
        entry_time=None,
    )

    save_capital(new_capital)

    save_trade({
        "num"    : trade_num,
        "date"   : datetime.now().strftime("%d/%m/%Y"),
        "time"   : datetime.now().strftime("%H:%M:%S"),
        "mode"   : MODE,
        "side"   : side,
        "entry"  : round(entry, 2),
        "exit"   : round(exit_p, 2),
        "qty"    : qty,
        "gross"  : round(gross, 4),
        "fee"    : round(total_fee, 4),
        "net_pnl": round(net_pnl, 4),
        "capital": round(new_capital, 4),
        "dur"    : f"{elapsed:.1f}s",
        "reason" : reason,
        "result" : label,
    })

    print(
        f"[#{trade_num}] {label} | "
        f"{side} | {reason} | "
        f"Net={net_pnl:+.4f} | "
        f"Cap={new_capital:.2f} | "
        f"WR={wr}%"
    )

    send_tg(
        f"{icon} {label} #{trade_num}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Side   : {side}\n"
        f"Reason : {reason}\n"
        f"Entry  : {entry:.2f}\n"
        f"Exit   : {exit_p:.2f}\n"
        f"Time   : {elapsed:.1f}s\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Gross  : {gross:+.4f}\n"
        f"Fee    : {total_fee:+.4f}\n"
        f"NET    : {net_pnl:+.4f} USDT\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Capital: {new_capital:.4f}\n"
        f"WR     : {wr}%\n"
        f"Trades : {trades}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━"
    )

    return new_capital

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  UPDATE WORKER
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def update_worker():
    time.sleep(60)
    while True:
        try:
            st    = get_state()
            cap   = st["capital"]
            scap  = st["start_cap"]
            growth = round(cap - scap, 4)
            growp  = round(
                growth / max(1, scap) * 100, 2
            )
            wr = round(
                st["wins"] /
                max(1, st["trades"]) * 100, 1
            )
            now   = datetime.now().strftime(
                "%Y-%m-%d %H:%M"
            )
            daily = get_daily_stats()

            pos_txt = ""
            if st["position"] == "OPEN":
                with _price_lock:
                    cp = _cur_price
                pnl_now = (
                    (cp - st["entry_price"]) *
                    st["pos_size"]
                    if st["side"] == "BUY"
                    else
                    (st["entry_price"] - cp) *
                    st["pos_size"]
                )
                pos_txt = (
                    f"POSITION\n"
                    f"Side  : {st['side']}\n"
                    f"Entry : {st['entry_price']:.2f}\n"
                    f"Now   : {cp:.2f}\n"
                    f"PnL   : {pnl_now:+.4f}\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                )

            msg = (
                f"📊 STATUS UPDATE\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"{now} | {MODE}\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"{pos_txt}"
                f"STATS\n"
                f"Trades : {st['trades']}\n"
                f"Wins   : {st['wins']} ✅\n"
                f"Losses : {st['losses']} ❌\n"
                f"WR     : {wr}%\n"
                f"Net    : {st['net_pnl']:+.4f}\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"CAPITAL\n"
                f"Start  : {scap:.2f}\n"
                f"Now    : {cap:.4f}\n"
                f"Growth : {growth:+.4f}\n"
                f"ROI    : {growp:+.2f}%\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"Active : {st['bot_active']}\n"
                f"D/Loss : {st['daily_loss']:.4f}\n"
                f"━━━━━━━━━━━━━━━━━━━━━━"
            )

            if daily:
                msg += (
                    f"\nTODAY\n"
                    f"Trades : {daily['total']}\n"
                    f"WR     : {daily['win_rate']}%\n"
                    f"PnL    : {daily['pnl']:+.4f}\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━"
                )

            send_tg(msg)

        except Exception as e:
            print(f"[UPD ERR] {e}")

        time.sleep(UPDATE_MIN * 60)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  DAILY REPORT
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def daily_worker():
    while True:
        try:
            ist = timezone(timedelta(hours=5, minutes=30))
            now = datetime.now(ist)

            if now.hour == 23 and now.minute == 59:
                daily = get_daily_stats()
                st    = get_state()
                today = now.strftime("%d/%m/%Y")

                # Daily reset
                set_state(
                    daily_loss=0.0,
                    daily_trades=0,
                    bot_active=True,
                    pause_reason="",
                    consec_loss=0,
                )

                if daily:
                    growth = round(
                        st["capital"] - st["start_cap"], 4
                    )
                    roi = round(
                        growth / max(1, st["start_cap"]) * 100, 2
                    )
                    send_tg(
                        f"📅 DAILY REPORT\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"{today} | {MODE}\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"Trades : {daily['total']}\n"
                        f"Wins   : {daily['wins']} ✅\n"
                        f"Losses : {daily['losses']} ❌\n"
                        f"WR     : {daily['win_rate']}%\n"
                        f"PnL    : {daily['pnl']:+.4f}\n"
                        f"Best   : +{daily['best']:.4f}\n"
                        f"Worst  : {daily['worst']:.4f}\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"Capital: {st['capital']:.4f}\n"
                        f"Growth : {growth:+.4f}\n"
                        f"ROI    : {roi:+.2f}%\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━"
                    )
                else:
                    send_tg(
                        f"📅 DAILY REPORT\n"
                        f"{today}\n"
                        f"Aaj koi trade nahi hua"
                    )
                time.sleep(70)

        except Exception as e:
            print(f"[DAILY ERR] {e}")
        time.sleep(30)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  MAIN ENGINE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def run_engine():
    print("=" * 45)
    print("  ETH HFT BOT v4.0")
    print(f"  MODE: {MODE}")
    print("=" * 45)

    # Symbol info
    sym_info = get_symbol_info()
    print(f"[SYM] {sym_info}")

    # Setup exchange
    setup_exchange()

    # Balance fetch
    balance = get_balance()
    saved   = load_capital()

    if saved and saved > 0:
        capital = saved
    elif balance and balance > 0:
        capital = balance
        save_capital(capital)
    else:
        capital = 1052.0
        save_capital(capital)

    set_state(
        capital=capital,
        start_cap=capital,
        bot_active=True,
    )

    print(f"[CAP] {capital:.4f} USDT")

    # WebSocket ready wait
    print("[WS] Data aane ka wait...")
    time.sleep(5)

    send_tg(
        f"🤖 ETH HFT BOT v4.0\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Mode    : {MODE}\n"
        f"Capital : {capital:.2f} USDT\n"
        f"Leverage: {LEVERAGE}x\n"
        f"TP      : {TP_PCT}%\n"
        f"SL      : {SL_PCT}%\n"
        f"Hold    : {MAX_HOLD}s\n"
        f"Strategy: OB+Flow+Vel\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Bot Live! 🚀\n"
        f"━━━━━━━━━━━━━━━━━━━━━━"
    )

    cooldown_end = 0.0

    while True:
        try:
            st = get_state()

            # Position open hai?
            if st["position"] is not None:
                time.sleep(0.05)
                continue

            # Cooldown check
            if time.time() < cooldown_end:
                remaining = int(cooldown_end - time.time())
                print(f"[CD] {remaining}s baki...")
                time.sleep(0.5)
                continue

            # Risk check
            ok, reason = check_risk()
            if not ok:
                print(f"[RISK] {reason}")
                time.sleep(1)
                continue

            # Signal
            signal, strength, ob, flow, vel, spread = (
                get_combined_signal()
            )

            with _price_lock:
                price = _cur_price

            if price <= 0:
                time.sleep(0.05)
                continue

            # Set price state
            set_state(last_price=price)

            if signal in ["BUY", "SELL"]:
                print(
                    f"[SIGNAL] {signal} | "
                    f"OB={ob} FL={flow} VL={vel} | "
                    f"P={price:.2f} | "
                    f"Strength={strength}/3"
                )

                capital = st["capital"]
                new_cap = execute_trade(
                    signal, price,
                    capital, sym_info
                )

                # Cooldown set
                if new_cap > capital:
                    cooldown_end = (
                        time.time() + COOLDOWN_WIN
                    )
                else:
                    st2 = get_state()
                    cd  = (
                        COOLDOWN_2LOSS
                        if st2["consec_loss"] >= 2
                        else COOLDOWN_LOSS
                    )
                    cooldown_end = time.time() + cd

            else:
                print(
                    f"[WAIT] "
                    f"OB={ob} FL={flow} VL={vel} | "
                    f"P={price:.2f}"
                )

            time.sleep(0.05)

        except Exception as e:
            err = str(e)
            print(f"[ENGINE ERR] {err}")
            if "429" in err:
                time.sleep(30)
            elif "connection" in err.lower():
                time.sleep(5)
            else:
                time.sleep(2)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  START
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

if __name__ == "__main__":

    # API check
    if not API_KEY or not API_SECRET:
        print("❌ API_KEY aur API_SECRET set karo!")
        print("Render Environment Variables mein daalo")
        exit(1)

    print("=" * 45)
    print("  ETH HFT BOT v4.0 STARTING")
    print(f"  MODE: {MODE}")
    print("=" * 45)

    # WebSockets start
    start_ws(
        stream=f"{SYMBOL_WS}@depth@100ms",
        handler=on_ob_msg,
        name="OrderBook"
    )
    start_ws(
        stream=f"{SYMBOL_WS}@aggTrade",
        handler=on_trade_msg,
        name="TradeFlow"
    )

    # Threads
    threads = [
        threading.Thread(
            target=run_server,
            name="Flask",
            daemon=True
        ),
        threading.Thread(
            target=tg_worker,
            name="Telegram",
            daemon=True
        ),
        threading.Thread(
            target=update_worker,
            name="Update",
            daemon=True
        ),
        threading.Thread(
            target=daily_worker,
            name="Daily",
            daemon=True
        ),
        threading.Thread(
            target=run_engine,
            name="Engine",
            daemon=True
        ),
    ]

    for t in threads:
        t.start()
        print(f"[✅] {t.name}")
        time.sleep(0.3)

    print("=" * 45)
    print(f"[✅] {MODE} Mode")
    print("[✅] Bot Live 24/7!")
    print("=" * 45)

    while True:
        time.sleep(60)
