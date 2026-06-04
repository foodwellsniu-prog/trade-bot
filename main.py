"""
ETH High Frequency Scalping Bot v3.0
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Exchange : MEXC (Zero Maker Fee)
Strategy : Order Book + Trade Flow 
           + Price Velocity
           + Trend Filter (NEW)
Symbol   : ETH/USDT
Capital  : 35 USDT
Leverage : 20x
TP       : 0.08%
SL       : 0.03%
Max Hold : 30 seconds
Fee      : 0.01% Taker (MEXC)
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

app = Flask(__name__)

@app.route('/')
def home():
    return "ETH HF Scalping Bot v3.0 - MEXC Running!"

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
CAPITAL     = 35.0
CAPITAL_USE = 90
LEVERAGE    = 20

# ── Trade Config ──────────────────────────
TP_PCT   = 0.08
SL_PCT   = 0.03
MAX_HOLD = 30

# ── MEXC Fee ──────────────────────────────
TAKER_FEE = 0.01

# ── Speed ─────────────────────────────────
SCAN_INTERVAL = 1

# ── Cooldown ──────────────────────────────
COOLDOWN_WIN   = 2
COOLDOWN_LOSS  = 5
COOLDOWN_2LOSS = 10

# ── Spread ────────────────────────────────
MAX_SPREAD = 0.05

# ── Order Book Config ─────────────────────
OB_LEVELS    = 10
OB_IMBALANCE = 1.5

# ── Trend Filter Config (NEW) ─────────────
TREND_CANDLES  = 20   # Last 20 candles
TREND_TF       = "1m" # 1 minute candles
EMA_FAST       = 9    # Fast EMA
EMA_SLOW       = 21   # Slow EMA

# ── Update ────────────────────────────────
UPDATE_INTERVAL = 1800


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  FEE CALCULATOR
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def calc_fees(exposure):
    entry_fee = exposure * TAKER_FEE / 100
    exit_fee  = exposure * TAKER_FEE / 100
    return round(entry_fee + exit_fee, 6)

def calc_net_tp(exposure):
    gross = exposure * TP_PCT / 100
    fees  = calc_fees(exposure)
    return round(gross - fees, 6)

def calc_net_sl(exposure):
    gross = exposure * SL_PCT / 100
    fees  = calc_fees(exposure)
    return round(gross + fees, 6)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  FILES
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

FILES = {
    "capital":  "capital_eth.txt",
    "cooldown": "cooldown_eth.txt",
    "history":  "history_eth.json",
    "log":      "log_eth.json",
}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  STATE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

state_lock = threading.Lock()

state = {
    "position":     None,
    "entry_price":  0.0,
    "entry_time":   None,
    "sl_price":     0.0,
    "tp_price":     0.0,
    "pos_size":     0.0,
    "capital_used": 0.0,
    "exposure":     0.0,
    "fees":         0.0,
    "capital":      CAPITAL,
    "last_price":   0.0,
    "last_signal":  "WAIT",
    "ob_signal":    "FLAT",
    "flow_signal":  "FLAT",
    "velocity":     0.0,
    "trend":        "FLAT",
}

def update_state(**kwargs):
    with state_lock:
        for k, v in kwargs.items():
            if k in state:
                state[k] = v

def get_state(key):
    with state_lock:
        return state.get(key)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  CAPITAL
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def load_capital():
    try:
        with open(FILES["capital"], "r") as f:
            cap = float(f.read().strip())
            print(f"[CAPITAL] Loaded: {cap} USDT")
            return cap
    except Exception:
        save_capital(CAPITAL)
        return CAPITAL

def save_capital(capital):
    try:
        with open(FILES["capital"], "w") as f:
            f.write(str(round(capital, 6)))
    except Exception as e:
        print(f"[CAPITAL ERROR] {e}")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  COOLDOWN
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def save_cooldown(end_time):
    try:
        with open(FILES["cooldown"], "w") as f:
            f.write(str(end_time))
    except Exception as e:
        print(f"[COOLDOWN ERROR] {e}")

def load_cooldown():
    try:
        with open(FILES["cooldown"], "r") as f:
            val = float(f.read().strip())
            if val > time.time():
                print(
                    f"[COOLDOWN] "
                    f"{int(val - time.time())}s")
                return val
    except Exception:
        pass
    return None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  TRADE HISTORY
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def save_trade(side, entry, exit_p,
               pnl, fees, capital,
               duration, label, trend):
    try:
        try:
            with open(
                    FILES["history"], "r",
                    encoding="utf-8") as f:
                history = json.load(f)
        except Exception:
            history = []

        history.append({
            "date":     datetime.now().strftime(
                "%d/%m/%Y"),
            "time":     datetime.now().strftime(
                "%H:%M:%S"),
            "symbol":   "ETH",
            "side":     side,
            "entry":    round(entry, 4),
            "exit":     round(exit_p, 4),
            "pnl":      round(pnl, 4),
            "fees":     round(fees, 4),
            "net_pnl":  round(pnl - fees, 4),
            "capital":  round(capital, 4),
            "duration": duration,
            "trend":    trend,
            "result":   (
                "WIN" if (pnl - fees) > 0
                else "LOSS"),
            "label":    label,
        })

        with open(
                FILES["history"], "w",
                encoding="utf-8") as f:
            json.dump(history, f, indent=2)

    except Exception as e:
        print(f"[HISTORY ERROR] {e}")


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
        sum(t.get("net_pnl", t["pnl"])
            for t in trades), 4)
    total_fees = round(
        sum(t.get("fees", 0)
            for t in trades), 4)

    return {
        "total":      total,
        "wins":       wins,
        "losses":     losses,
        "win_rate":   win_rate,
        "net_pnl":    net_pnl,
        "total_fees": total_fees,
        "best":       round(
            max(t.get("net_pnl", t["pnl"])
                for t in trades), 4),
        "worst":      round(
            min(t.get("net_pnl", t["pnl"])
                for t in trades), 4),
        "capital":    trades[-1]["capital"],
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  EXCHANGE — MEXC
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def get_exchange():
    while True:
        try:
            ex = ccxt.mexc({
                "apiKey":          API_KEY,
                "secret":          API_SECRET,
                "enableRateLimit": True,
                "rateLimit":       50,
                "options": {
                    "defaultType": "swap",
                },
            })
            ex.load_markets()
            print("[INFO] MEXC connected ✅")
            return ex
        except Exception as e:
            print(f"[RECONNECT] {e} — 30s...")
            time.sleep(30)


def safe_fetch_ticker(ex):
    for i in range(3):
        try:
            t = ex.fetch_ticker(SYMBOL)
            return float(t["last"])
        except Exception as e:
            if "429" in str(e):
                time.sleep((i+1) * 10)
            else:
                time.sleep(2)
    return None


def safe_fetch_ohlcv(ex, tf="1m", limit=30):
    for i in range(3):
        try:
            bars = ex.fetch_ohlcv(
                SYMBOL,
                timeframe=tf,
                limit=limit)
            return bars
        except Exception as e:
            if "429" in str(e):
                time.sleep((i+1) * 10)
            else:
                time.sleep(2)
    return None


def safe_fetch_orderbook(ex, limit=10):
    for i in range(3):
        try:
            ob = ex.fetch_order_book(
                SYMBOL, limit=limit)
            return ob
        except Exception as e:
            if "429" in str(e):
                time.sleep((i+1) * 10)
            else:
                time.sleep(2)
    return None


def safe_fetch_trades(ex, limit=50):
    for i in range(3):
        try:
            trades = ex.fetch_trades(
                SYMBOL, limit=limit)
            return trades
        except Exception as e:
            if "429" in str(e):
                time.sleep((i+1) * 10)
            else:
                time.sleep(2)
    return None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  TELEGRAM
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def send_telegram(message):
    url = (
        f"https://api.telegram.org/bot"
        f"{BOT_TOKEN}/sendMessage")
    for attempt in range(3):
        try:
            r = requests.post(
                url,
                data={
                    "chat_id": CHAT_ID,
                    "text":    message,
                },
                timeout=15)
            if r.status_code == 200:
                return
        except Exception as e:
            print(
                f"[TELEGRAM] "
                f"{attempt+1}/3: {e}")
            time.sleep(3)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  EMA CALCULATOR
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def calc_ema(prices, period):
    """
    EMA calculate karo
    Exponential Moving Average
    """
    if len(prices) < period:
        return None

    k   = 2 / (period + 1)
    ema = sum(prices[:period]) / period

    for price in prices[period:]:
        ema = price * k + ema * (1 - k)

    return round(ema, 4)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  TREND FILTER (NEW)
#  EMA 9 vs EMA 21 se trend detect karo
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def analyze_trend(ex):
    """
    Trend Filter Logic:

    EMA9 > EMA21 = UPTREND   → Sirf BUY lo
    EMA9 < EMA21 = DOWNTREND → Sirf SELL lo
    EMA9 = EMA21 = SIDEWAYS  → Trade mat karo

    Isse bot trend ke against
    trade nahi karega
    """
    try:
        bars = safe_fetch_ohlcv(
            ex,
            tf=TREND_TF,
            limit=TREND_CANDLES + 5)

        if not bars or len(bars) < EMA_SLOW:
            print("[TREND] Data kam hai")
            return "FLAT", 0.0, 0.0

        # Close prices nikalo
        closes = [
            float(bar[4]) for bar in bars]

        # EMA calculate karo
        ema_fast = calc_ema(closes, EMA_FAST)
        ema_slow = calc_ema(closes, EMA_SLOW)

        if ema_fast is None or ema_slow is None:
            return "FLAT", 0.0, 0.0

        # Trend decide karo
        diff = ema_fast - ema_slow
        diff_pct = (diff / ema_slow) * 100

        if ema_fast > ema_slow:
            trend = "UP"
        elif ema_fast < ema_slow:
            trend = "DOWN"
        else:
            trend = "FLAT"

        print(
            f"[TREND] {trend} | "
            f"EMA{EMA_FAST}={ema_fast:.2f} | "
            f"EMA{EMA_SLOW}={ema_slow:.2f} | "
            f"Diff={diff_pct:.4f}%")

        return trend, ema_fast, ema_slow

    except Exception as e:
        print(f"[TREND ERROR] {e}")
        return "FLAT", 0.0, 0.0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  ORDER BOOK ANALYSIS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def analyze_orderbook(ex):
    try:
        ob = safe_fetch_orderbook(
            ex, limit=OB_LEVELS)
        if ob is None:
            return "FLAT", 0.0, 0.0, 0.0

        bids = ob["bids"]
        asks = ob["asks"]

        if not bids or not asks:
            return "FLAT", 0.0, 0.0, 0.0

        best_bid = float(bids[0][0])
        best_ask = float(asks[0][0])

        spread = (
            (best_ask - best_bid) /
            best_bid) * 100

        if spread > MAX_SPREAD:
            print(
                f"[OB] Spread HIGH "
                f"{spread:.4f}% ❌")
            return "FLAT", 0.0, spread, 0.0

        bid_vol = sum(
            float(b[1]) for b in bids[:10])
        ask_vol = sum(
            float(a[1]) for a in asks[:10])

        if ask_vol == 0:
            return "FLAT", 0.0, spread, 0.0

        ratio = bid_vol / ask_vol

        if ratio >= OB_IMBALANCE:
            signal = "BUY"
        elif ratio <= (1 / OB_IMBALANCE):
            signal = "SELL"
        else:
            signal = "FLAT"

        mid_price = (best_bid + best_ask) / 2

        print(
            f"[OB] {signal} | "
            f"BidVol={bid_vol:.2f} | "
            f"AskVol={ask_vol:.2f} | "
            f"Ratio={ratio:.2f} | "
            f"Spread={spread:.4f}%")

        return signal, mid_price, spread, ratio

    except Exception as e:
        print(f"[OB ERROR] {e}")
        return "FLAT", 0.0, 0.0, 0.0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  TRADE FLOW ANALYSIS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def analyze_trade_flow(ex):
    try:
        trades = safe_fetch_trades(
            ex, limit=50)
        if not trades:
            return "FLAT", 0.0, 0.0

        buy_vol  = 0.0
        sell_vol = 0.0

        for t in trades:
            side = t.get("side", "")
            amt  = float(
                t.get("amount", 0))
            if side == "buy":
                buy_vol += amt
            elif side == "sell":
                sell_vol += amt

        if sell_vol == 0:
            return "FLAT", 0.0, 0.0

        ratio = buy_vol / sell_vol

        if ratio >= 1.3:
            signal = "BUY"
        elif ratio <= 0.7:
            signal = "SELL"
        else:
            signal = "FLAT"

        print(
            f"[FLOW] {signal} | "
            f"Buy={buy_vol:.2f} | "
            f"Sell={sell_vol:.2f} | "
            f"Ratio={ratio:.2f}")

        return signal, buy_vol, sell_vol

    except Exception as e:
        print(f"[FLOW ERROR] {e}")
        return "FLAT", 0.0, 0.0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  PRICE VELOCITY
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

price_history = []
price_lock    = threading.Lock()

def update_price_history(price):
    with price_lock:
        price_history.append({
            "price": price,
            "time":  time.time(),
        })
        cutoff = time.time() - 30
        while (price_history and
               price_history[0]["time"] < cutoff):
            price_history.pop(0)

def analyze_velocity():
    try:
        with price_lock:
            if len(price_history) < 3:
                return "FLAT", 0.0

            recent = price_history[-10:]
            if len(recent) < 2:
                return "FLAT", 0.0

            first = recent[0]["price"]
            last  = recent[-1]["price"]
            t1    = recent[0]["time"]
            t2    = recent[-1]["time"]

            if t2 == t1:
                return "FLAT", 0.0

            change    = last - first
            time_diff = t2 - t1
            velocity  = change / time_diff
            pct       = (change / first) * 100

            if pct > 0.01:
                signal = "BUY"
            elif pct < -0.01:
                signal = "SELL"
            else:
                signal = "FLAT"

            print(
                f"[VEL] {signal} | "
                f"Change={pct:.4f}% | "
                f"Vel={velocity:.4f}/s")

            return signal, pct

    except Exception as e:
        print(f"[VEL ERROR] {e}")
        return "FLAT", 0.0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  COMBINED SIGNAL
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def get_combined_signal(
        ob_signal,
        flow_signal,
        vel_signal):
    signals = [
        ob_signal,
        flow_signal,
        vel_signal]

    buy_count  = signals.count("BUY")
    sell_count = signals.count("SELL")

    if buy_count >= 2:
        return "BUY", buy_count
    elif sell_count >= 2:
        return "SELL", sell_count
    else:
        return "FLAT", 0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  TREND FILTER CHECK (NEW)
#  Signal aur Trend match karo
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def check_trend_filter(signal, trend):
    """
    Trend ke against trade nahi karo

    UP trend   → Sirf BUY allowed
    DOWN trend → Sirf SELL allowed
    FLAT trend → Koi trade nahi

    Return:
    True  = Trade allowed
    False = Trade block karo
    """
    if trend == "UP" and signal == "BUY":
        return True
    elif trend == "DOWN" and signal == "SELL":
        return True
    else:
        return False


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  PnL CALCULATOR
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def calc_pnl(side, entry, exit_p, pos_size):
    if side == "BUY":
        return (exit_p - entry) * pos_size
    else:
        return (entry - exit_p) * pos_size


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  PERIODIC UPDATE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def run_periodic_update():
    time.sleep(UPDATE_INTERVAL)
    while True:
        try:
            now = datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S")

            with state_lock:
                st = dict(state)

            pos      = st["position"]
            price    = st["last_price"]
            capital  = st["capital"]
            entry    = st["entry_price"]
            etime    = st["entry_time"]
            ob_sig   = st["ob_signal"]
            fl_sig   = st["flow_signal"]
            fees     = st["fees"]
            exposure = st["exposure"]
            trend    = st["trend"]

            daily = get_daily_stats()

            if (pos is not None and
                    etime is not None and
                    price > 0):

                gross_pnl = calc_pnl(
                    pos, entry, price,
                    st["pos_size"])
                net_pnl   = gross_pnl - fees
                dur = str(
                    datetime.now() -
                    etime).split(".")[0]
                icon = (
                    "🟢" if net_pnl >= 0
                    else "🔴")

                msg = (
                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"  ETH BOT UPDATE\n"
                    f"  {now}\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"{icon} {pos}\n"
                    f"Entry    : {entry:.4f}\n"
                    f"Price    : {price:.4f}\n"
                    f"Gross PnL: "
                    f"{gross_pnl:+.4f} USDT\n"
                    f"Fees     : "
                    f"-{fees:.4f} USDT\n"
                    f"Net PnL  : "
                    f"{net_pnl:+.4f} USDT\n"
                    f"Exposure : "
                    f"{exposure:.2f} USDT\n"
                    f"Trend    : {trend}\n"
                    f"OB       : {ob_sig}\n"
                    f"Flow     : {fl_sig}\n"
                    f"Capital  : "
                    f"{capital:.4f} USDT\n")
            else:
                msg = (
                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"  ETH BOT UPDATE\n"
                    f"  {now}\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"⏳ WAITING\n"
                    f"Price    : {price:.4f}\n"
                    f"Trend    : {trend}\n"
                    f"OB       : {ob_sig}\n"
                    f"Flow     : {fl_sig}\n"
                    f"Capital  : "
                    f"{capital:.4f} USDT\n")

            if daily:
                msg += (
                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"TODAY\n"
                    f"Trades   : "
                    f"{daily['total']}\n"
                    f"Wins     : "
                    f"{daily['wins']} ✅\n"
                    f"Losses   : "
                    f"{daily['losses']} ❌\n"
                    f"Win Rate : "
                    f"{daily['win_rate']}%\n"
                    f"Fees Paid: "
                    f"-{daily['total_fees']:.4f}\n"
                    f"Net PnL  : "
                    f"{daily['net_pnl']:+.4f} USDT\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━")

            send_telegram(msg)

        except Exception as e:
            print(f"[UPDATE ERROR] {e}")

        time.sleep(UPDATE_INTERVAL)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  DAILY REPORT
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def run_daily_report():
    while True:
        try:
            ist = timezone(
                timedelta(
                    hours=5, minutes=30))
            now = datetime.now(ist)

            if (now.hour == 23 and
                    now.minute == 59):
                daily = get_daily_stats()
                today = now.strftime(
                    "%d/%m/%Y")

                if daily:
                    msg = (
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"  DAILY REPORT\n"
                        f"  {today}\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"Symbol   : ETH/USDT\n"
                        f"Exchange : MEXC\n"
                        f"Trades   : "
                        f"{daily['total']}\n"
                        f"Wins     : "
                        f"{daily['wins']} ✅\n"
                        f"Losses   : "
                        f"{daily['losses']} ❌\n"
                        f"Win Rate : "
                        f"{daily['win_rate']}%\n"
                        f"Fees Paid: "
                        f"-{daily['total_fees']:.4f}"
                        f" USDT\n"
                        f"Net PnL  : "
                        f"{daily['net_pnl']:+.4f}"
                        f" USDT\n"
                        f"Best     : "
                        f"+{daily['best']:.4f}\n"
                        f"Worst    : "
                        f"{daily['worst']:.4f}\n"
                        f"Capital  : "
                        f"{daily['capital']:.4f}"
                        f" USDT\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━")
                else:
                    msg = (
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"  DAILY REPORT\n"
                        f"  {today}\n"
                        f"Aaj koi trade nahi hua\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━")

                send_telegram(msg)
                time.sleep(70)

        except Exception as e:
            print(f"[DAILY ERROR] {e}")

        time.sleep(30)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  MAIN TRADING ENGINE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def run_trading_engine():
    ex                 = get_exchange()
    capital            = load_capital()
    position           = None
    entry_price        = 0.0
    entry_time         = None
    pos_size           = 0.0
    sl_price           = 0.0
    tp_price           = 0.0
    capital_used       = 0.0
    exposure           = 0.0
    trade_fees         = 0.0
    cooldown_end       = load_cooldown()
    consecutive_losses = 0
    current_trend      = "FLAT"

    sample_exposure = (
        CAPITAL * CAPITAL_USE / 100 *
        LEVERAGE)
    sample_fees     = calc_fees(
        sample_exposure)
    sample_net_win  = calc_net_tp(
        sample_exposure)
    sample_net_loss = calc_net_sl(
        sample_exposure)

    print("[ENGINE] Started ✅")

    send_telegram(
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"  ETH HF BOT v3.0\n"
        f"  MEXC Exchange\n"
        f"  Trend Filter ON ✅\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Symbol   : ETH/USDT\n"
        f"Capital  : {CAPITAL:.2f} USDT\n"
        f"Use (90%): "
        f"{CAPITAL * CAPITAL_USE / 100:.2f}"
        f" USDT\n"
        f"Leverage : {LEVERAGE}x\n"
        f"Exposure : "
        f"{sample_exposure:.2f} USDT\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"TP       : {TP_PCT}%\n"
        f"SL       : {SL_PCT}%\n"
        f"Max Hold : {MAX_HOLD}s\n"
        f"Fee/Trade: "
        f"{sample_fees:.4f} USDT\n"
        f"Net Win  : "
        f"+{sample_net_win:.4f} USDT\n"
        f"Net Loss : "
        f"-{sample_net_loss:.4f} USDT\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Trend    : EMA{EMA_FAST}/"
        f"EMA{EMA_SLOW}\n"
        f"Strategy : OB+Flow+Vel+Trend\n"
        f"Scan     : Har {SCAN_INTERVAL}s\n"
        f"━━━━━━━━━━━━━━━━━━━━━━"
    )

    # Trend har 10 seconds mein update
    trend_counter = 0

    while True:
        try:
            now = datetime.now().strftime(
                "%H:%M:%S")

            # ── Price Fetch ───────────────
            cur_price = safe_fetch_ticker(ex)
            if cur_price is None:
                time.sleep(SCAN_INTERVAL)
                continue

            update_price_history(cur_price)

            # ── Trend Update ──────────────
            # Har 10 second mein trend check
            trend_counter += 1
            if trend_counter >= 10:
                trend_counter = 0
                current_trend, ema_f, ema_s = (
                    analyze_trend(ex))
                update_state(
                    trend=current_trend)

            # ── Analysis ──────────────────
            ob_signal, mid_price, spread, ob_ratio = (
                analyze_orderbook(ex))

            flow_signal, buy_vol, sell_vol = (
                analyze_trade_flow(ex))

            vel_signal, velocity = (
                analyze_velocity())

            # ── Combined Signal ───────────
            final_signal, strength = (
                get_combined_signal(
                    ob_signal,
                    flow_signal,
                    vel_signal))

            # ── Trend Filter Check ────────
            trend_allowed = check_trend_filter(
                final_signal, current_trend)

            # State update
            update_state(
                last_price=cur_price,
                capital=capital,
                position=position,
                entry_price=entry_price,
                entry_time=entry_time,
                sl_price=sl_price,
                tp_price=tp_price,
                pos_size=pos_size,
                capital_used=capital_used,
                exposure=exposure,
                fees=trade_fees,
                ob_signal=ob_signal,
                flow_signal=flow_signal,
                velocity=velocity,
                last_signal=final_signal,
                trend=current_trend,
            )

            # ══════════════════════════════
            #  POSITION MONITOR
            # ══════════════════════════════
            if position is not None:
                held = (
                    datetime.now() -
                    entry_time).seconds

                gross_pnl = calc_pnl(
                    position,
                    entry_price,
                    cur_price,
                    pos_size)

                net_pnl = gross_pnl - trade_fees

                icon = (
                    "🟢" if net_pnl >= 0
                    else "🔴")

                print(
                    f"[{now}] {icon} "
                    f"{position} | "
                    f"Net={net_pnl:+.4f} | "
                    f"Price={cur_price:.4f} | "
                    f"Held={held}s/{MAX_HOLD}s | "
                    f"Trend={current_trend}")

                hit_tp = (
                    (position == "BUY" and
                     cur_price >= tp_price) or
                    (position == "SELL" and
                     cur_price <= tp_price))

                hit_sl = (
                    (position == "BUY" and
                     cur_price <= sl_price) or
                    (position == "SELL" and
                     cur_price >= sl_price))

                hit_max = held >= MAX_HOLD

                if hit_tp or hit_sl or hit_max:
                    if hit_tp:
                        label = "TAKE PROFIT ✅"
                        icon  = "🟢"
                    elif hit_sl:
                        label = "STOP LOSS ❌"
                        icon  = "🔴"
                    else:
                        label = "MAX HOLD ⏰"
                        icon  = (
                            "🟢"
                            if net_pnl >= 0
                            else "🔴")

                    final_gross = calc_pnl(
                        position,
                        entry_price,
                        cur_price,
                        pos_size)
                    final_net = (
                        final_gross - trade_fees)

                    capital += final_net
                    duration = f"{held}s"

                    if final_net > 0:
                        consecutive_losses = 0
                        cd = COOLDOWN_WIN
                    else:
                        consecutive_losses += 1
                        cd = (
                            COOLDOWN_2LOSS
                            if consecutive_losses >= 2
                            else COOLDOWN_LOSS)

                    save_capital(capital)
                    save_trade(
                        position,
                        entry_price,
                        cur_price,
                        final_gross,
                        trade_fees,
                        capital,
                        duration,
                        label,
                        current_trend)

                    print(
                        f"[CLOSED] {label} | "
                        f"Gross="
                        f"{final_gross:+.4f} | "
                        f"Fees="
                        f"-{trade_fees:.4f} | "
                        f"Net={final_net:+.4f} | "
                        f"Cap={capital:.4f}")

                    send_telegram(
                        f"{icon} {label}\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"Symbol   : ETH\n"
                        f"Exchange : MEXC\n"
                        f"Side     : {position}\n"
                        f"Entry    : "
                        f"{entry_price:.4f}\n"
                        f"Exit     : "
                        f"{cur_price:.4f}\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"Gross PnL: "
                        f"{final_gross:+.4f} USDT\n"
                        f"Fees     : "
                        f"-{trade_fees:.4f} USDT\n"
                        f"Net PnL  : "
                        f"{final_net:+.4f} USDT\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"Capital  : "
                        f"{capital:.4f} USDT\n"
                        f"Duration : {duration}\n"
                        f"Trend    : "
                        f"{current_trend}\n"
                        f"OB       : {ob_signal}\n"
                        f"Flow     : "
                        f"{flow_signal}\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━"
                    )

                    position     = None
                    entry_price  = 0.0
                    entry_time   = None
                    pos_size     = 0.0
                    sl_price     = 0.0
                    tp_price     = 0.0
                    capital_used = 0.0
                    exposure     = 0.0
                    trade_fees   = 0.0
                    cooldown_end = (
                        time.time() + cd)
                    save_cooldown(cooldown_end)
                    update_state(
                        position=None,
                        capital_used=0.0,
                        exposure=0.0,
                        fees=0.0,
                        capital=capital)

                    time.sleep(SCAN_INTERVAL)
                    continue

            # ══════════════════════════════
            #  COOLDOWN
            # ══════════════════════════════
            if (cooldown_end is not None and
                    time.time() < cooldown_end):
                remaining = int(
                    cooldown_end - time.time())
                print(
                    f"[{now}] "
                    f"Cooldown {remaining}s...")
                time.sleep(SCAN_INTERVAL)
                continue

            # ══════════════════════════════
            #  ENTRY
            # ══════════════════════════════
            if position is None:
                if final_signal in [
                        "BUY", "SELL"]:

                    # ── Trend Filter ──────
                    if not trend_allowed:
                        print(
                            f"[{now}] "
                            f"TREND BLOCK | "
                            f"Signal={final_signal}"
                            f" | Trend="
                            f"{current_trend} ❌")
                        time.sleep(SCAN_INTERVAL)
                        continue

                    # ── Spread Check ──────
                    if spread > MAX_SPREAD:
                        print(
                            f"[SKIP] "
                            f"Spread "
                            f"{spread:.4f}%")
                        time.sleep(SCAN_INTERVAL)
                        continue

                    capital_used = (
                        capital *
                        CAPITAL_USE / 100)
                    exposure = (
                        capital_used * LEVERAGE)
                    pos_size = (
                        exposure / cur_price)
                    trade_fees = calc_fees(
                        exposure)

                    entry_price  = cur_price
                    entry_time   = datetime.now()
                    position     = final_signal
                    cooldown_end = None

                    exp_net_win  = calc_net_tp(
                        exposure)
                    exp_net_loss = calc_net_sl(
                        exposure)

                    if final_signal == "BUY":
                        tp_price = (
                            entry_price *
                            (1 + TP_PCT / 100))
                        sl_price = (
                            entry_price *
                            (1 - SL_PCT / 100))
                    else:
                        tp_price = (
                            entry_price *
                            (1 - TP_PCT / 100))
                        sl_price = (
                            entry_price *
                            (1 + SL_PCT / 100))

                    print(
                        f"[OPENED] {position} | "
                        f"Entry="
                        f"{entry_price:.4f} | "
                        f"TP={tp_price:.4f} | "
                        f"SL={sl_price:.4f} | "
                        f"Trend={current_trend} | "
                        f"Strength={strength}/3")

                    send_telegram(
                        f"🚀 ENTRY\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"Symbol   : ETH\n"
                        f"Exchange : MEXC\n"
                        f"Side     : {position}\n"
                        f"Entry    : "
                        f"{entry_price:.4f}\n"
                        f"TP       : "
                        f"{tp_price:.4f}\n"
                        f"SL       : "
                        f"{sl_price:.4f}\n"
                        f"Max Hold : {MAX_HOLD}s\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"Capital  : "
                        f"{capital_used:.2f} USDT\n"
                        f"Leverage : {LEVERAGE}x\n"
                        f"Exposure : "
                        f"{exposure:.2f} USDT\n"
                        f"Fees     : "
                        f"-{trade_fees:.4f} USDT\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"Exp Win  : "
                        f"+{exp_net_win:.4f} USDT\n"
                        f"Exp Loss : "
                        f"-{exp_net_loss:.4f} USDT\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"Trend    : "
                        f"{current_trend} ✅\n"
                        f"OB       : {ob_signal}\n"
                        f"Flow     : "
                        f"{flow_signal}\n"
                        f"Velocity : {vel_signal}\n"
                        f"Strength : "
                        f"{strength}/3\n"
                        f"OB Ratio : "
                        f"{ob_ratio:.2f}\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━"
                    )

                else:
                    print(
                        f"[{now}] FLAT | "
                        f"OB={ob_signal} | "
                        f"Flow={flow_signal} | "
                        f"Vel={vel_signal} | "
                        f"Trend={current_trend} | "
                        f"Price={cur_price:.4f}")

        except Exception as e:
            err = str(e)
            print(f"[ENGINE ERROR] {err}")
            if "429" in err:
                time.sleep(30)
            elif ("connection" in err.lower() or
                  "timeout" in err.lower()):
                ex = get_exchange()
                time.sleep(10)
            else:
                time.sleep(5)

        time.sleep(SCAN_INTERVAL)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  START
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

if __name__ == "__main__":

    cap_use        = CAPITAL * CAPITAL_USE / 100
    exposure       = cap_use * LEVERAGE
    fees_per_trade = calc_fees(exposure)
    net_win        = calc_net_tp(exposure)
    net_loss       = calc_net_sl(exposure)

    print("=" * 50)
    print("  ETH HF SCALPING BOT v3.0")
    print("  MEXC — Zero Maker Fee")
    print("  Trend Filter: EMA9/EMA21")
    print("=" * 50)
    print(f"  Symbol    : ETH/USDT")
    print(f"  Exchange  : MEXC")
    print(f"  Capital   : {CAPITAL} USDT")
    print(f"  Use (90%) : {cap_use} USDT")
    print(f"  Leverage  : {LEVERAGE}x")
    print(f"  Exposure  : {exposure} USDT")
    print(f"  TP        : {TP_PCT}%")
    print(f"  SL        : {SL_PCT}%")
    print(f"  Max Hold  : {MAX_HOLD}s")
    print(f"  Taker Fee : {TAKER_FEE}%")
    print(f"  Fee/Trade : {fees_per_trade} USDT")
    print(f"  Net Win   : +{net_win} USDT")
    print(f"  Net Loss  : -{net_loss} USDT")
    print(f"  Scan      : Har {SCAN_INTERVAL}s")
    print(f"  Trend     : EMA{EMA_FAST}/"
          f"EMA{EMA_SLOW} ON ✅")
    print("=" * 50)
    print(f"  RR Ratio  : "
          f"1:{round(net_win/net_loss, 2)}")
    print(f"  Min WR Req: "
          f"{round(net_loss/(net_win+net_loss)*100, 1)}%")
    print("=" * 50)

    threads = [
        threading.Thread(
            target=run_server,
            name="Flask",
            daemon=True),
        threading.Thread(
            target=run_periodic_update,
            name="Update",
            daemon=True),
        threading.Thread(
            target=run_daily_report,
            name="Daily",
            daemon=True),
        threading.Thread(
            target=run_trading_engine,
            name="Engine",
            daemon=True),
    ]

    for t in threads:
        t.start()
        time.sleep(0.5)

    print(f"\n[INFO] Threads: {len(threads)}")
    print("[INFO] Bot Running 24/7 ✅")
    print("=" * 50)

    while True:
        time.sleep(60)
