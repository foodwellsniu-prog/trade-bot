"""
SCALPING BOT v4.0 — Multi-Symbol Ultimate SMC Edition
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Strategy  : Smart Money Concepts (SMC)
            BOS + CHOCH + OB + LIQ + FVG + RSI + MA
Symbols   : BTC/USDT, ETH/USDT, SOL/USDT, BNB/USDT
Timeframes: 15m (Trend) + 5m (Confirm) + 1m (Entry)
Sessions  : 24/7 with Session Filter
Min Score : 8/12
Capital   : Total / 4 Symbols = Per Symbol
Trade Use : 90% of Per Symbol Capital
Leverage  : 5x (All Symbols)
TP Zone   : 70-90% Early Exit
Max Hold  : 3 min base + Smart Extension
Dynamic RR: Score Based (1:2 to 1:4)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import threading
import time
import queue
from flask import Flask
from queue import Queue

app = Flask(__name__)

@app.route('/')
def home():
    return "Scalping Bot v4.0 Multi-Symbol Ultimate SMC Running!"

def run_server():
    import os
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)


import ccxt
import pandas as pd
import numpy as np
import json
import requests
from datetime import datetime, timezone, timedelta


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  CONFIG — MULTI SYMBOL
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SYMBOLS = [
    "BTC/USDT:USDT",
    "ETH/USDT:USDT",
    "SOL/USDT:USDT",
    "BNB/USDT:USDT",
]

API_KEY          = ""
API_SECRET       = ""

BOT_TOKEN        = "8161773850:AAFcWw3UnlSe2TrMooB2uvgZQZUqIW0zW2w"
CHAT_ID          = "7102976298"

# ── Capital Config ────────────────────────────────────
TOTAL_CAPITAL    = 420
NUM_SYMBOLS      = len(SYMBOLS)
CAPITAL_PER_SYM  = TOTAL_CAPITAL / NUM_SYMBOLS   # 105 per symbol
CAPITAL_USE_PCT  = 90                             # 90% per trade
LEVERAGE         = 10                            # 10x all symbols

# ── Score Config ──────────────────────────────────────
MIN_SCORE        = 8
MIN_CONFIDENCE   = int((MIN_SCORE / 12) * 100)

# ── Timing Config ─────────────────────────────────────
EXECUTE_SCAN     = 8
DECISION_SCAN    = 60
COOLDOWN         = 60
COOLDOWN_WIN     = 30
COOLDOWN_LOSS    = 90
COOLDOWN_2LOSS   = 180

# ── Max Hold Config ───────────────────────────────────
MAX_HOLD_SECONDS   = 180
MAX_HOLD_EXTENSION = 140
HOLD_SCORE_MINIMUM = 7
MAX_EXTENSIONS     = 3

# ── ATR Config ────────────────────────────────────────
ATR_PERIOD       = 7

# ── ATR Range Per Symbol ──────────────────────────────
ATR_RANGES = {
    "BTC/USDT:USDT": {"min": 20.0,  "max": 500.0},
    "ETH/USDT:USDT": {"min": 5.0,   "max": 50.0},
    "SOL/USDT:USDT": {"min": 0.3,   "max": 10.0},
    "BNB/USDT:USDT": {"min": 0.5,   "max": 15.0},
}

# ── Dynamic RR — Score Based ──────────────────────────
RR_CONFIG = {
    8:  {"sl_mult": 1.0, "tp_mult": 2.0},
    9:  {"sl_mult": 0.9, "tp_mult": 2.5},
    10: {"sl_mult": 0.8, "tp_mult": 3.0},
    11: {"sl_mult": 0.7, "tp_mult": 3.5},
    12: {"sl_mult": 0.6, "tp_mult": 4.0},
}
RR_DEFAULT_SL    = 1.0
RR_DEFAULT_TP    = 2.0
MIN_RR           = 2.0

# ── TP Early Exit ─────────────────────────────────────
TP_EXIT_MIN_PCT  = 0.70
TP_EXIT_MAX_PCT  = 0.90
TP_HOLD_MIN_SCORE = 9

# ── Trailing SL ───────────────────────────────────────
TRAIL_TRIGGER_PCT  = 1.0
TRAIL_DISTANCE_PCT = 0.5

# ── Break Even SL ─────────────────────────────────────
BREAK_EVEN_TRIGGER = 0.5

# ── Volume Config ─────────────────────────────────────
VOLUME_MULT      = 1.5

# ── Spread Config ─────────────────────────────────────
MAX_SPREAD_PCT   = 0.05

# ── Update Config ─────────────────────────────────────
UPDATE_INTERVAL  = 1800


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  FILE NAMES — Per Symbol
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def get_files(symbol):
    """
    Har symbol ke liye alag file names generate karta hai
    Example: ETH/USDT:USDT → ETH_USDT_USDT
    """
    name = symbol.replace(
        "/", "_").replace(":", "_")
    return {
        "capital":  f"capital_{name}.txt",
        "cooldown": f"cooldown_{name}.txt",
        "history":  f"history_{name}.json",
        "log":      f"log_{name}.json",
        "output":   f"output_{name}.txt",
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  SIGNAL QUEUES — Per Symbol
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

signal_queues = {
    sym: Queue(maxsize=1)
    for sym in SYMBOLS
}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  STATE LOCK
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

state_lock = threading.Lock()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  PRICE CACHE — Per Symbol
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

price_caches = {
    sym: {
        "price": 0.0,
        "time":  0.0,
        "lock":  threading.Lock()
    }
    for sym in SYMBOLS
}


def get_cached_price(ex, symbol, max_age=5):
    """
    Cache se price return karta hai
    max_age seconds ke baad fresh fetch karta hai
    """
    cache = price_caches[symbol]
    with cache["lock"]:
        if time.time() - cache["time"] < max_age:
            return cache["price"]
    price = safe_fetch_ticker(ex, symbol)
    if price:
        with cache["lock"]:
            cache["price"] = price
            cache["time"]  = time.time()
    return price


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  TRADE STATE — Per Symbol
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def make_trade_state(capital):
    """
    Har symbol ke liye fresh trade state banata hai
    """
    return {
        "position":        None,
        "entry_price":     0.0,
        "entry_time":      None,
        "sl_price":        0.0,
        "tp_price":        0.0,
        "pos_size":        0.0,
        "capital_used":    0.0,
        "capital":         capital,
        "last_signal":     "WAIT",
        "last_conf":       0,
        "last_price":      0.0,
        "last_points":     0,
        "last_tp_zone":    "",
        "last_session":    "",
        "extension_count": 0,
        "struct_15m":      "RANGE",
        "struct_5m":       "RANGE",
        "struct_1m":       "RANGE",
        "atr_15m":         0.0,
        "rr_type":         "Default",
    }


trade_states = {
    sym: make_trade_state(CAPITAL_PER_SYM)
    for sym in SYMBOLS
}


def update_state(symbol, **kwargs):
    """
    Thread-safe state update karta hai
    """
    with state_lock:
        for key, val in kwargs.items():
            if key in trade_states[symbol]:
                trade_states[symbol][key] = val


def get_state(symbol, key):
    """
    Thread-safe state read karta hai
    """
    with state_lock:
        return trade_states[symbol].get(key)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  CAPITAL — Per Symbol
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def load_capital(symbol):
    """
    Symbol ka capital file se load karta hai
    File nahi mili toh CAPITAL_PER_SYM use karta hai
    """
    files = get_files(symbol)
    try:
        with open(files["capital"], "r") as f:
            cap = float(f.read().strip())
            print(
                f"[{symbol}][CAPITAL] "
                f"Loaded: {cap} USDT")
            return cap
    except Exception:
        import os
        env_key = (
            f"CAPITAL_"
            f"{symbol.replace('/', '_').replace(':', '_')}")
        env_cap = os.environ.get(env_key)
        if env_cap:
            cap = float(env_cap)
            print(
                f"[{symbol}][CAPITAL] "
                f"Env: {cap} USDT")
        else:
            cap = CAPITAL_PER_SYM
            print(
                f"[{symbol}][CAPITAL] "
                f"Default: {cap} USDT")
        save_capital(symbol, cap)
        return cap


def save_capital(symbol, capital):
    """
    Symbol ka capital file mein save karta hai
    """
    files = get_files(symbol)
    try:
        with open(files["capital"], "w") as f:
            f.write(str(round(capital, 6)))
    except Exception as e:
        print(
            f"[{symbol}][CAPITAL ERROR] {e}")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  COOLDOWN — Per Symbol
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def save_cooldown(symbol, end_time):
    """
    Cooldown end time file mein save karta hai
    """
    files = get_files(symbol)
    try:
        with open(files["cooldown"], "w") as f:
            f.write(str(end_time))
    except Exception as e:
        print(
            f"[{symbol}][COOLDOWN SAVE ERROR] {e}")


def load_cooldown(symbol):
    """
    Cooldown file se load karta hai
    Agar abhi bhi active hai toh return karta hai
    """
    files = get_files(symbol)
    try:
        with open(files["cooldown"], "r") as f:
            val = float(f.read().strip())
            if val > time.time():
                remaining = int(val - time.time())
                print(
                    f"[{symbol}][COOLDOWN] "
                    f"Remaining: {remaining}s")
                return val
    except Exception:
        pass
    return None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  TRADE HISTORY — Per Symbol
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def save_trade_history(symbol, side, entry,
                       exit_price, pnl,
                       capital, duration, label):
    """
    Trade ko history file mein save karta hai
    """
    files = get_files(symbol)
    try:
        try:
            with open(
                    files["history"], "r",
                    encoding="utf-8") as f:
                history = json.load(f)
        except Exception:
            history = []

        history.append({
            "date":     datetime.now().strftime(
                "%d/%m/%Y"),
            "time":     datetime.now().strftime(
                "%H:%M:%S"),
            "symbol":   symbol,
            "side":     side,
            "entry":    round(entry, 4),
            "exit":     round(exit_price, 4),
            "pnl":      round(pnl, 4),
            "capital":  round(capital, 4),
            "duration": duration,
            "result":   "WIN" if pnl > 0 else "LOSS",
            "label":    label,
        })

        with open(
                files["history"], "w",
                encoding="utf-8") as f:
            json.dump(history, f, indent=2)

    except Exception as e:
        print(
            f"[{symbol}][HISTORY ERROR] {e}")


def get_daily_stats(symbol):
    """
    Aaj ke trades ki stats return karta hai
    """
    files = get_files(symbol)
    try:
        with open(
                files["history"], "r",
                encoding="utf-8") as f:
            history = json.load(f)
    except Exception:
        return None

    today  = datetime.now().strftime("%d/%m/%Y")
    trades = [
        t for t in history
        if t["date"] == today]

    if not trades:
        return None

    total     = len(trades)
    wins      = len([
        t for t in trades
        if t["result"] == "WIN"])
    losses    = total - wins
    win_rate  = round((wins / total) * 100, 1)
    daily_pnl = round(
        sum(t["pnl"] for t in trades), 4)
    best      = round(
        max(t["pnl"] for t in trades), 4)
    worst     = round(
        min(t["pnl"] for t in trades), 4)

    return {
        "total":   total,
        "wins":    wins,
        "losses":  losses,
        "win_rate": win_rate,
        "pnl":     daily_pnl,
        "best":    best,
        "worst":   worst,
        "capital": trades[-1]["capital"],
    }


def get_overall_stats(symbol):
    """
    Sab trades ki overall stats return karta hai
    """
    files = get_files(symbol)
    try:
        with open(
                files["history"], "r",
                encoding="utf-8") as f:
            history = json.load(f)
    except Exception:
        return None

    if not history:
        return None

    total     = len(history)
    wins      = len([
        t for t in history
        if t["result"] == "WIN"])
    losses    = total - wins
    win_rate  = round((wins / total) * 100, 1)
    total_pnl = round(
        sum(t["pnl"] for t in history), 4)

    return {
        "total":    total,
        "wins":     wins,
        "losses":   losses,
        "win_rate": win_rate,
        "pnl":      total_pnl,
        "best":     round(
            max(t["pnl"] for t in history), 4),
        "worst":    round(
            min(t["pnl"] for t in history), 4),
        "capital":  history[-1]["capital"],
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  EXCHANGE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def get_exchange():
    """
    Binance futures exchange connect karta hai
    Fail hone par 30s baad retry karta hai
    """
    while True:
        try:
            ex = ccxt.binanceusdm({
                "apiKey":          API_KEY,
                "secret":          API_SECRET,
                "enableRateLimit": True,
                "rateLimit":       100,
            })
            ex.load_markets()
            print("[INFO] Binance connected ✅")
            return ex
        except Exception as e:
            print(
                f"[RECONNECT] Fail: {e}\n"
                f"[RECONNECT] 30s retry...")
            time.sleep(30)


def safe_fetch_ticker(ex, symbol, retries=3):
    """
    Symbol ka last price fetch karta hai
    Rate limit aane par wait karta hai
    """
    for i in range(retries):
        try:
            ticker = ex.fetch_ticker(symbol)
            return float(ticker["last"])
        except Exception as e:
            if ("429" in str(e) or
                    "Too Many" in str(e)):
                wait = (i + 1) * 30
                print(
                    f"[RATE LIMIT] "
                    f"Ticker {wait}s wait...")
                time.sleep(wait)
            else:
                print(
                    f"[TICKER ERROR] "
                    f"{symbol}: {e}")
                time.sleep(5)
    return None


def safe_fetch_ohlcv(ex, symbol, tf,
                     limit, retries=3):
    """
    OHLCV candles fetch karta hai
    Rate limit aane par wait karta hai
    """
    for i in range(retries):
        try:
            bars = ex.fetch_ohlcv(
                symbol,
                timeframe=tf,
                limit=limit)
            return bars
        except Exception as e:
            if ("429" in str(e) or
                    "Too Many" in str(e)):
                wait = (i + 1) * 30
                print(
                    f"[RATE LIMIT] "
                    f"{symbol} {tf} {wait}s...")
                time.sleep(wait)
            else:
                print(
                    f"[OHLCV ERROR] "
                    f"{symbol} {tf}: {e}")
                time.sleep(5)
    return None


def safe_fetch_orderbook(ex, symbol, retries=3):
    """
    Order book fetch karta hai spread check ke liye
    """
    for i in range(retries):
        try:
            ob = ex.fetch_order_book(
                symbol, limit=5)
            return ob
        except Exception as e:
            if ("429" in str(e) or
                    "Too Many" in str(e)):
                wait = (i + 1) * 30
                print(
                    f"[RATE LIMIT] "
                    f"OB {symbol} {wait}s...")
                time.sleep(wait)
            else:
                print(
                    f"[OB ERROR] "
                    f"{symbol}: {e}")
                time.sleep(5)
    return None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  TELEGRAM
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def send_telegram(message):
    """
    Telegram par message bhejta hai
    3 baar retry karta hai fail hone par
    """
    url = (
        f"https://api.telegram.org/bot"
        f"{BOT_TOKEN}/sendMessage")
    for attempt in range(3):
        try:
            r = requests.post(
                url,
                data={
                    "chat_id": CHAT_ID,
                    "text":    f"[SCALP] {message}",
                },
                timeout=15,
            )
            if r.status_code == 200:
                return
        except Exception as e:
            print(
                f"[TELEGRAM] "
                f"{attempt+1}/3: {e}")
            time.sleep(3)
    print("[TELEGRAM] Failed after 3 attempts")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  SPREAD CHECK
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def check_spread(ex, symbol):
    """
    Bid-Ask spread check karta hai
    Zyada spread = Skip trade
    """
    try:
        ob = safe_fetch_orderbook(ex, symbol)
        if ob is None:
            return True
        bid        = ob["bids"][0][0]
        ask        = ob["asks"][0][0]
        spread_pct = ((ask - bid) / bid) * 100
        if spread_pct > MAX_SPREAD_PCT:
            print(
                f"[{symbol}][SPREAD] "
                f"High: {spread_pct:.4f}% ❌")
            return False
        print(
            f"[{symbol}][SPREAD] "
            f"OK: {spread_pct:.4f}% ✅")
        return True
    except Exception as e:
        print(
            f"[{symbol}][SPREAD ERROR] {e}")
        return True


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  VOLUME CHECK
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def check_volume(df, symbol, mult=VOLUME_MULT):
    """
    Current volume ko 20 candle average se compare karta hai
    1.5x se zyada = Strong volume
    """
    try:
        avg_vol  = df["volume"].tail(20).mean()
        last_vol = df["volume"].iloc[-1]
        if avg_vol == 0:
            return True
        ratio = last_vol / avg_vol
        ok    = ratio >= mult
        print(
            f"[{symbol}][VOLUME] "
            f"{ratio:.2f}x | "
            f"{'OK ✅' if ok else 'WEAK ❌'}")
        return ok
    except Exception as e:
        print(
            f"[{symbol}][VOLUME ERROR] {e}")
        return True


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  ATR RANGE CHECK — Symbol Specific
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def check_atr_range(symbol, atr_val):
    """
    ATR value ko symbol ke range se compare karta hai
    BTC ka range ETH se alag hota hai
    """
    ranges = ATR_RANGES.get(symbol, {
        "min": 0.5,
        "max": 500.0
    })
    if atr_val < ranges["min"]:
        print(
            f"[{symbol}][ATR] "
            f"Too Low: {atr_val:.4f} "
            f"< {ranges['min']} ❌")
        return False
    if atr_val > ranges["max"]:
        print(
            f"[{symbol}][ATR] "
            f"Too High: {atr_val:.4f} "
            f"> {ranges['max']} ❌")
        return False
    print(
        f"[{symbol}][ATR] "
        f"OK: {atr_val:.4f} ✅")
    return True


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  SESSION FILTER
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def is_good_session():
    """
    Trading session check karta hai
    London + NY = Best sessions
    Asian = Sirf high score pe trade
    """
    hour    = datetime.utcnow().hour
    london  = 7 <= hour < 16
    newyork = 12 <= hour < 21
    overlap = 12 <= hour < 16

    if overlap:
        session = "London-NY Overlap 🔥 (Best)"
    elif london:
        session = "London Session ✅"
    elif newyork:
        session = "New York Session ✅"
    else:
        session = "Asian Session ⚠️ (Weak)"

    is_good = london or newyork
    print(
        f"[SESSION] {session} | "
        f"Good: {is_good}")
    return is_good, session


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  ATR CALCULATOR
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def calc_atr(df, period=7):
    """
    Average True Range calculate karta hai
    SL aur TP distance ke liye use hota hai
    """
    try:
        high  = df["high"]
        low   = df["low"]
        close = df["close"]
        tr1   = high - low
        tr2   = (high - close.shift(1)).abs()
        tr3   = (low  - close.shift(1)).abs()
        tr    = pd.concat(
            [tr1, tr2, tr3],
            axis=1).max(axis=1)
        return float(
            tr.ewm(
                span=period,
                adjust=False
            ).mean().iloc[-1])
    except Exception:
        return 0.0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  RSI CALCULATOR
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def calc_rsi(df, period=14):
    """
    Relative Strength Index calculate karta hai
    1m timeframe pe use hota hai entry ke liye
    """
    try:
        close = df["close"]
        delta = close.diff()
        gain  = delta.where(delta > 0, 0)
        loss  = -delta.where(delta < 0, 0)
        avg_g = gain.ewm(
            span=period,
            adjust=False).mean()
        avg_l = loss.ewm(
            span=period,
            adjust=False).mean()
        rs    = avg_g / avg_l
        rsi   = 100 - (100 / (1 + rs))
        val   = float(rsi.iloc[-1])
        print(f"[RSI-1m] Value={val:.2f}")
        return val
    except Exception as e:
        print(f"[RSI ERROR] {e}")
        return 50.0


def check_rsi(rsi_val, direction):
    """
    RSI value ko direction ke saath compare karta hai
    BUY ke liye <= 45, SELL ke liye >= 55
    """
    if direction == "BUY":
        if rsi_val <= 45:
            return True, f"RSI {rsi_val:.1f} BUY ✅"
        return False, f"RSI {rsi_val:.1f} not BUY"
    else:
        if rsi_val >= 55:
            return True, f"RSI {rsi_val:.1f} SELL ✅"
        return False, f"RSI {rsi_val:.1f} not SELL"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  MOVING AVERAGE — 15m Timeframe
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def check_moving_average(df, direction):
    """
    EMA 20 aur EMA 50 check karta hai
    15m timeframe pe use hota hai trend ke liye
    """
    try:
        close = df["close"]
        ema20 = float(
            close.ewm(
                span=20,
                adjust=False
            ).mean().iloc[-1])
        ema50 = float(
            close.ewm(
                span=50,
                adjust=False
            ).mean().iloc[-1])
        price = float(close.iloc[-1])

        if direction == "BUY":
            if price > ema20 and ema20 > ema50:
                status = "STRONG_BULL"
                ok     = True
            elif price > ema20:
                status = "WEAK_BULL"
                ok     = True
            else:
                status = "BEARISH"
                ok     = False
        else:
            if price < ema20 and ema20 < ema50:
                status = "STRONG_BEAR"
                ok     = True
            elif price < ema20:
                status = "WEAK_BEAR"
                ok     = True
            else:
                status = "BULLISH"
                ok     = False

        print(
            f"[MA-15m] EMA20={ema20:.4f} | "
            f"EMA50={ema50:.4f} | "
            f"Price={price:.4f} | "
            f"{status}")
        return ok, status, ema20, ema50

    except Exception as e:
        print(f"[MA ERROR] {e}")
        return True, "ERROR", 0.0, 0.0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  BOS / CHOCH DETECTOR
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def detect_bos_choch(df, swing_bars=2):
    """
    Break of Structure aur Change of Character detect karta hai
    15m aur 5m dono timeframes pe use hota hai
    """
    try:
        highs  = df["high"].values
        lows   = df["low"].values
        closes = df["close"].values
        n      = len(highs)

        swing_highs = []
        swing_lows  = []

        for i in range(swing_bars, n - swing_bars):
            if highs[i] == max(
                    highs[i - swing_bars:
                           i + swing_bars + 1]):
                swing_highs.append(
                    (i, highs[i]))
            if lows[i] == min(
                    lows[i - swing_bars:
                          i + swing_bars + 1]):
                swing_lows.append(
                    (i, lows[i]))

        if (len(swing_highs) < 2 or
                len(swing_lows) < 2):
            return {
                "bos_bull":   False,
                "bos_bear":   False,
                "choch_bull": False,
                "choch_bear": False,
                "last_sh":    0.0,
                "last_sl":    0.0,
                "type":       "NONE",
            }

        last_price = closes[-1]
        last_sh    = swing_highs[-1][1]
        last_sl    = swing_lows[-1][1]
        prev_sh    = swing_highs[-2][1]
        prev_sl    = swing_lows[-2][1]

        bos_bull   = last_price > last_sh
        bos_bear   = last_price < last_sl
        choch_bull = (
            last_sh < prev_sh and
            last_price > last_sh)
        choch_bear = (
            last_sl > prev_sl and
            last_price < last_sl)

        if choch_bull:
            result = "CHOCH_BULL"
        elif choch_bear:
            result = "CHOCH_BEAR"
        elif bos_bull:
            result = "BOS_BULL"
        elif bos_bear:
            result = "BOS_BEAR"
        else:
            result = "NONE"

        print(
            f"[BOS/CHOCH] {result} | "
            f"SH={last_sh:.4f} | "
            f"SL={last_sl:.4f}")

        return {
            "bos_bull":   bos_bull,
            "bos_bear":   bos_bear,
            "choch_bull": choch_bull,
            "choch_bear": choch_bear,
            "last_sh":    last_sh,
            "last_sl":    last_sl,
            "type":       result,
        }

    except Exception as e:
        print(f"[BOS/CHOCH ERROR] {e}")
        return {
            "bos_bull":   False,
            "bos_bear":   False,
            "choch_bull": False,
            "choch_bear": False,
            "last_sh":    0.0,
            "last_sl":    0.0,
            "type":       "NONE",
        }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  EQUAL HIGHS / EQUAL LOWS — 1m Timeframe
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def detect_equal_levels(df, tolerance=0.002):
    """
    Equal Highs aur Equal Lows detect karta hai
    Liquidity pools identify karne ke liye
    1m timeframe pe use hota hai
    """
    try:
        highs         = df["high"].tail(50).values
        lows          = df["low"].tail(50).values
        current_price = float(df["close"].iloc[-1])
        n             = len(highs)
        equal_highs   = []
        equal_lows    = []

        for i in range(n):
            for j in range(i + 1, n):
                diff_h = abs(highs[i] - highs[j])
                avg_h  = (highs[i] + highs[j]) / 2
                if (avg_h > 0 and
                        diff_h / avg_h <= tolerance):
                    equal_highs.append(
                        round(avg_h, 4))

                diff_l = abs(lows[i] - lows[j])
                avg_l  = (lows[i] + lows[j]) / 2
                if (avg_l > 0 and
                        diff_l / avg_l <= tolerance):
                    equal_lows.append(
                        round(avg_l, 4))

        near_eq_high = any(
            abs(current_price - h) /
            current_price <= 0.003
            for h in equal_highs
        ) if equal_highs else False

        near_eq_low = any(
            abs(current_price - l) /
            current_price <= 0.003
            for l in equal_lows
        ) if equal_lows else False

        print(
            f"[EQ LEVELS-1m] "
            f"EqH={len(equal_highs)} | "
            f"EqL={len(equal_lows)} | "
            f"NearH={near_eq_high} | "
            f"NearL={near_eq_low}")

        return {
            "equal_highs":  list(
                set(equal_highs))[-3:],
            "equal_lows":   list(
                set(equal_lows))[-3:],
            "near_eq_high": near_eq_high,
            "near_eq_low":  near_eq_low,
        }

    except Exception as e:
        print(f"[EQ LEVELS ERROR] {e}")
        return {
            "equal_highs":  [],
            "equal_lows":   [],
            "near_eq_high": False,
            "near_eq_low":  False,
        }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  MARKET STRUCTURE DETECTOR
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def detect_structure(df, swing_bars=2):
    """
    Market structure detect karta hai
    15m = Main Trend
    5m  = Confirmation
    1m  = Entry Structure
    HH+HL = BULL | LH+LL = BEAR | else = RANGE
    """
    try:
        highs = df["high"].values
        lows  = df["low"].values
        n     = len(highs)
        swing_highs = []
        swing_lows  = []

        for i in range(swing_bars, n - swing_bars):
            if highs[i] == max(
                    highs[i - swing_bars:
                           i + swing_bars + 1]):
                swing_highs.append(highs[i])
            if lows[i] == min(
                    lows[i - swing_bars:
                          i + swing_bars + 1]):
                swing_lows.append(lows[i])

        if (len(swing_highs) < 2 or
                len(swing_lows) < 2):
            return "RANGE"

        hh = swing_highs[-1] > swing_highs[-2]
        hl = swing_lows[-1]  > swing_lows[-2]
        lh = swing_highs[-1] < swing_highs[-2]
        ll = swing_lows[-1]  < swing_lows[-2]

        if hh and hl:
            return "BULL"
        elif lh and ll:
            return "BEAR"
        return "RANGE"

    except Exception:
        return "RANGE"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  ORDER BLOCKS — 5m Timeframe
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def detect_order_blocks(df, lookback=40):
    """
    Order Blocks detect karta hai
    Smart Money ke entry zones hote hain
    5m timeframe pe use hota hai
    """
    try:
        recent        = df.tail(
            lookback).reset_index(drop=True)
        n             = len(recent)
        current_price = recent["close"].iloc[-1]
        bullish_obs   = []
        bearish_obs   = []

        for i in range(1, n - 1):
            curr      = recent.iloc[i]
            next_     = recent.iloc[i + 1]
            curr_body = abs(
                curr["close"] - curr["open"])
            next_body = abs(
                next_["close"] - next_["open"])
            if curr_body == 0:
                continue

            if (curr["close"] > curr["open"] and
                    next_["close"] < next_["open"]
                    and next_body > curr_body * 1.2):
                ob_top    = curr["high"]
                ob_bottom = curr["open"]
                tolerance = (
                    ob_top - ob_bottom) * 0.3
                in_zone   = (
                    ob_bottom - tolerance
                    <= current_price
                    <= ob_top + tolerance)
                bearish_obs.append({
                    "top":         round(ob_top, 4),
                    "bottom":      round(ob_bottom, 4),
                    "price_in_ob": in_zone,
                    "fresh":       (i >= n - 10),
                    "idx":         i,
                })

            if (curr["close"] < curr["open"] and
                    next_["close"] > next_["open"]
                    and next_body > curr_body * 1.2):
                ob_top    = curr["open"]
                ob_bottom = curr["low"]
                tolerance = (
                    ob_top - ob_bottom) * 0.3
                in_zone   = (
                    ob_bottom - tolerance
                    <= current_price
                    <= ob_top + tolerance)
                bullish_obs.append({
                    "top":         round(ob_top, 4),
                    "bottom":      round(ob_bottom, 4),
                    "price_in_ob": in_zone,
                    "fresh":       (i >= n - 10),
                    "idx":         i,
                })

        print(
            f"[OB-5m] "
            f"Bull={len(bullish_obs)} | "
            f"Bear={len(bearish_obs)}")

        return {
            "bullish_obs": bullish_obs[-5:],
            "bearish_obs": bearish_obs[-5:],
        }

    except Exception as e:
        print(f"[OB ERROR] {e}")
        return {
            "bullish_obs": [],
            "bearish_obs": [],
        }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  LIQUIDITY — 5m Timeframe
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def detect_liquidity(df, lookback=40):
    """
    Liquidity levels detect karta hai
    Sweep hone ke baad reversal aata hai
    5m timeframe pe use hota hai
    """
    try:
        recent        = df.tail(lookback)
        highs         = recent["high"].values
        lows          = recent["low"].values
        current_price = df["close"].iloc[-1]
        n             = len(highs)
        swing_bars    = 2
        buy_liq       = []
        sell_liq      = []

        for i in range(swing_bars, n - swing_bars):
            if highs[i] == max(
                    highs[i - swing_bars:
                           i + swing_bars + 1]):
                buy_liq.append(highs[i])
            if lows[i] == min(
                    lows[i - swing_bars:
                          i + swing_bars + 1]):
                sell_liq.append(lows[i])

        buy_swept  = False
        sell_swept = False

        if buy_liq:
            last_high = buy_liq[-1]
            recent_5  = df.tail(5)
            tolerance = last_high * 0.002
            if (any(recent_5["high"] >
                    last_high - tolerance) and
                    current_price <
                    last_high + tolerance):
                buy_swept = True

        if sell_liq:
            last_low  = sell_liq[-1]
            recent_5  = df.tail(5)
            tolerance = last_low * 0.002
            if (any(recent_5["low"] <
                    last_low + tolerance) and
                    current_price >
                    last_low - tolerance):
                sell_swept = True

        print(
            f"[LIQ-5m] "
            f"BuySweep={buy_swept} | "
            f"SellSweep={sell_swept}")

        return {
            "buy_swept":   buy_swept,
            "sell_swept":  sell_swept,
            "buy_levels":  (buy_liq[-3:]
                            if buy_liq else []),
            "sell_levels": (sell_liq[-3:]
                            if sell_liq else []),
        }

    except Exception:
        return {
            "buy_swept":   False,
            "sell_swept":  False,
            "buy_levels":  [],
            "sell_levels": [],
        }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  FAIR VALUE GAP — 5m Timeframe
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def detect_fvg(df, lookback=30):
    """
    Fair Value Gaps detect karta hai
    Price gaps jahan market wapas aata hai
    5m timeframe pe use hota hai
    """
    try:
        fvgs          = []
        recent        = df.tail(
            lookback).reset_index(drop=True)
        n             = len(recent)
        current_price = recent["close"].iloc[-1]

        for i in range(2, n):
            c1 = recent.iloc[i - 2]
            c3 = recent.iloc[i]

            if c1["high"] < c3["low"]:
                gap_size = (
                    (c3["low"] - c1["high"]) /
                    c1["high"]) * 100
                if gap_size >= 0.02:
                    tolerance = (
                        c3["low"] -
                        c1["high"]) * 0.3
                    fvgs.append({
                        "type":   "BULL",
                        "top":    round(
                            c3["low"], 4),
                        "bottom": round(
                            c1["high"], 4),
                        "size":   round(
                            gap_size, 3),
                        "fresh":  (i >= n - 8),
                        "retest": (
                            c1["high"] - tolerance
                            <= current_price
                            <= c3["low"] + tolerance
                        ),
                    })

            elif c1["low"] > c3["high"]:
                gap_size = (
                    (c1["low"] - c3["high"]) /
                    c3["high"]) * 100
                if gap_size >= 0.02:
                    tolerance = (
                        c1["low"] -
                        c3["high"]) * 0.3
                    fvgs.append({
                        "type":   "BEAR",
                        "top":    round(
                            c1["low"], 4),
                        "bottom": round(
                            c3["high"], 4),
                        "size":   round(
                            gap_size, 3),
                        "fresh":  (i >= n - 8),
                        "retest": (
                            c3["high"] - tolerance
                            <= current_price
                            <= c1["low"] + tolerance
                        ),
                    })

        bull_fvg = len(
            [f for f in fvgs if f["type"] == "BULL"])
        bear_fvg = len(
            [f for f in fvgs if f["type"] == "BEAR"])
        print(
            f"[FVG-5m] "
            f"Bull={bull_fvg} | "
            f"Bear={bear_fvg}")

        return fvgs

    except Exception as e:
        print(f"[FVG ERROR] {e}")
        return []


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  RR CHECK
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def check_rr(entry, sl, tp, direction,
             min_rr=2.0):
    """
    Risk Reward Ratio check karta hai
    Minimum 1:2 RR chahiye trade ke liye
    """
    try:
        if direction == "BUY":
            risk   = entry - sl
            reward = tp - entry
        else:
            risk   = sl - entry
            reward = entry - tp

        if risk <= 0:
            print(
                f"[RR] Risk invalid: "
                f"{risk:.4f}")
            return False, 0.0

        rr = reward / risk
        ok = rr >= min_rr

        print(
            f"[RR] Risk={risk:.4f} | "
            f"Reward={reward:.4f} | "
            f"RR=1:{rr:.2f} | "
            f"{'OK ✅' if ok else 'SKIP ❌'}")

        return ok, round(rr, 2)

    except Exception as e:
        print(f"[RR ERROR] {e}")
        return True, 0.0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  QUICK MARKET SCAN — Loss Hold Decision
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def quick_market_scan(ex, symbol, position):
    """
    Max hold ke time quick scan karta hai
    Score >= 7 toh hold karo, nahi toh close karo
    5m aur 1m pe check karta hai
    """
    try:
        score   = 0
        reasons = []

        bars_1m = safe_fetch_ohlcv(
            ex, symbol, "1m", 50)
        bars_5m = safe_fetch_ohlcv(
            ex, symbol, "5m", 50)

        if bars_1m is None or bars_5m is None:
            print(
                f"[{symbol}][QUICK SCAN] "
                f"Data fail")
            return 0, ["Data fail — close"]

        df_1m = pd.DataFrame(
            bars_1m,
            columns=["time", "open", "high",
                     "low", "close", "volume"])
        df_5m = pd.DataFrame(
            bars_5m,
            columns=["time", "open", "high",
                     "low", "close", "volume"])

        # Check 1: 5m Structure (2 pts)
        structure_5m = detect_structure(df_5m)
        if (position == "BUY" and
                structure_5m == "BULL"):
            score += 2
            reasons.append("5m BULL (+2)")
        elif (position == "SELL" and
              structure_5m == "BEAR"):
            score += 2
            reasons.append("5m BEAR (+2)")
        else:
            reasons.append(
                f"5m {structure_5m} (0)")

        # Check 2: 1m Structure (2 pts)
        structure_1m = detect_structure(df_1m)
        if (position == "BUY" and
                structure_1m == "BULL"):
            score += 2
            reasons.append("1m BULL (+2)")
        elif (position == "SELL" and
              structure_1m == "BEAR"):
            score += 2
            reasons.append("1m BEAR (+2)")
        else:
            reasons.append(
                f"1m {structure_1m} (0)")

        # Check 3: Order Block 5m (2 pts)
        obs = detect_order_blocks(df_5m)
        if position == "BUY":
            ob_hit = [
                o for o in obs["bullish_obs"]
                if o["price_in_ob"]]
            if ob_hit:
                score += 2
                reasons.append(
                    "5m Bullish OB (+2)")
            else:
                reasons.append(
                    "5m No Bullish OB (0)")
        else:
            ob_hit = [
                o for o in obs["bearish_obs"]
                if o["price_in_ob"]]
            if ob_hit:
                score += 2
                reasons.append(
                    "5m Bearish OB (+2)")
            else:
                reasons.append(
                    "5m No Bearish OB (0)")

        # Check 4: Volume 1m (2 pts)
        avg_vol   = (
            df_1m["volume"].tail(20).mean())
        last_vol  = df_1m["volume"].iloc[-1]
        vol_ratio = (
            last_vol / avg_vol
            if avg_vol > 0 else 0)
        if vol_ratio >= 1.5:
            score += 2
            reasons.append(
                f"Vol {vol_ratio:.1f}x (+2)")
        elif vol_ratio >= 1.0:
            score += 1
            reasons.append(
                f"Vol {vol_ratio:.1f}x (+1)")
        else:
            reasons.append(
                f"Vol {vol_ratio:.1f}x (0)")

        # Check 5: Momentum 1m (2 pts)
        closes = df_1m["close"].tail(5).values
        if position == "BUY":
            going_up = sum(
                1 for i in range(1, len(closes))
                if closes[i] > closes[i - 1])
            if going_up >= 4:
                score += 2
                reasons.append(
                    f"UP mom {going_up}/4 (+2)")
            elif going_up >= 3:
                score += 1
                reasons.append(
                    f"UP mom {going_up}/4 (+1)")
            else:
                reasons.append(
                    f"UP mom {going_up}/4 (0)")
        else:
            going_down = sum(
                1 for i in range(1, len(closes))
                if closes[i] < closes[i - 1])
            if going_down >= 4:
                score += 2
                reasons.append(
                    f"DN mom {going_down}/4 (+2)")
            elif going_down >= 3:
                score += 1
                reasons.append(
                    f"DN mom {going_down}/4 (+1)")
            else:
                reasons.append(
                    f"DN mom {going_down}/4 (0)")

        reasons.append(
            f"Quick Score: {score}/10")
        print(
            f"[{symbol}][QUICK SCAN] "
            f"Score={score}/10")
        return score, reasons

    except Exception as e:
        print(
            f"[{symbol}][QUICK SCAN ERROR] {e}")
        return 0, [f"Error: {e}"]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  SMART MONEY SCORE — 12 Points (3 Timeframe MTF)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def smart_money_score(
        structure_15m,
        structure_5m,
        structure_1m,
        liq,
        obs,
        fvgs,
        bos_choch_15m=None,
        bos_choch_5m=None,
        rsi_val=50.0,
        ma_ok=True,
        eq_levels=None,
        volume_ok=True):
    """
    Multi-Timeframe Smart Money Score Calculator
    ─────────────────────────────────────────────
    15m Checks (4 pts) — Main Trend
      ├── Structure    : 2 pts
      ├── BOS/CHOCH    : 1 pt
      └── MA EMA20/50  : 1 pt

    5m Checks (5 pts) — Confirmation
      ├── Structure    : 1 pt
      ├── BOS/CHOCH    : 2 pts
      ├── Order Block  : 1 pt
      └── FVG + Liq    : 1 pt

    1m Checks (3 pts) — Entry
      ├── RSI          : 1 pt
      ├── Equal Levels : 1 pt
      └── Volume       : 1 pt
    ─────────────────────────────────────────────
    Total              : 12 pts
    Min to Trade       : 8 pts
    """
    points    = 0
    direction = None
    reasons   = []

    # ════════════════════════════════════════
    #  15m CHECKS — 4 Points — MAIN TREND
    # ════════════════════════════════════════

    # Check 1+2: 15m Market Structure (2 pts)
    # Higher High + Higher Low = BULL
    # Lower High  + Lower Low  = BEAR
    if structure_15m == "BULL":
        points    += 2
        direction  = "BUY"
        reasons.append(
            "15m BULL Structure (+2) ✅")
    elif structure_15m == "BEAR":
        points    += 2
        direction  = "SELL"
        reasons.append(
            "15m BEAR Structure (+2) ✅")
    else:
        reasons.append(
            "15m RANGE — Signal Skip ❌")
        return 0, "WAIT", reasons

    # Check 3: 15m BOS / CHOCH (1 pt)
    # Break of Structure = Trend continue
    # Change of Character = Reversal
    if bos_choch_15m:
        bos_type_15m = bos_choch_15m.get(
            "type", "NONE")
        if (direction == "BUY" and
                bos_type_15m in [
                    "BOS_BULL", "CHOCH_BULL"]):
            points += 1
            reasons.append(
                f"15m {bos_type_15m} (+1) ✅")
        elif (direction == "SELL" and
              bos_type_15m in [
                  "BOS_BEAR", "CHOCH_BEAR"]):
            points += 1
            reasons.append(
                f"15m {bos_type_15m} (+1) ✅")
        else:
            reasons.append(
                f"15m BOS/CHOCH="
                f"{bos_type_15m} (0)")
    else:
        reasons.append(
            "15m BOS/CHOCH N/A (0)")

    # Check 4: 15m Moving Average (1 pt)
    # EMA20 > EMA50 + Price above = Strong Bull
    # EMA20 < EMA50 + Price below = Strong Bear
    if ma_ok:
        points += 1
        reasons.append(
            "15m MA Confirms (+1) ✅")
    else:
        reasons.append(
            "15m MA Against (0) ❌")

    # ════════════════════════════════════════
    #  5m CHECKS — 5 Points — CONFIRMATION
    # ════════════════════════════════════════

    # Check 5: 5m Structure Confirmation (1 pt)
    # 15m trend ko 5m confirm karta hai
    if ((direction == "BUY" and
         structure_5m == "BULL") or
            (direction == "SELL" and
             structure_5m == "BEAR")):
        points += 1
        reasons.append(
            "5m Structure Confirms (+1) ✅")
    elif structure_5m == "RANGE":
        reasons.append(
            "5m RANGE — Weak (0)")
    else:
        reasons.append(
            "5m Structure Opposite (0) ❌")

    # Check 6+7: 5m BOS / CHOCH (2 pts)
    # 5m pe bhi BOS/CHOCH confirmation chahiye
    if bos_choch_5m:
        bos_type_5m = bos_choch_5m.get(
            "type", "NONE")
        if (direction == "BUY" and
                bos_type_5m in [
                    "BOS_BULL", "CHOCH_BULL"]):
            points += 2
            reasons.append(
                f"5m {bos_type_5m} (+2) ✅")
        elif (direction == "SELL" and
              bos_type_5m in [
                  "BOS_BEAR", "CHOCH_BEAR"]):
            points += 2
            reasons.append(
                f"5m {bos_type_5m} (+2) ✅")
        else:
            reasons.append(
                f"5m BOS/CHOCH="
                f"{bos_type_5m} (0)")
    else:
        reasons.append(
            "5m BOS/CHOCH N/A (0)")

    # Check 8: 5m Order Block (1 pt)
    # Smart Money ke entry zones
    if direction == "BUY":
        ob_hit = [
            ob for ob in obs["bullish_obs"]
            if ob["price_in_ob"]]
        if ob_hit:
            best_ob = sorted(
                ob_hit,
                key=lambda x: x["fresh"],
                reverse=True)[0]
            points += 1
            reasons.append(
                f"5m Bull OB "
                f"{best_ob['bottom']:.4f}-"
                f"{best_ob['top']:.4f} (+1) ✅")
        else:
            reasons.append(
                "5m No Bull OB (0)")
    else:
        ob_hit = [
            ob for ob in obs["bearish_obs"]
            if ob["price_in_ob"]]
        if ob_hit:
            best_ob = sorted(
                ob_hit,
                key=lambda x: x["fresh"],
                reverse=True)[0]
            points += 1
            reasons.append(
                f"5m Bear OB "
                f"{best_ob['bottom']:.4f}-"
                f"{best_ob['top']:.4f} (+1) ✅")
        else:
            reasons.append(
                "5m No Bear OB (0)")

    # Check 9: 5m FVG + Liquidity (1 pt)
    # Dono mein se koi ek milne par bhi point milta hai
    liq_ok = False
    fvg_ok = False

    if direction == "BUY":
        if liq["sell_swept"]:
            liq_ok = True
        bull_fvg = [
            f for f in fvgs
            if f["type"] == "BULL"
            and f["retest"]]
        if bull_fvg:
            fvg_ok = True
            reasons.append(
                f"5m Bull FVG "
                f"{bull_fvg[-1]['bottom']:.4f}-"
                f"{bull_fvg[-1]['top']:.4f}")
    else:
        if liq["buy_swept"]:
            liq_ok = True
        bear_fvg = [
            f for f in fvgs
            if f["type"] == "BEAR"
            and f["retest"]]
        if bear_fvg:
            fvg_ok = True
            reasons.append(
                f"5m Bear FVG "
                f"{bear_fvg[-1]['bottom']:.4f}-"
                f"{bear_fvg[-1]['top']:.4f}")

    if liq_ok and fvg_ok:
        points += 1
        reasons.append(
            "5m Liq + FVG Both (+1) ✅")
    elif liq_ok:
        points += 1
        reasons.append(
            "5m Liq Swept (+1) ✅")
    elif fvg_ok:
        points += 1
        reasons.append(
            "5m FVG Retest (+1) ✅")
    else:
        reasons.append(
            "5m No Liq/FVG (0)")

    # ════════════════════════════════════════
    #  1m CHECKS — 3 Points — ENTRY TIMING
    # ════════════════════════════════════════

    # Check 10: 1m RSI (1 pt)
    # BUY = RSI <= 45 (oversold)
    # SELL = RSI >= 55 (overbought)
    rsi_ok, rsi_msg = check_rsi(
        rsi_val, direction)
    if rsi_ok:
        points += 1
        reasons.append(
            f"1m {rsi_msg} (+1) ✅")
    else:
        reasons.append(
            f"1m {rsi_msg} (0)")

    # Check 11: 1m Equal Levels (1 pt)
    # Liquidity pools near price = good entry
    if eq_levels:
        if (direction == "BUY" and
                eq_levels["near_eq_low"]):
            points += 1
            reasons.append(
                "1m Near Eq Lows (+1) ✅")
        elif (direction == "SELL" and
              eq_levels["near_eq_high"]):
            points += 1
            reasons.append(
                "1m Near Eq Highs (+1) ✅")
        else:
            reasons.append(
                "1m No Eq Level (0)")
    else:
        reasons.append(
            "1m Eq Level N/A (0)")

    # Check 12: 1m Volume (1 pt)
    # Strong volume = Strong signal
    if volume_ok:
        points += 1
        reasons.append(
            "1m Volume Strong (+1) ✅")
    else:
        reasons.append(
            "1m Volume Weak (0) ❌")

    # ════════════════════════════════════════
    #  FINAL SCORE
    # ════════════════════════════════════════
    reasons.append(
        f"━━━━━━━━━━━━━━━━━━━━━━━━")
    reasons.append(
        f"Total Score: {points}/12")
    reasons.append(
        f"Direction  : {direction}")
    reasons.append(
        f"15m={structure_15m} | "
        f"5m={structure_5m} | "
        f"1m={structure_1m}")

    return points, direction, reasons


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  PnL CALCULATOR
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def calc_pnl(side, entry, exit_price, pos_size):
    """
    Profit aur Loss calculate karta hai
    BUY: (exit - entry) * size
    SELL: (entry - exit) * size
    """
    if side == "BUY":
        return (exit_price - entry) * pos_size
    else:
        return (entry - exit_price) * pos_size


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  DYNAMIC RR — Score Based
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def get_dynamic_rr(score):
    """
    Score ke hisaab se SL aur TP multiplier deta hai
    Score 8 = 1:2 RR
    Score 12 = 1:4 RR
    """
    score = int(score)
    if score >= 12:
        sl_mult = RR_CONFIG[12]["sl_mult"]
        tp_mult = RR_CONFIG[12]["tp_mult"]
        rr_type = "Perfect 1:4 🎯"
    elif score >= 11:
        sl_mult = RR_CONFIG[11]["sl_mult"]
        tp_mult = RR_CONFIG[11]["tp_mult"]
        rr_type = "Excellent 1:3.5 🔥"
    elif score >= 10:
        sl_mult = RR_CONFIG[10]["sl_mult"]
        tp_mult = RR_CONFIG[10]["tp_mult"]
        rr_type = "Strong 1:3 💪"
    elif score >= 9:
        sl_mult = RR_CONFIG[9]["sl_mult"]
        tp_mult = RR_CONFIG[9]["tp_mult"]
        rr_type = "Good 1:2.5 ✅"
    elif score >= 8:
        sl_mult = RR_CONFIG[8]["sl_mult"]
        tp_mult = RR_CONFIG[8]["tp_mult"]
        rr_type = "Moderate 1:2 ⚡"
    else:
        sl_mult = RR_DEFAULT_SL
        tp_mult = RR_DEFAULT_TP
        rr_type = "Default 1:2"

    print(
        f"[DYNAMIC RR] "
        f"Score={score}/12 | "
        f"SL={sl_mult}x | "
        f"TP={tp_mult}x | "
        f"{rr_type}")
    return sl_mult, tp_mult, rr_type


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  PERIODIC UPDATE — All Symbols Combined
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def run_periodic_update():
    """
    Har 30 min mein sab symbols ka update bhejta hai
    Active trades ka PnL aur status dikhata hai
    """
    time.sleep(UPDATE_INTERVAL)
    while True:
        try:
            now = datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S")

            msg  = (
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"  SCALP UPDATE\n"
                f"  {now}\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n")

            total_capital = 0.0
            active_count  = 0
            total_pnl_now = 0.0

            for sym in SYMBOLS:
                sym_name = sym.split("/")[0]

                with state_lock:
                    st = dict(
                        trade_states[sym])

                price     = st["last_price"]
                capital   = st["capital"]
                points    = st["last_points"]
                position  = st["position"]
                entry     = st["entry_price"]
                sl        = st["sl_price"]
                tp        = st["tp_price"]
                psize     = st["pos_size"]
                etime     = st["entry_time"]
                s15m      = st["struct_15m"]
                s5m       = st["struct_5m"]
                ext_count = st["extension_count"]
                rr_t      = st["rr_type"]

                total_capital += capital

                if (position is not None and
                        etime is not None and
                        price > 0):
                    active_count  += 1
                    pnl_now = calc_pnl(
                        position, entry,
                        price, psize)
                    total_pnl_now += pnl_now
                    dur = str(
                        datetime.now() -
                        etime
                    ).split(".")[0]

                    if position == "BUY":
                        tp_dist = (
                            (tp - price) /
                            price) * 100
                        sl_dist = (
                            (price - sl) /
                            price) * 100
                    else:
                        tp_dist = (
                            (price - tp) /
                            price) * 100
                        sl_dist = (
                            (sl - price) /
                            price) * 100

                    icon = (
                        "🟢" if pnl_now >= 0
                        else "🔴")

                    msg += (
                        f"\n{icon} {sym_name}\n"
                        f"Side   : {position}\n"
                        f"Entry  : {entry:.4f}\n"
                        f"Price  : {price:.4f}\n"
                        f"PnL    : "
                        f"{pnl_now:+.4f} USDT\n"
                        f"TP dist: {tp_dist:.2f}%\n"
                        f"SL dist: {sl_dist:.2f}%\n"
                        f"Score  : {points}/12\n"
                        f"15m    : {s15m}\n"
                        f"5m     : {s5m}\n"
                        f"RR     : {rr_t}\n"
                        f"Held   : {dur}\n"
                        f"Ext    : "
                        f"{ext_count}/"
                        f"{MAX_EXTENSIONS}\n"
                        f"Cap    : "
                        f"{capital:.4f} USDT\n"
                    )
                else:
                    status_icon = "⏳"
                    msg += (
                        f"\n{status_icon} "
                        f"{sym_name}\n"
                        f"Status : WAIT\n"
                        f"Price  : {price:.4f}\n"
                        f"Score  : {points}/12\n"
                        f"15m    : {s15m}\n"
                        f"5m     : {s5m}\n"
                        f"Cap    : "
                        f"{capital:.4f} USDT\n"
                    )

            msg += (
                f"\n━━━━━━━━━━━━━━━━━━━━━━\n"
                f"Active : "
                f"{active_count}/{len(SYMBOLS)}\n"
                f"PnL Now: "
                f"{total_pnl_now:+.4f} USDT\n"
                f"Total Cap: "
                f"{total_capital:.4f} USDT\n"
                f"━━━━━━━━━━━━━━━━━━━━━━")

            send_telegram(msg)

        except Exception as e:
            print(f"[UPDATE ERROR] {e}")

        time.sleep(UPDATE_INTERVAL)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  DAILY REPORT — All Symbols Combined
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def run_daily_report():
    """
    Raat 11:59 IST mein daily report bhejta hai
    Sab symbols ki combined stats dikhata hai
    """
    while True:
        try:
            ist = timezone(
                timedelta(hours=5, minutes=30))
            now = datetime.now(ist)

            if (now.hour == 23 and
                    now.minute == 59):

                today_str = now.strftime(
                    "%d/%m/%Y")

                msg = (
                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"  DAILY REPORT\n"
                    f"  {today_str}\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n")

                grand_total  = 0
                grand_wins   = 0
                grand_losses = 0
                grand_pnl    = 0.0
                grand_cap    = 0.0

                for sym in SYMBOLS:
                    sym_name = sym.split("/")[0]
                    daily    = get_daily_stats(sym)
                    overall  = get_overall_stats(sym)

                    if daily:
                        grand_total  += daily["total"]
                        grand_wins   += daily["wins"]
                        grand_losses += daily["losses"]
                        grand_pnl    += daily["pnl"]
                        grand_cap    += daily["capital"]

                        msg += (
                            f"\n📊 {sym_name}\n"
                            f"Trades  : "
                            f"{daily['total']}\n"
                            f"Win     : "
                            f"{daily['wins']} ✅\n"
                            f"Loss    : "
                            f"{daily['losses']} ❌\n"
                            f"Win Rate: "
                            f"{daily['win_rate']}%\n"
                            f"PnL     : "
                            f"{daily['pnl']:+.4f} USDT\n"
                            f"Best    : "
                            f"+{daily['best']:.4f}\n"
                            f"Worst   : "
                            f"{daily['worst']:.4f}\n"
                            f"Capital : "
                            f"{daily['capital']:.4f}\n"
                        )

                        if overall:
                            msg += (
                                f"Overall : "
                                f"{overall['total']}T "
                                f"WR={overall['win_rate']}% "
                                f"PnL={overall['pnl']:+.4f}\n"
                            )
                    else:
                        msg += (
                            f"\n📊 {sym_name}: "
                            f"No trades today\n")

                if grand_total > 0:
                    grand_wr = round(
                        (grand_wins /
                         grand_total) * 100, 1)
                    msg += (
                        f"\n━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"  COMBINED TODAY\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"Total Trades : "
                        f"{grand_total}\n"
                        f"Total Wins   : "
                        f"{grand_wins} ✅\n"
                        f"Total Losses : "
                        f"{grand_losses} ❌\n"
                        f"Win Rate     : "
                        f"{grand_wr}%\n"
                        f"Total PnL    : "
                        f"{grand_pnl:+.4f} USDT\n"
                        f"Total Capital: "
                        f"{grand_cap:.4f} USDT\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━")
                else:
                    msg += (
                        f"\n━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"Aaj koi trade nahi hua\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━")

                send_telegram(msg)
                time.sleep(70)

        except Exception as e:
            print(f"[DAILY ERROR] {e}")

        time.sleep(30)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  DECISION ENGINE — Per Symbol (15m + 5m + 1m MTF)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def run_decision_engine_for_symbol(symbol):
    """
    Har symbol ke liye alag decision engine
    15m = Main Trend
    5m  = Confirmation + BOS + OB + FVG + Liq
    1m  = RSI + EqLevels + Volume + Entry
    Har 60 seconds mein scan karta hai
    """
    exchange = get_exchange()
    sym_name = symbol.split("/")[0]
    print(
        f"[{sym_name}][DECISION] "
        f"v4.0 MTF Started ✅")

    while True:
        try:
            scan_time = datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S")

            good_session, session_name = (
                is_good_session())
            update_state(
                symbol,
                last_session=session_name)

            # ── Data Fetch — 3 Timeframes ─────────
            bars_15m = safe_fetch_ohlcv(
                exchange, symbol, "15m", 100)
            time.sleep(0.5)
            bars_5m  = safe_fetch_ohlcv(
                exchange, symbol, "5m", 100)
            time.sleep(0.5)
            bars_1m  = safe_fetch_ohlcv(
                exchange, symbol, "1m", 100)

            if (bars_15m is None or
                    bars_5m is None or
                    bars_1m is None):
                print(
                    f"[{sym_name}][DECISION] "
                    f"Fetch fail — Retry...")
                exchange = get_exchange()
                time.sleep(30)
                continue

            # ── DataFrames ────────────────────────
            df_15m = pd.DataFrame(
                bars_15m,
                columns=[
                    "time", "open", "high",
                    "low", "close", "volume"])
            df_5m  = pd.DataFrame(
                bars_5m,
                columns=[
                    "time", "open", "high",
                    "low", "close", "volume"])
            df_1m  = pd.DataFrame(
                bars_1m,
                columns=[
                    "time", "open", "high",
                    "low", "close", "volume"])

            # ── Data Check ───────────────────────
            if (len(df_15m) < 50 or
                    len(df_5m) < 50 or
                    len(df_1m) < 50):
                print(
                    f"[{sym_name}][DECISION] "
                    f"Data insufficient")
                time.sleep(30)
                continue

            df_15m["time"] = pd.to_datetime(
                df_15m["time"], unit="ms")
            df_5m["time"]  = pd.to_datetime(
                df_5m["time"],  unit="ms")
            df_1m["time"]  = pd.to_datetime(
                df_1m["time"],  unit="ms")

            # ── Current Price ─────────────────────
            current_price = float(
                df_1m["close"].iloc[-1])

            # ── ATR — 3 Timeframes ────────────────
            atr_1m  = calc_atr(
                df_1m,  ATR_PERIOD)
            atr_5m  = calc_atr(
                df_5m,  ATR_PERIOD)
            atr_15m = calc_atr(
                df_15m, ATR_PERIOD)

            print(
                f"[{sym_name}][ATR] "
                f"1m={atr_1m:.4f} | "
                f"5m={atr_5m:.4f} | "
                f"15m={atr_15m:.4f}")

            # ── Volume — 1m ───────────────────────
            volume_ok = check_volume(
                df_1m, symbol, VOLUME_MULT)

            # ── Structure — 3 Timeframes ──────────
            structure_15m = detect_structure(
                df_15m)
            structure_5m  = detect_structure(
                df_5m)
            structure_1m  = detect_structure(
                df_1m)

            print(
                f"[{sym_name}][STRUCT] "
                f"15m={structure_15m} | "
                f"5m={structure_5m} | "
                f"1m={structure_1m}")

            # ── BOS/CHOCH — 15m + 5m ─────────────
            bos_choch_15m = detect_bos_choch(
                df_15m)
            bos_choch_5m  = detect_bos_choch(
                df_5m)

            print(
                f"[{sym_name}][BOS] "
                f"15m={bos_choch_15m['type']} | "
                f"5m={bos_choch_5m['type']}")

            # ── Order Block — 5m ──────────────────
            obs = detect_order_blocks(df_5m)

            # ── FVG — 5m ──────────────────────────
            fvgs = detect_fvg(df_5m)

            # ── Liquidity — 5m ────────────────────
            liq = detect_liquidity(df_5m)

            # ── RSI — 1m ──────────────────────────
            rsi_val = calc_rsi(df_1m, 14)

            # ── Equal Levels — 1m ─────────────────
            eq_levels = detect_equal_levels(
                df_1m)

            # ── MA — 15m ──────────────────────────
            temp_dir = (
                "BUY"  if structure_15m == "BULL"
                else "SELL" if structure_15m == "BEAR"
                else "BUY")

            ma_ok, ma_status, ema20, ema50 = (
                check_moving_average(
                    df_15m, temp_dir))

            print(
                f"[{sym_name}][MA-15m] "
                f"Status={ma_status} | "
                f"EMA20={ema20:.4f} | "
                f"EMA50={ema50:.4f}")

            # ── Smart Money Score — 12 pts ────────
            points, direction, reasons = (
                smart_money_score(
                    structure_15m,
                    structure_5m,
                    structure_1m,
                    liq,
                    obs,
                    fvgs,
                    bos_choch_15m=bos_choch_15m,
                    bos_choch_5m=bos_choch_5m,
                    rsi_val=rsi_val,
                    ma_ok=ma_ok,
                    eq_levels=eq_levels,
                    volume_ok=volume_ok,
                ))

            confidence = int(
                (points / 12) * 100)

            # ── Signal Determine ──────────────────
            if (points >= MIN_SCORE and
                    direction == "BUY"):
                signal = "BUY"
            elif (points >= MIN_SCORE and
                  direction == "SELL"):
                signal = "SELL"
            else:
                signal = "WAIT"

            # ── ATR Filter — Symbol Specific ──────
            if signal != "WAIT":
                if not check_atr_range(
                        symbol, atr_15m):
                    print(
                        f"[{sym_name}] "
                        f"ATR Filter — Skip")
                    signal = "WAIT"

            # ── Session Filter ────────────────────
            if (not good_session and
                    signal != "WAIT"):
                if points >= 10:
                    print(
                        f"[{sym_name}][SESSION] "
                        f"Asian Score={points}/12 "
                        f"HIGH — Allowed ✅")
                else:
                    print(
                        f"[{sym_name}][SESSION] "
                        f"Asian Score={points}/12 "
                        f"LOW — Skip ❌")
                    signal = "WAIT"

            # ── State Update ──────────────────────
            update_state(
                symbol,
                last_signal=signal,
                last_conf=confidence,
                last_points=points,
                last_price=current_price,
                struct_15m=structure_15m,
                struct_5m=structure_5m,
                atr_15m=atr_15m,
            )

            print(
                f"[{sym_name}] {scan_time} | "
                f"Score={points}/12 | "
                f"Signal={signal} | "
                f"15m={structure_15m} | "
                f"5m={structure_5m} | "
                f"1m={structure_1m} | "
                f"BOS15={bos_choch_15m['type']} | "
                f"BOS5={bos_choch_5m['type']} | "
                f"ATR15m={atr_15m:.4f} | "
                f"RSI={rsi_val:.1f} | "
                f"Price={current_price:.4f} | "
                f"{session_name}")

            # ── Signal Queue ──────────────────────
            signal_data = {
                "signal":        signal,
                "confidence":    confidence,
                "score":         points,
                "atr_1m":        round(atr_1m,  6),
                "atr_5m":        round(atr_5m,  6),
                "atr_15m":       round(atr_15m, 6),
                "rsi":           round(rsi_val, 2),
                "ma_status":     ma_status,
                "time":          scan_time,
                "reasons":       reasons,
                "volume_ok":     volume_ok,
                "session":       session_name,
                "price":         current_price,
                "structure_15m": structure_15m,
                "structure_5m":  structure_5m,
                "structure_1m":  structure_1m,
                "bos_15m":       bos_choch_15m[
                    "type"],
                "bos_5m":        bos_choch_5m[
                    "type"],
            }

            try:
                signal_queues[symbol].get_nowait()
            except queue.Empty:
                pass
            signal_queues[symbol].put(signal_data)

            # ── Log Save ──────────────────────────
            files = get_files(symbol)
            try:
                with open(
                        files["log"], "r",
                        encoding="utf-8") as f:
                    log = json.load(f)
            except Exception:
                log = []

            log.append({
                "time":          scan_time,
                "signal":        signal,
                "points":        points,
                "atr_1m":        round(atr_1m,  6),
                "atr_5m":        round(atr_5m,  6),
                "atr_15m":       round(atr_15m, 6),
                "rsi":           round(rsi_val, 2),
                "price":         current_price,
                "session":       session_name,
                "volume_ok":     volume_ok,
                "structure_15m": structure_15m,
                "structure_5m":  structure_5m,
                "structure_1m":  structure_1m,
                "bos_15m":       bos_choch_15m[
                    "type"],
                "bos_5m":        bos_choch_5m[
                    "type"],
                "ma_status":     ma_status,
            })
            log = log[-3000:]

            with open(
                    files["log"], "w",
                    encoding="utf-8") as f:
                json.dump(log, f, indent=2)

        except Exception as e:
            print(
                f"[{sym_name}][DECISION ERROR] "
                f"{e}")
            if ("connection" in str(e).lower() or
                    "timeout" in str(e).lower()):
                exchange = get_exchange()
            time.sleep(30)

        time.sleep(DECISION_SCAN)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  EXECUTION ENGINE — Per Symbol
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def run_execution_engine_for_symbol(symbol):
    """
    Har symbol ke liye alag execution engine
    Capital = CAPITAL_PER_SYM (Total / 4)
    Leverage = 5x
    Trade Use = 90% of per symbol capital
    """
    ex                 = get_exchange()
    capital            = load_capital(symbol)
    sym_name           = symbol.split("/")[0]
    position           = None
    entry_price        = 0.0
    entry_time         = None
    pos_size           = 0.0
    sl_price           = 0.0
    tp_price           = 0.0
    capital_used       = 0.0
    cooldown_end       = load_cooldown(symbol)
    consecutive_losses = 0
    extension_count    = 0
    sl_mult            = RR_DEFAULT_SL
    tp_mult            = RR_DEFAULT_TP
    rr_type            = "Default"
    signal             = "WAIT"
    score              = 0
    atr_15m            = 0.0
    reason             = ""
    session            = ""
    vol_ok             = True
    s15m               = "RANGE"
    s5m                = "RANGE"
    bos15              = "NONE"
    bos5               = "NONE"

    print(
        f"[{sym_name}][EXECUTE] "
        f"Waiting for first signal...")

    signal_data = signal_queues[symbol].get()

    print(
        f"[{sym_name}][EXECUTE] "
        f"v4.0 MTF Started! ✅")

    send_telegram(
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"  BOT v4.0 STARTED\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Symbol   : {sym_name}\n"
        f"Capital  : {capital:.4f} USDT\n"
        f"Trade Use: "
        f"{capital * CAPITAL_USE_PCT / 100:.4f} USDT\n"
        f"Leverage : {LEVERAGE}x\n"
        f"Min Score: {MIN_SCORE}/12\n"
        f"Max Hold : "
        f"{MAX_HOLD_SECONDS // 60} min\n"
        f"Ext      : {MAX_HOLD_EXTENSION}s "
        f"x {MAX_EXTENSIONS}\n"
        f"TP Zone  : "
        f"{int(TP_EXIT_MIN_PCT*100)}-"
        f"{int(TP_EXIT_MAX_PCT*100)}%\n"
        f"RR Range : 8=1:2 to 12=1:4\n"
        f"BE Trig  : {BREAK_EVEN_TRIGGER}%\n"
        f"Trail    : {TRAIL_TRIGGER_PCT}%\n"
        f"TF       : 15m+5m+1m MTF\n"
        f"━━━━━━━━━━━━━━━━━━━━━━"
    )

    # Initial signal values
    signal  = signal_data.get("signal",  "WAIT")
    score   = signal_data.get("score",   0)
    atr_15m = signal_data.get("atr_15m", 0.0)
    reason  = " | ".join(
        signal_data.get("reasons", []))
    session = signal_data.get("session", "")
    vol_ok  = signal_data.get("volume_ok", True)
    s15m    = signal_data.get(
        "structure_15m", "RANGE")
    s5m     = signal_data.get(
        "structure_5m",  "RANGE")
    bos15   = signal_data.get("bos_15m", "NONE")
    bos5    = signal_data.get("bos_5m",  "NONE")

    while True:
        try:
            # ── Get Latest Signal ─────────────────
            try:
                new_data = (
                    signal_queues[symbol]
                    .get_nowait())
                signal  = new_data.get(
                    "signal",  "WAIT")
                score   = new_data.get(
                    "score",   0)
                atr_15m = new_data.get(
                    "atr_15m", 0.0)
                reason  = " | ".join(
                    new_data.get("reasons", []))
                session = new_data.get(
                    "session", "")
                vol_ok  = new_data.get(
                    "volume_ok", True)
                s15m    = new_data.get(
                    "structure_15m", "RANGE")
                s5m     = new_data.get(
                    "structure_5m",  "RANGE")
                bos15   = new_data.get(
                    "bos_15m", "NONE")
                bos5    = new_data.get(
                    "bos_5m",  "NONE")
            except queue.Empty:
                pass

            # ── Current Price ─────────────────────
            current_price = get_cached_price(
                ex, symbol)
            if current_price is None:
                print(
                    f"[{sym_name}][EXECUTE] "
                    f"Price fail")
                ex = get_exchange()
                time.sleep(EXECUTE_SCAN)
                continue

            now = datetime.now().strftime(
                "%H:%M:%S")

            # ── State Update ──────────────────────
            update_state(
                symbol,
                last_price=current_price,
                capital=capital,
                position=position,
                entry_price=entry_price,
                entry_time=entry_time,
                sl_price=sl_price,
                tp_price=tp_price,
                pos_size=pos_size,
                capital_used=capital_used,
                extension_count=extension_count,
                rr_type=rr_type,
            )

            # ══════════════════════════════════════
            #  SMART MAX HOLD
            # ══════════════════════════════════════
            if (position is not None and
                    entry_time is not None):
                held_secs = (
                    datetime.now() -
                    entry_time).seconds

                if held_secs >= MAX_HOLD_SECONDS:
                    pnl_now = calc_pnl(
                        position,
                        entry_price,
                        current_price,
                        pos_size)

                    # Profit mein hai — Close karo
                    if pnl_now >= 0:
                        pnl      = pnl_now
                        capital += pnl
                        duration = str(
                            datetime.now() -
                            entry_time
                        ).split(".")[0]
                        save_capital(
                            symbol, capital)
                        save_trade_history(
                            symbol, position,
                            entry_price,
                            current_price,
                            pnl, capital,
                            duration,
                            "Max Hold — Profit")
                        consecutive_losses = 0
                        print(
                            f"[{sym_name}]"
                            f"[MAX HOLD] "
                            f"Profit Close "
                            f"PnL={pnl:+.4f}")
                        send_telegram(
                            f"CLOSED — Max Hold ✅\n"
                            f"Symbol  : {sym_name}\n"
                            f"Side    : {position}\n"
                            f"Entry   : "
                            f"{entry_price:.4f}\n"
                            f"Exit    : "
                            f"{current_price:.4f}\n"
                            f"PnL     : "
                            f"{pnl:+.4f} USDT\n"
                            f"Capital : "
                            f"{capital:.4f} USDT\n"
                            f"Reason  : "
                            f"Profit ✅"
                        )
                        position        = None
                        entry_price     = 0.0
                        entry_time      = None
                        pos_size        = 0.0
                        sl_price        = 0.0
                        tp_price        = 0.0
                        capital_used    = 0.0
                        extension_count = 0
                        cooldown_end    = (
                            time.time() +
                            COOLDOWN_WIN)
                        save_cooldown(
                            symbol, cooldown_end)
                        update_state(
                            symbol,
                            position=None,
                            capital_used=0.0,
                            capital=capital,
                            last_tp_zone="",
                            extension_count=0)
                        time.sleep(EXECUTE_SCAN)
                        continue

                    else:
                        # Extension limit pahunch gaya
                        if (extension_count >=
                                MAX_EXTENSIONS):
                            pnl      = pnl_now
                            capital += pnl
                            duration = str(
                                datetime.now() -
                                entry_time
                            ).split(".")[0]
                            save_capital(
                                symbol, capital)
                            save_trade_history(
                                symbol, position,
                                entry_price,
                                current_price,
                                pnl, capital,
                                duration,
                                "Max Hold — Ext Over")
                            consecutive_losses += 1
                            smart_cd = (
                                COOLDOWN_2LOSS
                                if consecutive_losses >= 2
                                else COOLDOWN_LOSS)
                            print(
                                f"[{sym_name}]"
                                f"[MAX HOLD] "
                                f"Force Close "
                                f"PnL={pnl:+.4f}")
                            send_telegram(
                                f"CLOSED — Force ❌\n"
                                f"Symbol  : "
                                f"{sym_name}\n"
                                f"Side    : "
                                f"{position}\n"
                                f"Entry   : "
                                f"{entry_price:.4f}\n"
                                f"Exit    : "
                                f"{current_price:.4f}\n"
                                f"PnL     : "
                                f"{pnl:+.4f} USDT\n"
                                f"Capital : "
                                f"{capital:.4f} USDT\n"
                                f"Ext     : "
                                f"{extension_count}/"
                                f"{MAX_EXTENSIONS}"
                            )
                            position        = None
                            entry_price     = 0.0
                            entry_time      = None
                            pos_size        = 0.0
                            sl_price        = 0.0
                            tp_price        = 0.0
                            capital_used    = 0.0
                            extension_count = 0
                            cooldown_end    = (
                                time.time() +
                                smart_cd)
                            save_cooldown(
                                symbol, cooldown_end)
                            update_state(
                                symbol,
                                position=None,
                                capital_used=0.0,
                                capital=capital,
                                last_tp_zone="",
                                extension_count=0)
                            time.sleep(EXECUTE_SCAN)
                            continue

                        # Quick scan karo
                        print(
                            f"[{sym_name}]"
                            f"[MAX HOLD] "
                            f"Loss={pnl_now:+.4f}"
                            f" — Quick Scan...")
                        send_telegram(
                            f"MAX HOLD SCANNING\n"
                            f"Symbol : {sym_name}\n"
                            f"Side   : {position}\n"
                            f"PnL    : "
                            f"{pnl_now:+.4f} USDT\n"
                            f"Ext    : "
                            f"{extension_count}/"
                            f"{MAX_EXTENSIONS}"
                        )

                        q_score, q_reasons = (
                            quick_market_scan(
                                ex, symbol,
                                position))

                        if (q_score >=
                                HOLD_SCORE_MINIMUM):
                            extension_count += 1
                            update_state(
                                symbol,
                                extension_count=
                                extension_count)
                            print(
                                f"[{sym_name}]"
                                f"[MAX HOLD] "
                                f"Score={q_score}/10"
                                f" STRONG — Hold "
                                f"{extension_count}/"
                                f"{MAX_EXTENSIONS}")
                            send_telegram(
                                f"HOLD EXTENDED ⏳\n"
                                f"Symbol : "
                                f"{sym_name}\n"
                                f"Side   : "
                                f"{position}\n"
                                f"PnL    : "
                                f"{pnl_now:+.4f}\n"
                                f"Score  : "
                                f"{q_score}/10\n"
                                f"Ext    : "
                                f"{extension_count}/"
                                f"{MAX_EXTENSIONS}\n"
                                f"Reason : "
                                f"{' | '.join(q_reasons[:2])}"
                            )
                            time.sleep(
                                MAX_HOLD_EXTENSION)
                            continue

                        else:
                            pnl      = pnl_now
                            capital += pnl
                            duration = str(
                                datetime.now() -
                                entry_time
                            ).split(".")[0]
                            save_capital(
                                symbol, capital)
                            save_trade_history(
                                symbol, position,
                                entry_price,
                                current_price,
                                pnl, capital,
                                duration,
                                "Max Hold — Weak")
                            consecutive_losses += 1
                            smart_cd = (
                                COOLDOWN_2LOSS
                                if consecutive_losses >= 2
                                else COOLDOWN_LOSS)
                            print(
                                f"[{sym_name}]"
                                f"[MAX HOLD] "
                                f"Score={q_score}/10"
                                f" WEAK "
                                f"PnL={pnl:+.4f}")
                            send_telegram(
                                f"CLOSED — Weak ❌\n"
                                f"Symbol  : "
                                f"{sym_name}\n"
                                f"Side    : "
                                f"{position}\n"
                                f"Entry   : "
                                f"{entry_price:.4f}\n"
                                f"Exit    : "
                                f"{current_price:.4f}\n"
                                f"PnL     : "
                                f"{pnl:+.4f} USDT\n"
                                f"Capital : "
                                f"{capital:.4f} USDT\n"
                                f"Score   : "
                                f"{q_score}/10"
                            )
                            position        = None
                            entry_price     = 0.0
                            entry_time      = None
                            pos_size        = 0.0
                            sl_price        = 0.0
                            tp_price        = 0.0
                            capital_used    = 0.0
                            extension_count = 0
                            cooldown_end    = (
                                time.time() +
                                smart_cd)
                            save_cooldown(
                                symbol, cooldown_end)
                            update_state(
                                symbol,
                                position=None,
                                capital_used=0.0,
                                capital=capital,
                                last_tp_zone="",
                                extension_count=0)
                            time.sleep(EXECUTE_SCAN)
                            continue

            # ══════════════════════════════════════
            #  TP ZONE 70-90% EARLY EXIT
            # ══════════════════════════════════════
            if position is not None:
                try:
                    if position == "BUY":
                        tp_range = (
                            tp_price - entry_price)
                        tp_prog  = (
                            (current_price -
                             entry_price) /
                            tp_range
                        ) if tp_range != 0 else 0
                    else:
                        tp_range = (
                            entry_price - tp_price)
                        tp_prog  = (
                            (entry_price -
                             current_price) /
                            tp_range
                        ) if tp_range != 0 else 0

                    if (TP_EXIT_MIN_PCT
                            <= tp_prog
                            <= TP_EXIT_MAX_PCT):
                        pts = get_state(
                            symbol, "last_points")
                        if pts < TP_HOLD_MIN_SCORE:
                            pnl = calc_pnl(
                                position,
                                entry_price,
                                current_price,
                                pos_size)
                            capital += pnl
                            duration = str(
                                datetime.now() -
                                entry_time
                            ).split(".")[0]
                            save_capital(
                                symbol, capital)
                            save_trade_history(
                                symbol, position,
                                entry_price,
                                current_price,
                                pnl, capital,
                                duration,
                                "Early Exit")
                            if pnl > 0:
                                consecutive_losses = 0
                            else:
                                consecutive_losses += 1
                            print(
                                f"[{sym_name}]"
                                f"[EARLY EXIT] "
                                f"{tp_prog*100:.0f}%"
                                f" PnL={pnl:+.4f}")
                            send_telegram(
                                f"EARLY EXIT 🎯\n"
                                f"Symbol : "
                                f"{sym_name}\n"
                                f"Side   : "
                                f"{position}\n"
                                f"Entry  : "
                                f"{entry_price:.4f}\n"
                                f"Exit   : "
                                f"{current_price:.4f}\n"
                                f"PnL    : "
                                f"{pnl:+.4f} USDT\n"
                                f"Zone   : "
                                f"{tp_prog*100:.0f}%\n"
                                f"Score  : "
                                f"{pts}/12\n"
                                f"Capital: "
                                f"{capital:.4f} USDT"
                            )
                            position        = None
                            entry_price     = 0.0
                            entry_time      = None
                            pos_size        = 0.0
                            sl_price        = 0.0
                            tp_price        = 0.0
                            capital_used    = 0.0
                            extension_count = 0
                            smart_cd = (
                                COOLDOWN_WIN
                                if pnl > 0
                                else COOLDOWN_LOSS)
                            cooldown_end = (
                                time.time() +
                                smart_cd)
                            save_cooldown(
                                symbol, cooldown_end)
                            update_state(
                                symbol,
                                position=None,
                                capital_used=0.0,
                                capital=capital,
                                last_tp_zone="",
                                extension_count=0)
                            time.sleep(EXECUTE_SCAN)
                            continue
                        else:
                            update_state(
                                symbol,
                                last_tp_zone=(
                                    f"TP Zone "
                                    f"{tp_prog*100:.0f}%"
                                    f" | Score="
                                    f"{pts}/12 Strong"))
                    else:
                        update_state(
                            symbol,
                            last_tp_zone="")

                except Exception as e:
                    print(
                        f"[{sym_name}]"
                        f"[TP ZONE ERROR] {e}")

            # ══════════════════════════════════════
            #  BREAK EVEN SL
            # ══════════════════════════════════════
            if position is not None:
                try:
                    if position == "BUY":
                        be_pct = (
                            (current_price -
                             entry_price) /
                            entry_price) * 100
                        if (be_pct >=
                                BREAK_EVEN_TRIGGER
                                and sl_price <
                                entry_price):
                            sl_price = entry_price
                            update_state(
                                symbol,
                                sl_price=sl_price)
                            print(
                                f"[{sym_name}]"
                                f"[BE] BUY "
                                f"SL={sl_price:.4f}"
                                f" ✅")
                            send_telegram(
                                f"BREAK EVEN ✅\n"
                                f"Symbol : "
                                f"{sym_name}\n"
                                f"Side   : "
                                f"{position}\n"
                                f"Entry  : "
                                f"{entry_price:.4f}\n"
                                f"SL→BE  : "
                                f"{sl_price:.4f}\n"
                                f"Loss impossible!"
                            )
                    elif position == "SELL":
                        be_pct = (
                            (entry_price -
                             current_price) /
                            entry_price) * 100
                        if (be_pct >=
                                BREAK_EVEN_TRIGGER
                                and sl_price >
                                entry_price):
                            sl_price = entry_price
                            update_state(
                                symbol,
                                sl_price=sl_price)
                            print(
                                f"[{sym_name}]"
                                f"[BE] SELL "
                                f"SL={sl_price:.4f}"
                                f" ✅")
                            send_telegram(
                                f"BREAK EVEN ✅\n"
                                f"Symbol : "
                                f"{sym_name}\n"
                                f"Side   : "
                                f"{position}\n"
                                f"Entry  : "
                                f"{entry_price:.4f}\n"
                                f"SL→BE  : "
                                f"{sl_price:.4f}\n"
                                f"Loss impossible!"
                            )
                except Exception as e:
                    print(
                        f"[{sym_name}]"
                        f"[BE ERROR] {e}")

            # ══════════════════════════════════════
            #  TRAILING SL
            # ══════════════════════════════════════
            if position is not None:
                try:
                    if position == "BUY":
                        p_pct = (
                            (current_price -
                             entry_price) /
                            entry_price) * 100
                        if (p_pct >=
                                TRAIL_TRIGGER_PCT):
                            new_sl = (
                                current_price *
                                (1 -
                                 TRAIL_DISTANCE_PCT /
                                 100))
                            if new_sl > sl_price:
                                sl_price = new_sl
                                update_state(
                                    symbol,
                                    sl_price=sl_price)
                                print(
                                    f"[{sym_name}]"
                                    f"[TRAIL] BUY "
                                    f"SL={sl_price:.4f}"
                                    f" ✅")
                    elif position == "SELL":
                        p_pct = (
                            (entry_price -
                             current_price) /
                            entry_price) * 100
                        if (p_pct >=
                                TRAIL_TRIGGER_PCT):
                            new_sl = (
                                current_price *
                                (1 +
                                 TRAIL_DISTANCE_PCT /
                                 100))
                            if new_sl < sl_price:
                                sl_price = new_sl
                                update_state(
                                    symbol,
                                    sl_price=sl_price)
                                print(
                                    f"[{sym_name}]"
                                    f"[TRAIL] SELL "
                                    f"SL={sl_price:.4f}"
                                    f" ✅")
                except Exception as e:
                    print(
                        f"[{sym_name}]"
                        f"[TRAIL ERROR] {e}")

            # ══════════════════════════════════════
            #  SL / TP HIT CHECK
            # ══════════════════════════════════════
            if position is not None:
                hit_sl = (
                    (position == "BUY" and
                     current_price <= sl_price) or
                    (position == "SELL" and
                     current_price >= sl_price))
                hit_tp = (
                    (position == "BUY" and
                     current_price >= tp_price) or
                    (position == "SELL" and
                     current_price <= tp_price))

                if hit_sl or hit_tp:
                    label    = (
                        "STOP LOSS ❌"
                        if hit_sl
                        else "TAKE PROFIT ✅")
                    pnl      = calc_pnl(
                        position,
                        entry_price,
                        current_price,
                        pos_size)
                    capital += pnl
                    duration = str(
                        datetime.now() -
                        entry_time
                    ).split(".")[0]
                    save_capital(symbol, capital)
                    save_trade_history(
                        symbol, position,
                        entry_price,
                        current_price,
                        pnl, capital,
                        duration, label)

                    if pnl > 0:
                        consecutive_losses = 0
                        smart_cd  = COOLDOWN_WIN
                        cd_reason = "Win ✅"
                        result_icon = "🟢"
                    else:
                        consecutive_losses += 1
                        if consecutive_losses >= 2:
                            smart_cd  = COOLDOWN_2LOSS
                            cd_reason = (
                                f"{consecutive_losses}"
                                f" Loss streak! ⚠️")
                        else:
                            smart_cd  = COOLDOWN_LOSS
                            cd_reason = "Loss ❌"
                        result_icon = "🔴"

                    print(
                        f"[{sym_name}] "
                        f"{label} | "
                        f"PnL={pnl:+.4f} | "
                        f"CD={smart_cd}s")

                    send_telegram(
                        f"{result_icon} "
                        f"CLOSED — {label}\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"Symbol  : {sym_name}\n"
                        f"Side    : {position}\n"
                        f"Entry   : "
                        f"{entry_price:.4f}\n"
                        f"Exit    : "
                        f"{current_price:.4f}\n"
                        f"PnL     : "
                        f"{pnl:+.4f} USDT\n"
                        f"Capital : "
                        f"{capital:.4f} USDT\n"
                        f"RR Type : {rr_type}\n"
                        f"Time    : {duration}\n"
                        f"15m     : {s15m}\n"
                        f"5m      : {s5m}\n"
                        f"BOS 15m : {bos15}\n"
                        f"BOS 5m  : {bos5}\n"
                        f"Cooldown: {smart_cd}s\n"
                        f"Reason  : {cd_reason}\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━"
                    )

                    position        = None
                    entry_price     = 0.0
                    entry_time      = None
                    pos_size        = 0.0
                    sl_price        = 0.0
                    tp_price        = 0.0
                    capital_used    = 0.0
                    extension_count = 0
                    cooldown_end    = (
                        time.time() + smart_cd)
                    save_cooldown(
                        symbol, cooldown_end)
                    update_state(
                        symbol,
                        position=None,
                        capital_used=0.0,
                        capital=capital,
                        last_tp_zone="",
                        extension_count=0)
                    time.sleep(EXECUTE_SCAN)
                    continue

            # ══════════════════════════════════════
            #  COOLDOWN CHECK
            # ══════════════════════════════════════
            if (cooldown_end is not None and
                    time.time() < cooldown_end):
                remaining = int(
                    cooldown_end - time.time())
                print(
                    f"[{sym_name}][{now}] "
                    f"Cooldown {remaining}s...")
                time.sleep(EXECUTE_SCAN)
                continue

            # ══════════════════════════════════════
            #  ENTRY CHECK
            # ══════════════════════════════════════
            if position is None:
                if (signal in ["BUY", "SELL"] and
                        int(score) >= MIN_SCORE):

                    # Spread Check
                    spread_ok = check_spread(
                        ex, symbol)
                    if not spread_ok:
                        print(
                            f"[{sym_name}][{now}]"
                            f" SKIP — Spread High")
                        time.sleep(EXECUTE_SCAN)
                        continue

                    # Volume Check
                    if (not vol_ok and
                            int(score) < 10):
                        print(
                            f"[{sym_name}][{now}]"
                            f" SKIP — Volume Weak")
                        time.sleep(EXECUTE_SCAN)
                        continue

                    # Session Check
                    good_sess, sess_name = (
                        is_good_session())
                    if (not good_sess and
                            int(score) < 10):
                        print(
                            f"[{sym_name}][{now}]"
                            f" SKIP — Asian "
                            f"Score={score}<10")
                        time.sleep(EXECUTE_SCAN)
                        continue

                    # Dynamic RR
                    sl_mult, tp_mult, rr_type = (
                        get_dynamic_rr(score))

                    # SL / TP Calculation
                    # ATR 15m use karo SL/TP ke liye
                    if atr_15m > 0:
                        sl_pct = (
                            atr_15m * sl_mult /
                            current_price) * 100
                        tp_pct = (
                            atr_15m * tp_mult /
                            current_price) * 100
                    else:
                        sl_pct = 0.3 * sl_mult
                        tp_pct = 0.3 * tp_mult

                    # Capital Calculation
                    # Total/4 = Per Symbol Capital
                    # 90% of that = Trade Capital
                    capital_used = (
                        capital *
                        (CAPITAL_USE_PCT / 100))

                    # Position Size
                    # 5x Leverage
                    pos_size = (
                        (capital_used * LEVERAGE) /
                        current_price)

                    entry_price     = current_price
                    entry_time      = datetime.now()
                    position        = signal
                    extension_count = 0
                    cooldown_end    = None

                    if signal == "BUY":
                        sl_price = entry_price * (
                            1 - sl_pct / 100)
                        tp_price = entry_price * (
                            1 + tp_pct / 100)
                    else:
                        sl_price = entry_price * (
                            1 + sl_pct / 100)
                        tp_price = entry_price * (
                            1 - tp_pct / 100)

                    # RR Check
                    rr_ok, rr_val = check_rr(
                        entry_price,
                        sl_price,
                        tp_price,
                        signal,
                        min_rr=MIN_RR)

                    if not rr_ok:
                        print(
                            f"[{sym_name}][{now}]"
                            f" SKIP — RR={rr_val}"
                            f" < 1:{MIN_RR}")
                        position     = None
                        entry_price  = 0.0
                        entry_time   = None
                        pos_size     = 0.0
                        sl_price     = 0.0
                        tp_price     = 0.0
                        capital_used = 0.0
                        time.sleep(EXECUTE_SCAN)
                        continue

                    print(
                        f"[{sym_name}] OPENED "
                        f"{position} | "
                        f"Entry={entry_price:.4f} | "
                        f"SL={sl_price:.4f} | "
                        f"TP={tp_price:.4f} | "
                        f"Score={int(score)}/12 | "
                        f"RR=1:{rr_val} | "
                        f"{rr_type} | "
                        f"Cap={capital_used:.2f}$")

                    send_telegram(
                        f"🚀 SCALP OPENED\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"Symbol  : {sym_name}\n"
                        f"Side    : {position}\n"
                        f"Entry   : "
                        f"{entry_price:.4f}\n"
                        f"SL      : "
                        f"{sl_price:.4f}\n"
                        f"TP      : "
                        f"{tp_price:.4f}\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"Capital : "
                        f"{capital_used:.2f} USDT\n"
                        f"Leverage: {LEVERAGE}x\n"
                        f"Exposure: "
                        f"{capital_used * LEVERAGE:.2f} USDT\n"
                        f"Score   : "
                        f"{int(score)}/12\n"
                        f"RR Type : {rr_type}\n"
                        f"RR      : 1:{rr_val}\n"
                        f"ATR 15m : {atr_15m:.4f}\n"
                        f"SL Mult : {sl_mult}x\n"
                        f"TP Mult : {tp_mult}x\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"15m     : {s15m}\n"
                        f"5m      : {s5m}\n"
                        f"BOS 15m : {bos15}\n"
                        f"BOS 5m  : {bos5}\n"
                        f"Volume  : "
                        f"{'OK ✅' if vol_ok else 'WEAK ⚠️'}\n"
                        f"Session : {session}\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"Reason  : "
                        f"{reason[:200]}"
                    )

                else:
                    print(
                        f"[{sym_name}][{now}] "
                        f"WAIT | "
                        f"Score={int(score)}/12 | "
                        f"Signal={signal} | "
                        f"15m={s15m} | "
                        f"5m={s5m} | "
                        f"Price={current_price:.4f}")

            # ══════════════════════════════════════
            #  HOLDING — Status Print
            # ══════════════════════════════════════
            else:
                pnl_now = calc_pnl(
                    position,
                    entry_price,
                    current_price,
                    pos_size)
                held = (
                    datetime.now() -
                    entry_time).seconds
                icon = (
                    "🟢" if pnl_now >= 0
                    else "🔴")
                print(
                    f"[{sym_name}][{now}] "
                    f"{icon} {position} | "
                    f"PnL={pnl_now:+.4f} | "
                    f"Price={current_price:.4f} | "
                    f"Held={held}s | "
                    f"SL={sl_price:.4f} | "
                    f"TP={tp_price:.4f} | "
                    f"Ext={extension_count}/"
                    f"{MAX_EXTENSIONS} | "
                    f"{rr_type}")

        except Exception as e:
            err_msg = str(e)
            print(
                f"[{sym_name}][EXECUTE ERROR] "
                f"{err_msg}")
            if ("429" in err_msg or
                    "Too Many" in err_msg):
                print(
                    f"[{sym_name}][RATE LIMIT] "
                    f"60s wait...")
                time.sleep(60)
            elif ("connection" in err_msg.lower() or
                  "timeout" in err_msg.lower()):
                print(
                    f"[{sym_name}][CONNECTION] "
                    f"Reconnecting...")
                ex = get_exchange()
                time.sleep(10)
            else:
                time.sleep(10)

        time.sleep(EXECUTE_SCAN)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  START — Multi Symbol + Multi Thread
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

if __name__ == "__main__":

    total_max = (
        MAX_HOLD_SECONDS +
        MAX_HOLD_EXTENSION *
        MAX_EXTENSIONS)

    print("=" * 60)
    print("  SCALPING BOT v4.0")
    print("  Multi-Symbol Ultimate SMC Edition")
    print("=" * 60)
    print(f"  Symbols   : "
          f"{', '.join([s.split('/')[0] for s in SYMBOLS])}")
    print(f"  Strategy  : BOS+CHOCH+OB+LIQ+FVG"
          f"+RSI+MA+EqLevels")
    print(f"  Timeframes: 15m+5m+1m (MTF)")
    print(f"  Min Score : {MIN_SCORE}/12")
    print(f"  Total Cap : {TOTAL_CAPITAL} USDT")
    print(f"  Per Symbol: {CAPITAL_PER_SYM:.4f} USDT")
    print(f"  Trade Use : "
          f"{CAPITAL_PER_SYM * CAPITAL_USE_PCT / 100:.4f} USDT")
    print(f"  Leverage  : {LEVERAGE}x")
    print(f"  Exposure  : "
          f"{CAPITAL_PER_SYM * CAPITAL_USE_PCT / 100 * LEVERAGE:.4f} USDT")
    print(f"  Dynamic RR: "
          f"8=1:2 | 10=1:3 | 12=1:4")
    print(f"  Max Hold  : {MAX_HOLD_SECONDS}s + "
          f"{MAX_HOLD_EXTENSION}s x "
          f"{MAX_EXTENSIONS} "
          f"= {total_max // 60} min max")
    print(f"  Asian     : 10/12+ only")
    print(f"  Break Even: "
          f"{BREAK_EVEN_TRIGGER}% trigger")
    print(f"  Trail SL  : "
          f"{TRAIL_TRIGGER_PCT}% trigger")
    print(f"  Min RR    : 1:{MIN_RR}")
    print("=" * 60)

    threads = []

    # ── Flask Server ──────────────────────────
    t_flask = threading.Thread(
        target=run_server,
        name="Flask_Server",
        daemon=True)
    threads.append(t_flask)

    # ── Periodic Update ───────────────────────
    t_update = threading.Thread(
        target=run_periodic_update,
        name="Periodic_Update",
        daemon=True)
    threads.append(t_update)

    # ── Daily Report ──────────────────────────
    t_daily = threading.Thread(
        target=run_daily_report,
        name="Daily_Report",
        daemon=True)
    threads.append(t_daily)

    # ── Decision + Execution — Per Symbol ─────
    for sym in SYMBOLS:
        sym_name = sym.split("/")[0]

        t_decision = threading.Thread(
            target=run_decision_engine_for_symbol,
            args=(sym,),
            name=f"Decision_{sym_name}",
            daemon=True)

        t_execution = threading.Thread(
            target=run_execution_engine_for_symbol,
            args=(sym,),
            name=f"Execution_{sym_name}",
            daemon=True)

        threads.append(t_decision)
        threads.append(t_execution)

    # ── Start All Threads ─────────────────────
    for t in threads:
        t.start()
        time.sleep(0.5)

    print(f"\n[INFO] Total Threads  : "
          f"{len(threads)}")
    print(f"[INFO] Symbol Threads : "
          f"{len(SYMBOLS)} x 2 = "
          f"{len(SYMBOLS) * 2}")
    print(f"[INFO] Flask          : Running")
    print(f"[INFO] Decision       : "
          f"Har {DECISION_SCAN}s per symbol")
    print(f"[INFO] Execution      : "
          f"Har {EXECUTE_SCAN}s per symbol")
    print(f"[INFO] Update         : "
          f"Har {UPDATE_INTERVAL//60} min")
    print(f"[INFO] Min RR         : 1:{MIN_RR}")
    print(f"[INFO] 24/7           : ON ✅")
    print("=" * 60)

    # ── Main Thread Keep Alive ────────────────
    while True:
        time.sleep(60)
