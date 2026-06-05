"""
ETH High Frequency Trading Bot v4.0
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Exchange : MEXC Futures
Symbol   : ETH/USDT
Capital  : 10,000 USDT
Use      : 9,000 USDT (90%)
Leverage : 5x
Exposure : 45,000 USDT

TP       : 0.08% = +27 USDT net
SL       : 0.04% = -27 USDT net
Fee      : 0.02% =   9 USDT
Max Hold : 2 seconds
Scan     : 10ms
RR Ratio : 1:1
Break Even: 50% win rate

Strategy : Order Book + Trade Flow
           + Price Velocity
           2/3 signals = Entry
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import ccxt
import requests
import threading
import time
import json
import os
from flask import Flask
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor

app = Flask(__name__)

@app.route('/')
def home():
    return "ETH HFT Bot v4.0 Running!"

def run_server():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  CONFIG
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SYMBOL     = "ETH/USDT:USDT"
API_KEY    = ""
API_SECRET = ""
BOT_TOKEN  = "8161773850:AAFcWw3UnlSe2TrMooB2uvgZQZUqIW0zW2w"
CHAT_ID    = "7102976298"

# ── Capital ───────────────────────────────
CAPITAL     = 10000.0    # 10,000 USDT
CAPITAL_USE = 90         # 90% = 9,000 USDT
LEVERAGE    = 5          # 5x
# Exposure  = 45,000 USDT

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  MEXC FEE
#  Maker : 0.00% FREE
#  Taker : 0.01%
#  Total : 0.02% per trade
#
#  Example:
#  45000 × 0.02% = 9 USDT per trade
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

MEXC_MAKER_FEE = 0.0000   # 0.00% FREE
MEXC_TAKER_FEE = 0.0001   # 0.01%
MEXC_ENTRY_FEE = MEXC_TAKER_FEE
MEXC_EXIT_FEE  = MEXC_TAKER_FEE
MEXC_TOTAL_FEE = MEXC_ENTRY_FEE + MEXC_EXIT_FEE

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  TRADE CONFIG
#
#  TP = 0.08%
#  Gross TP = 45000 × 0.08% = 36 USDT
#  Fee      =                   9 USDT
#  NET TP   =                 +27 USDT ✅
#
#  SL = 0.04%
#  Gross SL = 45000 × 0.04% = 18 USDT
#  Fee      =                   9 USDT
#  NET SL   =                 -27 USDT
#
#  Risk:Reward = 1:1 ✅
#  Break Even  = 50% win rate ✅
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

TP_PCT   = 0.08   # 0.08% target
SL_PCT   = 0.04   # 0.04% stop loss
MAX_HOLD = 2      # 2 seconds max hold

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  SPEED CONFIG
#  Ultra fast HFT
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SCAN_INTERVAL    = 0.01   # 10ms = 100 scans/sec
ANALYSIS_WORKERS = 6      # 6 parallel threads

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  COOLDOWN
#  HFT ke liye minimum cooldown
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

COOLDOWN_WIN   = 0.0    # No wait!
COOLDOWN_LOSS  = 0.0    # No wait!
COOLDOWN_2LOSS = 0.1    # 100ms only

# ── Spread ────────────────────────────────
MAX_SPREAD = 0.03   # Tight spread only

# ── Order Book ────────────────────────────
OB_LEVELS    = 5    # Top 5 levels (fast)
OB_IMBALANCE = 1.3  # Lower = More signals

# ── Update Interval ───────────────────────
UPDATE_INTERVAL = 1800   # 30 min


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  FILES
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

FILES = {
    "capital":  "capital_eth.txt",
    "cooldown": "cooldown_eth.txt",
    "history":  "history_eth.json",
    "fees":     "fees_eth.json",
    "stats":    "stats_eth.json",
}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  STATE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

state_lock = threading.Lock()

state = {
    # Position
    "position":     None,
    "entry_price":  0.0,
    "entry_time":   None,
    "sl_price":     0.0,
    "tp_price":     0.0,
    "pos_size":     0.0,
    "capital_used": 0.0,

    # Capital
    "capital":      CAPITAL,

    # Market
    "last_price":   0.0,

    # Signals
    "last_signal":  "WAIT",
    "ob_signal":    "FLAT",
    "flow_signal":  "FLAT",
    "vel_signal":   "FLAT",
    "velocity":     0.0,

    # Stats
    "trade_count":  0,
    "win_count":    0,
    "loss_count":   0,
    "total_fees":   0.0,
    "gross_pnl":    0.0,
    "net_pnl":      0.0,
}

def update_state(**kwargs):
    with state_lock:
        for k, v in kwargs.items():
            if k in state:
                state[k] = v

def get_state(key):
    with state_lock:
        return state.get(key)

def get_all_state():
    with state_lock:
        return dict(state)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  MEXC FEE CALCULATOR
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def calculate_fee(capital_used, leverage):
    """
    MEXC Fee Calculator

    Exposure   = capital × leverage
    Entry Fee  = exposure × 0.01%
    Exit Fee   = exposure × 0.01%
    Total      = exposure × 0.02%

    9000 × 5 = 45000
    45000 × 0.02% = 9 USDT
    """
    exposure  = capital_used * leverage
    entry_fee = exposure * MEXC_ENTRY_FEE
    exit_fee  = exposure * MEXC_EXIT_FEE
    total_fee = entry_fee + exit_fee

    return {
        "exposure":  round(exposure, 4),
        "entry_fee": round(entry_fee, 6),
        "exit_fee":  round(exit_fee, 6),
        "total_fee": round(total_fee, 6),
    }


def calc_pnl(
        side, entry, exit_p,
        pos_size, capital_used, leverage):
    """
    Full PnL Calculator with MEXC fee

    Gross = price_diff × pos_size
    Fee   = exposure × 0.02%
    Net   = Gross - Fee
    """
    # Gross PnL
    if side == "BUY":
        gross = (exit_p - entry) * pos_size
    else:
        gross = (entry - exit_p) * pos_size

    # Fee
    fee_data  = calculate_fee(
        capital_used, leverage)
    total_fee = fee_data["total_fee"]

    # Net
    net = gross - total_fee

    return {
        "gross":     round(gross, 6),
        "entry_fee": fee_data["entry_fee"],
        "exit_fee":  fee_data["exit_fee"],
        "total_fee": total_fee,
        "net":       round(net, 6),
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  CAPITAL
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def load_capital():
    try:
        with open(FILES["capital"], "r") as f:
            cap = float(f.read().strip())
            print(f"[CAPITAL] {cap:.2f} USDT")
            return cap
    except Exception:
        save_capital(CAPITAL)
        return CAPITAL

def save_capital(capital):
    try:
        with open(FILES["capital"], "w") as f:
            f.write(str(round(capital, 6)))
    except Exception as e:
        print(f"[CAPITAL ERR] {e}")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  COOLDOWN
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def save_cooldown(end_time):
    try:
        with open(FILES["cooldown"], "w") as f:
            f.write(str(end_time))
    except Exception:
        pass

def load_cooldown():
    try:
        with open(FILES["cooldown"], "r") as f:
            val = float(f.read().strip())
            if val > time.time():
                return val
    except Exception:
        pass
    return None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  TRADE HISTORY
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

history_lock = threading.Lock()

def save_trade(
        side, entry, exit_p,
        gross, net, fee,
        capital, duration, label,
        trade_num):
    try:
        with history_lock:
            try:
                with open(
                        FILES["history"], "r",
                        encoding="utf-8") as f:
                    history = json.load(f)
            except Exception:
                history = []

            history.append({
                "num":      trade_num,
                "date":     datetime.now()
                    .strftime("%d/%m/%Y"),
                "time":     datetime.now()
                    .strftime("%H:%M:%S.%f")[:-3],
                "symbol":   "ETH/USDT",
                "side":     side,
                "entry":    round(entry, 4),
                "exit":     round(exit_p, 4),
                "gross":    round(gross, 4),
                "fee":      round(fee, 4),
                "net":      round(net, 4),
                "capital":  round(capital, 4),
                "duration": duration,
                "result":   (
                    "WIN" if net > 0
                    else "LOSS"),
                "label":    label,
            })

            # Last 10000 trades rakho
            if len(history) > 10000:
                history = history[-10000:]

            with open(
                    FILES["history"], "w",
                    encoding="utf-8") as f:
                json.dump(
                    history, f, indent=2)

    except Exception as e:
        print(f"[HISTORY ERR] {e}")


def get_daily_stats():
    try:
        with open(
                FILES["history"], "r",
                encoding="utf-8") as f:
            history = json.load(f)
    except Exception:
        return None

    today  = datetime.now().strftime(
        "%d/%m/%Y")
    trades = [
        t for t in history
        if t["date"] == today]

    if not trades:
        return None

    total      = len(trades)
    wins       = len([
        t for t in trades
        if t["result"] == "WIN"])
    losses     = total - wins
    win_rate   = round(
        (wins / total) * 100, 1)
    net_pnl    = round(
        sum(t["net"]   for t in trades), 4)
    gross_pnl  = round(
        sum(t["gross"] for t in trades), 4)
    total_fees = round(
        sum(t["fee"]   for t in trades), 4)

    # Hourly trades
    hour_now   = datetime.now().strftime("%H")
    hour_trades = len([
        t for t in trades
        if t["time"][:2] == hour_now])

    return {
        "total":       total,
        "wins":        wins,
        "losses":      losses,
        "win_rate":    win_rate,
        "net_pnl":     net_pnl,
        "gross_pnl":   gross_pnl,
        "total_fees":  total_fees,
        "hour_trades": hour_trades,
        "best":  round(
            max(t["net"] for t in trades), 4),
        "worst": round(
            min(t["net"] for t in trades), 4),
        "capital": trades[-1]["capital"],
        "avg_net": round(net_pnl / total, 4),
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  EXCHANGE - MEXC
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def get_exchange():
    while True:
        try:
            ex = ccxt.mexc({
                "apiKey":          API_KEY,
                "secret":          API_SECRET,
                "enableRateLimit": True,
                "rateLimit":       10,
                "options": {
                    "defaultType":
                        "swap",
                    "adjustForTimeDifference":
                        True,
                },
            })
            ex.load_markets()
            print("[MEXC] Connected ✅")
            return ex
        except Exception as e:
            print(
                f"[MEXC RECONNECT] "
                f"{e} — 15s...")
            time.sleep(15)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  ULTRA FAST DATA CACHE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

cache_lock = threading.Lock()
cache = {
    "ticker":       None,
    "orderbook":    None,
    "trades":       None,
    "ticker_ts":    0,
    "orderbook_ts": 0,
    "trades_ts":    0,
}

# Cache TTL
TICKER_TTL    = 0.01   # 10ms
ORDERBOOK_TTL = 0.05   # 50ms
TRADES_TTL    = 0.1    # 100ms


def fetch_ticker(ex):
    now = time.time()
    with cache_lock:
        if (cache["ticker"] is not None and
                now - cache["ticker_ts"]
                < TICKER_TTL):
            return cache["ticker"]

    for i in range(3):
        try:
            t     = ex.fetch_ticker(SYMBOL)
            price = float(t["last"])
            with cache_lock:
                cache["ticker"]    = price
                cache["ticker_ts"] = time.time()
            return price
        except Exception as e:
            if "429" in str(e):
                time.sleep((i+1))
            else:
                time.sleep(0.05)
    return None


def fetch_orderbook(ex):
    now = time.time()
    with cache_lock:
        if (cache["orderbook"] is not None and
                now - cache["orderbook_ts"]
                < ORDERBOOK_TTL):
            return cache["orderbook"]

    for i in range(3):
        try:
            ob = ex.fetch_order_book(
                SYMBOL, limit=OB_LEVELS)
            with cache_lock:
                cache["orderbook"]    = ob
                cache["orderbook_ts"] = time.time()
            return ob
        except Exception as e:
            if "429" in str(e):
                time.sleep((i+1))
            else:
                time.sleep(0.05)
    return None


def fetch_trades(ex):
    now = time.time()
    with cache_lock:
        if (cache["trades"] is not None and
                now - cache["trades_ts"]
                < TRADES_TTL):
            return cache["trades"]

    for i in range(3):
        try:
            trades = ex.fetch_trades(
                SYMBOL, limit=50)
            with cache_lock:
                cache["trades"]    = trades
                cache["trades_ts"] = time.time()
            return trades
        except Exception as e:
            if "429" in str(e):
                time.sleep((i+1))
            else:
                time.sleep(0.05)
    return None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  TELEGRAM - ASYNC
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

tg_queue = []
tg_lock  = threading.Lock()

def send_telegram(msg):
    with tg_lock:
        tg_queue.append(str(msg))

def telegram_worker():
    url = (
        f"https://api.telegram.org"
        f"/bot{BOT_TOKEN}/sendMessage")
    while True:
        try:
            msg = None
            with tg_lock:
                if tg_queue:
                    msg = tg_queue.pop(0)

            if msg:
                for _ in range(3):
                    try:
                        requests.post(
                            url,
                            data={
                                "chat_id":
                                    CHAT_ID,
                                "text":
                                    f"[ETH HFT] "
                                    f"{msg}",
                            },
                            timeout=10)
                        break
                    except Exception:
                        time.sleep(1)
            else:
                time.sleep(0.05)

        except Exception as e:
            print(f"[TG ERR] {e}")
            time.sleep(1)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  SIGNAL ANALYSIS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# ── 1. Order Book ─────────────────────────
def analyze_ob(ex):
    """
    Order Book Imbalance

    Bids >> Asks = BUY pressure
    Asks >> Bids = SELL pressure
    """
    try:
        ob = fetch_orderbook(ex)
        if ob is None:
            return "FLAT", 0.0, 0.0

        bids = ob["bids"]
        asks = ob["asks"]

        if not bids or not asks:
            return "FLAT", 0.0, 0.0

        best_bid = float(bids[0][0])
        best_ask = float(asks[0][0])

        # Spread check
        spread = (
            (best_ask - best_bid) /
            best_bid) * 100

        if spread > MAX_SPREAD:
            return "FLAT", 0.0, spread

        # Volume
        bid_vol = sum(
            float(b[1])
            for b in bids[:OB_LEVELS])
        ask_vol = sum(
            float(a[1])
            for a in asks[:OB_LEVELS])

        if ask_vol == 0:
            return "FLAT", 0.0, spread

        ratio = bid_vol / ask_vol

        if ratio >= OB_IMBALANCE:
            signal = "BUY"
        elif ratio <= (1 / OB_IMBALANCE):
            signal = "SELL"
        else:
            signal = "FLAT"

        return signal, ratio, spread

    except Exception as e:
        print(f"[OB ERR] {e}")
        return "FLAT", 0.0, 0.0


# ── 2. Trade Flow ─────────────────────────
def analyze_flow(ex):
    """
    Recent trade direction

    Buy volume > Sell = BUY
    Sell volume > Buy = SELL
    """
    try:
        trades = fetch_trades(ex)
        if not trades:
            return "FLAT", 0.0

        buy_vol  = 0.0
        sell_vol = 0.0

        for t in trades:
            side = t.get("side", "")
            amt  = float(
                t.get("amount", 0))
            if side == "buy":
                buy_vol  += amt
            elif side == "sell":
                sell_vol += amt

        if sell_vol == 0:
            return "FLAT", 0.0

        ratio = buy_vol / sell_vol

        if ratio >= 1.3:
            signal = "BUY"
        elif ratio <= 0.77:
            signal = "SELL"
        else:
            signal = "FLAT"

        return signal, ratio

    except Exception as e:
        print(f"[FLOW ERR] {e}")
        return "FLAT", 0.0


# ── 3. Price Velocity ─────────────────────
ph_lock = threading.Lock()
ph      = []   # Price history

def update_ph(price):
    with ph_lock:
        ph.append({
            "p": price,
            "t": time.time(),
        })
        cutoff = time.time() - 5
        while ph and ph[0]["t"] < cutoff:
            ph.pop(0)

def analyze_velocity():
    """
    Price speed & direction

    Moving up fast   = BUY
    Moving down fast = SELL
    """
    try:
        with ph_lock:
            if len(ph) < 3:
                return "FLAT", 0.0

            data = ph[-20:]
            if len(data) < 2:
                return "FLAT", 0.0

            first = data[0]["p"]
            last  = data[-1]["p"]
            t1    = data[0]["t"]
            t2    = data[-1]["t"]

            if t2 == t1:
                return "FLAT", 0.0

            pct = (last - first) / first * 100

            # HFT ke liye low threshold
            if pct > 0.006:
                return "BUY", pct
            elif pct < -0.006:
                return "SELL", pct
            else:
                return "FLAT", pct

    except Exception as e:
        print(f"[VEL ERR] {e}")
        return "FLAT", 0.0


# ── Combined Signal ───────────────────────
def get_signal(ob_s, flow_s, vel_s):
    """
    
