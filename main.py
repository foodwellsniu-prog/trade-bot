"""
SCALPING BOT v3.0 — Ultimate SMC Edition
Strategy  : Smart Money (BOS+CHOCH+OB+LIQ+FVG+RSI+MA)
Sessions  : 24/7
Min Score : 8/12
Capital   : 90% per trade
TP Zone   : 70-90% early exit
Max Hold  : 3 min base + Smart Extension
Dynamic RR: Score Based (1:2 to 1:4)
"""

import threading
import time
import queue
from flask import Flask
from queue import Queue

app = Flask(__name__)

@app.route('/')
def home():
    return "Scalping Bot v3.0 Ultimate SMC Running!"

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

# ─────────────────────────────────────────────
#  CONFIG
# ─────────────────────────────────────────────
SYMBOL           = "ETH/USDT:USDT"
API_KEY          = ""
API_SECRET       = ""

BOT_TOKEN        = "8161773850:AAFcWw3UnlSe2TrMooB2uvgZQZUqIW0zW2w"
CHAT_ID          = "7102976298"

CAPITAL          = 112.4622
CAPITAL_USE_PCT  = 90
LEVERAGE         = 10
MIN_SCORE        = 8
MIN_CONFIDENCE   = int((MIN_SCORE / 12) * 100)

EXECUTE_SCAN     = 8
DECISION_SCAN    = 60
COOLDOWN         = 60
COOLDOWN_WIN     = 30
COOLDOWN_LOSS    = 90
COOLDOWN_2LOSS   = 180

# Max Hold — Smart Logic
MAX_HOLD_SECONDS   = 180
MAX_HOLD_EXTENSION = 140
HOLD_SCORE_MINIMUM = 7
MAX_EXTENSIONS     = 3

ATR_PERIOD       = 7

# Dynamic RR — Score Based (12 point system)
RR_CONFIG = {
    8:  {"sl_mult": 1.0, "tp_mult": 2.0},
    9:  {"sl_mult": 0.9, "tp_mult": 2.5},
    10: {"sl_mult": 0.8, "tp_mult": 3.0},
    11: {"sl_mult": 0.7, "tp_mult": 3.5},
    12: {"sl_mult": 0.6, "tp_mult": 4.0},
}
RR_DEFAULT_SL = 1.0
RR_DEFAULT_TP = 2.0
MIN_RR        = 2.0

# TP Early Exit
TP_EXIT_MIN_PCT   = 0.70
TP_EXIT_MAX_PCT   = 0.90
TP_HOLD_MIN_SCORE = 9

# Trailing SL
TRAIL_TRIGGER_PCT  = 1.0
TRAIL_DISTANCE_PCT = 0.5

# Break Even SL
BREAK_EVEN_TRIGGER = 0.5

# Volume
VOLUME_MULT = 1.5

# Spread
MAX_SPREAD_PCT = 0.05

# Volatility Filter
MIN_ATR_VALUE  = 5.0
MAX_ATR_VALUE  = 50.0

UPDATE_INTERVAL  = 1800

OUTPUT_FILE      = "scalping_output.txt"
LOG_FILE         = "scalping_log.json"
CAPITAL_FILE     = "scalping_capital.txt"
TRADE_HISTORY    = "scalping_history.json"
COOLDOWN_FILE    = "scalping_cooldown.txt"

# ─────────────────────────────────────────────
#  SIGNAL QUEUE
# ─────────────────────────────────────────────
signal_queue = Queue(maxsize=1)
state_lock   = threading.Lock()

# ─────────────────────────────────────────────
#  PRICE CACHE
# ─────────────────────────────────────────────
price_cache = {
    "price": 0.0,
    "time":  0.0,
    "lock":  threading.Lock()
}

def get_cached_price(ex, symbol, max_age=5):
    with price_cache["lock"]:
        if time.time() - price_cache["time"] < max_age:
            return price_cache["price"]
    price = safe_fetch_ticker(ex, symbol)
    if price:
        with price_cache["lock"]:
            price_cache["price"] = price
            price_cache["time"]  = time.time()
    return price


# ─────────────────────────────────────────────
#  CAPITAL
# ─────────────────────────────────────────────
def load_capital():
    try:
        with open(CAPITAL_FILE, "r") as f:
            cap = float(f.read().strip())
            print(f"[CAPITAL] Loaded: {cap} USDT")
            return cap
    except:
        import os
        env_cap = os.environ.get("INITIAL_CAPITAL")
        if env_cap:
            cap = float(env_cap)
            print(f"[CAPITAL] Env: {cap} USDT")
            save_capital(cap)
            return cap
        print(f"[CAPITAL] Default {CAPITAL} USDT")
        return CAPITAL

def save_capital(capital):
    try:
        with open(CAPITAL_FILE, "w") as f:
            f.write(str(round(capital, 6)))
    except Exception as e:
        print(f"[CAPITAL ERROR] {e}")


# ─────────────────────────────────────────────
#  COOLDOWN
# ─────────────────────────────────────────────
def save_cooldown(end_time):
    try:
        with open(COOLDOWN_FILE, "w") as f:
            f.write(str(end_time))
    except Exception as e:
        print(f"[COOLDOWN SAVE ERROR] {e}")

def load_cooldown():
    try:
        with open(COOLDOWN_FILE, "r") as f:
            val = float(f.read().strip())
            if val > time.time():
                print(f"[COOLDOWN] Remaining: "
                      f"{int(val - time.time())}s")
                return val
    except:
        pass
    return None


# ─────────────────────────────────────────────
#  TRADE HISTORY
# ─────────────────────────────────────────────
def save_trade_history(side, entry, exit_price, pnl,
                       capital, duration, label):
    try:
        try:
            with open(TRADE_HISTORY, "r",
                      encoding="utf-8") as f:
                history = json.load(f)
        except:
            history = []
        history.append({
            "date":     datetime.now().strftime(
                "%d/%m/%Y"),
            "time":     datetime.now().strftime(
                "%H:%M:%S"),
            "side":     side,
            "entry":    round(entry, 2),
            "exit":     round(exit_price, 2),
            "pnl":      round(pnl, 4),
            "capital":  round(capital, 4),
            "duration": duration,
            "result":   "WIN" if pnl > 0 else "LOSS",
            "label":    label,
        })
        with open(TRADE_HISTORY, "w",
                  encoding="utf-8") as f:
            json.dump(history, f, indent=2)
    except Exception as e:
        print(f"[HISTORY ERROR] {e}")


def get_daily_stats():
    try:
        with open(TRADE_HISTORY, "r",
                  encoding="utf-8") as f:
            history = json.load(f)
    except:
        return None
    today  = datetime.now().strftime("%d/%m/%Y")
    trades = [t for t in history
              if t["date"] == today]
    if not trades:
        return None
    total     = len(trades)
    wins      = len([t for t in trades
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
        "total": total, "wins": wins,
        "losses": losses,
        "win_rate": win_rate, "pnl": daily_pnl,
        "best": best, "worst": worst,
        "capital": trades[-1]["capital"],
    }


def get_overall_stats():
    try:
        with open(TRADE_HISTORY, "r",
                  encoding="utf-8") as f:
            history = json.load(f)
    except:
        return None
    if not history:
        return None
    total     = len(history)
    wins      = len([t for t in history
                     if t["result"] == "WIN"])
    losses    = total - wins
    win_rate  = round((wins / total) * 100, 1)
    total_pnl = round(
        sum(t["pnl"] for t in history), 4)
    return {
        "total": total, "wins": wins,
        "losses": losses,
        "win_rate": win_rate, "pnl": total_pnl,
        "best":  round(
            max(t["pnl"] for t in history), 4),
        "worst": round(
            min(t["pnl"] for t in history), 4),
        "capital": history[-1]["capital"],
    }


# ─────────────────────────────────────────────
#  EXCHANGE
# ─────────────────────────────────────────────
def get_exchange():
    while True:
        try:
            ex = ccxt.binanceusdm({
                "apiKey":          API_KEY,
                "secret":          API_SECRET,
                "enableRateLimit": True,
                "rateLimit":       100,
            })
            ex.load_markets()
            print("[INFO] Binance connected")
            return ex
        except Exception as e:
            print(f"[RECONNECT] Fail: {e}")
            print("[RECONNECT] 30s retry...")
            time.sleep(30)


def safe_fetch_ticker(ex, symbol, retries=3):
    for i in range(retries):
        try:
            ticker = ex.fetch_ticker(symbol)
            return float(ticker["last"])
        except Exception as e:
            if "429" in str(e) or \
                    "Too Many" in str(e):
                wait = (i + 1) * 30
                print(f"[RATE LIMIT] {wait}s...")
                time.sleep(wait)
            else:
                print(f"[TICKER ERROR] {e}")
                time.sleep(5)
    return None


def safe_fetch_ohlcv(ex, symbol, tf,
                     limit, retries=3):
    for i in range(retries):
        try:
            bars = ex.fetch_ohlcv(
                symbol, timeframe=tf, limit=limit)
            return bars
        except Exception as e:
            if "429" in str(e) or \
                    "Too Many" in str(e):
                wait = (i + 1) * 30
                print(f"[RATE LIMIT] {tf} {wait}s...")
                time.sleep(wait)
            else:
                print(f"[OHLCV ERROR] {tf}: {e}")
                time.sleep(5)
    return None


def safe_fetch_orderbook(ex, symbol, retries=3):
    for i in range(retries):
        try:
            ob = ex.fetch_order_book(
                symbol, limit=5)
            return ob
        except Exception as e:
            if "429" in str(e) or \
                    "Too Many" in str(e):
                wait = (i + 1) * 30
                print(f"[RATE LIMIT] OB {wait}s...")
                time.sleep(wait)
            else:
                print(f"[OB ERROR] {e}")
                time.sleep(5)
    return None


# ─────────────────────────────────────────────
#  TELEGRAM
# ─────────────────────────────────────────────
def send_telegram(message):
    url = (f"https://api.telegram.org/bot"
           f"{BOT_TOKEN}/sendMessage")
    for attempt in range(3):
        try:
            r = requests.post(
                url,
                data={
                    "chat_id": CHAT_ID,
                    "text": f"[SCALP] {message}"
                },
                timeout=15
            )
            if r.status_code == 200:
                return
        except Exception as e:
            print(f"[TELEGRAM] {attempt+1}/3: {e}")
            time.sleep(3)
    print("[TELEGRAM] Failed")


# ─────────────────────────────────────────────
#  SPREAD CHECK
# ─────────────────────────────────────────────
def check_spread(ex, symbol):
    try:
        ob = safe_fetch_orderbook(ex, symbol)
        if ob is None:
            return True
        bid = ob["bids"][0][0]
        ask = ob["asks"][0][0]
        spread_pct = ((ask - bid) / bid) * 100
        if spread_pct > MAX_SPREAD_PCT:
            print(f"[SPREAD] High: {spread_pct:.4f}%")
            return False
        print(f"[SPREAD] OK: {spread_pct:.4f}%")
        return True
    except Exception as e:
        print(f"[SPREAD ERROR] {e}")
        return True


# ─────────────────────────────────────────────
#  VOLUME CHECK
# ─────────────────────────────────────────────
def check_volume(df, mult=VOLUME_MULT):
    try:
        avg_vol  = df["volume"].tail(20).mean()
        last_vol = df["volume"].iloc[-1]
        if avg_vol == 0:
            return True
        ratio = last_vol / avg_vol
        ok    = ratio >= mult
        print(f"[VOLUME] {ratio:.2f}x | "
              f"{'OK' if ok else 'WEAK'}")
        return ok
    except Exception as e:
        print(f"[VOLUME ERROR] {e}")
        return True


# ─────────────────────────────────────────────
#  SESSION FILTER
# ─────────────────────────────────────────────
def is_good_session():
    hour    = datetime.utcnow().hour
    london  = 7 <= hour < 16
    newyork = 12 <= hour < 21
    overlap = 12 <= hour < 16

    if overlap:
        session = "London-NY Overlap (Best)"
    elif london:
        session = "London Session"
    elif newyork:
        session = "New York Session"
    else:
        session = "Asian Session (Weak)"

    is_good = london or newyork
    print(f"[SESSION] {session} | Good: {is_good}")
    return is_good, session


# ─────────────────────────────────────────────
#  ATR
# ─────────────────────────────────────────────
def calc_atr(df, period=7):
    try:
        high  = df["high"]
        low   = df["low"]
        close = df["close"]
        tr1   = high - low
        tr2   = (high - close.shift(1)).abs()
        tr3   = (low  - close.shift(1)).abs()
        tr    = pd.concat(
            [tr1, tr2, tr3], axis=1).max(axis=1)
        return float(
            tr.ewm(span=period,
                   adjust=False).mean().iloc[-1])
    except:
        return 0.0


# ─────────────────────────────────────────────
#  RSI
# ─────────────────────────────────────────────
def calc_rsi(df, period=14):
    try:
        close = df["close"]
        delta = close.diff()
        gain  = delta.where(delta > 0, 0)
        loss  = -delta.where(delta < 0, 0)
        avg_g = gain.ewm(
            span=period, adjust=False).mean()
        avg_l = loss.ewm(
            span=period, adjust=False).mean()
        rs    = avg_g / avg_l
        rsi   = 100 - (100 / (1 + rs))
        val   = float(rsi.iloc[-1])
        print(f"[RSI] Value={val:.2f}")
        return val
    except Exception as e:
        print(f"[RSI ERROR] {e}")
        return 50.0


def check_rsi(rsi_val, direction):
    if direction == "BUY":
        if rsi_val <= 45:
            return True, f"RSI {rsi_val:.1f} BUY ✅"
        return False, f"RSI {rsi_val:.1f} not BUY"
    else:
        if rsi_val >= 55:
            return True, f"RSI {rsi_val:.1f} SELL ✅"
        return False, f"RSI {rsi_val:.1f} not SELL"


# ─────────────────────────────────────────────
#  MOVING AVERAGE
# ─────────────────────────────────────────────
def check_moving_average(df, direction):
    try:
        close = df["close"]
        ema20 = float(close.ewm(
            span=20, adjust=False).mean().iloc[-1])
        ema50 = float(close.ewm(
            span=50, adjust=False).mean().iloc[-1])
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

        print(f"[MA] EMA20={ema20:.2f} | "
              f"EMA50={ema50:.2f} | "
              f"Price={price:.2f} | {status}")
        return ok, status, ema20, ema50

    except Exception as e:
        print(f"[MA ERROR] {e}")
        return True, "ERROR", 0.0, 0.0


# ─────────────────────────────────────────────
#  BOS / CHOCH
# ─────────────────────────────────────────────
def detect_bos_choch(df, swing_bars=2):
    try:
        highs  = df["high"].values
        lows   = df["low"].values
        closes = df["close"].values
        n      = len(highs)

        swing_highs = []
        swing_lows  = []

        for i in range(swing_bars, n - swing_bars):
            if highs[i] == max(
                    highs[i-swing_bars:
                           i+swing_bars+1]):
                swing_highs.append((i, highs[i]))
            if lows[i] == min(
                    lows[i-swing_bars:
                          i+swing_bars+1]):
                swing_lows.append((i, lows[i]))

        if len(swing_highs) < 2 or \
                len(swing_lows) < 2:
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
        choch_bull = (last_sh < prev_sh and
                      last_price > last_sh)
        choch_bear = (last_sl > prev_sl and
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

        print(f"[BOS/CHOCH] {result} | "
              f"SH={last_sh:.2f} | "
              f"SL={last_sl:.2f}")

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


# ─────────────────────────────────────────────
#  EQUAL HIGHS / EQUAL LOWS
# ─────────────────────────────────────────────
def detect_equal_levels(df, tolerance=0.002):
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
                if avg_h > 0 and \
                        diff_h / avg_h <= tolerance:
                    equal_highs.append(
                        round(avg_h, 2))

                diff_l = abs(lows[i] - lows[j])
                avg_l  = (lows[i] + lows[j]) / 2
                if avg_l > 0 and \
                        diff_l / avg_l <= tolerance:
                    equal_lows.append(
                        round(avg_l, 2))

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

        print(f"[EQ LEVELS] "
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


# ─────────────────────────────────────────────
#  MARKET STRUCTURE
# ─────────────────────────────────────────────
def detect_structure(df, swing_bars=2):
    try:
        highs = df["high"].values
        lows  = df["low"].values
        n     = len(highs)
        swing_highs, swing_lows = [], []
        for i in range(swing_bars, n - swing_bars):
            if highs[i] == max(
                    highs[i-swing_bars:
                           i+swing_bars+1]):
                swing_highs.append(highs[i])
            if lows[i] == min(
                    lows[i-swing_bars:
                          i+swing_bars+1]):
                swing_lows.append(lows[i])
        if len(swing_highs) < 2 or \
                len(swing_lows) < 2:
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
    except:
        return "RANGE"


# ─────────────────────────────────────────────
#  ORDER BLOCKS
# ─────────────────────────────────────────────
def detect_order_blocks(df, lookback=40):
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
                tolerance = (ob_top - ob_bottom) * 0.3
                in_zone   = (ob_bottom - tolerance
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
                tolerance = (ob_top - ob_bottom) * 0.3
                in_zone   = (ob_bottom - tolerance
                             <= current_price
                             <= ob_top + tolerance)
                bullish_obs.append({
                    "top":         round(ob_top, 4),
                    "bottom":      round(ob_bottom, 4),
                    "price_in_ob": in_zone,
                    "fresh":       (i >= n - 10),
                    "idx":         i,
                })

        return {
            "bullish_obs": bullish_obs[-5:],
            "bearish_obs": bearish_obs[-5:],
        }
    except:
        return {"bullish_obs": [], "bearish_obs": []}


# ─────────────────────────────────────────────
#  LIQUIDITY
# ─────────────────────────────────────────────
def detect_liquidity(df, lookback=40):
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
                    highs[i-swing_bars:
                           i+swing_bars+1]):
                buy_liq.append(highs[i])
            if lows[i] == min(
                    lows[i-swing_bars:
                          i+swing_bars+1]):
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

        return {
            "buy_swept":   buy_swept,
            "sell_swept":  sell_swept,
            "buy_levels":  buy_liq[-3:]
            if buy_liq else [],
            "sell_levels": sell_liq[-3:]
            if sell_liq else [],
        }
    except:
        return {
            "buy_swept":   False,
            "sell_swept":  False,
            "buy_levels":  [],
            "sell_levels": [],
        }


# ─────────────────────────────────────────────
#  FVG
# ─────────────────────────────────────────────
def detect_fvg(df, lookback=30):
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
                            <= c3["low"] + tolerance),
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
                            <= c1["low"] + tolerance),
                    })
        return fvgs
    except:
        return []


# ─────────────────────────────────────────────
#  RR CHECK
# ─────────────────────────────────────────────
def check_rr(entry, sl, tp, direction,
             min_rr=2.0):
    try:
        if direction == "BUY":
            risk   = entry - sl
            reward = tp - entry
        else:
            risk   = sl - entry
            reward = entry - tp

        if risk <= 0:
            print(f"[RR] Risk invalid: {risk}")
            return False, 0.0

        rr = reward / risk
        ok = rr >= min_rr

        print(f"[RR] Risk={risk:.2f} | "
              f"Reward={reward:.2f} | "
              f"RR=1:{rr:.2f} | "
              f"{'OK ✅' if ok else 'SKIP ❌'}")

        return ok, round(rr, 2)

    except Exception as e:
        print(f"[RR ERROR] {e}")
        return True, 0.0


# ─────────────────────────────────────────────
#  QUICK MARKET SCAN — Loss Hold Decision
# ─────────────────────────────────────────────
def quick_market_scan(ex, symbol, position):
    try:
        score   = 0
        reasons = []

        bars_1m = safe_fetch_ohlcv(
            ex, symbol, "1m", 50)
        bars_5m = safe_fetch_ohlcv(
            ex, symbol, "5m", 50)

        if bars_1m is None or bars_5m is None:
            print("[QUICK SCAN] Data fail")
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
            reasons.append(f"5m {structure_5m} (0)")

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
            reasons.append(f"1m {structure_1m} (0)")

        # Check 3: Order Block (2 pts)
        obs = detect_order_blocks(df_1m)
        if position == "BUY":
            ob_hit = [o for o in obs["bullish_obs"]
                      if o["price_in_ob"]]
            if ob_hit:
                score += 2
                reasons.append("Bullish OB (+2)")
            else:
                reasons.append("No Bullish OB (0)")
        else:
            ob_hit = [o for o in obs["bearish_obs"]
                      if o["price_in_ob"]]
            if ob_hit:
                score += 2
                reasons.append("Bearish OB (+2)")
            else:
                reasons.append("No Bearish OB (0)")

        # Check 4: Volume (2 pts)
        avg_vol   = df_1m["volume"].tail(20).mean()
        last_vol  = df_1m["volume"].iloc[-1]
        vol_ratio = (last_vol / avg_vol
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

        # Check 5: Momentum (2 pts)
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

        reasons.append(f"Quick Score: {score}/10")
        print(f"[QUICK SCAN] Score={score}/10")
        return score, reasons

    except Exception as e:
        print(f"[QUICK SCAN ERROR] {e}")
        return 0, [f"Error: {e}"]


# ─────────────────────────────────────────────
#  SMART MONEY SCORE — 12 Points
# ─────────────────────────────────────────────
def smart_money_score(structure_5m, structure_1m,
                      liq, obs, fvgs,
                      bos_choch=None,
                      rsi_val=50.0,
                      ma_ok=True,
                      eq_levels=None,
                      volume_ok=True):
    points    = 0
    direction = None
    reasons   = []

    # Check 1+2: 5m Structure (2 pts)
    if structure_5m == "BULL":
        points += 2
        direction = "BUY"
        reasons.append("5m BULL (+2)")
    elif structure_5m == "BEAR":
        points += 2
        direction = "SELL"
        reasons.append("5m BEAR (+2)")
    else:
        reasons.append("5m RANGE — skip")
        return 0, "WAIT", reasons

    # Check 3: 1m Structure (1 pt)
    if ((direction == "BUY" and
         structure_1m == "BULL") or
            (direction == "SELL" and
             structure_1m == "BEAR")):
        points += 1
        reasons.append("1m confirms (+1)")
    elif structure_1m == "RANGE":
        reasons.append("1m RANGE (0)")
    else:
        reasons.append("1m opposite (0)")

    # Check 4: BOS/CHOCH (2 pts)
    if bos_choch:
        bos_type = bos_choch.get("type", "NONE")
        if (direction == "BUY" and
                bos_type in ["BOS_BULL",
                             "CHOCH_BULL"]):
            points += 2
            reasons.append(f"{bos_type} (+2)")
        elif (direction == "SELL" and
              bos_type in ["BOS_BEAR",
                           "CHOCH_BEAR"]):
            points += 2
            reasons.append(f"{bos_type} (+2)")
        else:
            reasons.append("No BOS/CHOCH (0)")
    else:
        reasons.append("BOS/CHOCH N/A (0)")

    # Check 5+6: Order Block (2 pts)
    if direction == "BUY":
        ob_hit = [ob for ob in obs["bullish_obs"]
                  if ob["price_in_ob"]]
        if ob_hit:
            best_ob = sorted(
                ob_hit,
                key=lambda x: x["fresh"],
                reverse=True)[0]
            points += 2
            reasons.append(
                f"Bull OB "
                f"{best_ob['bottom']:.2f}-"
                f"{best_ob['top']:.2f} (+2)")
        else:
            reasons.append("No Bull OB (0)")
    else:
        ob_hit = [ob for ob in obs["bearish_obs"]
                  if ob["price_in_ob"]]
        if ob_hit:
            best_ob = sorted(
                ob_hit,
                key=lambda x: x["fresh"],
                reverse=True)[0]
            points += 2
            reasons.append(
                f"Bear OB "
                f"{best_ob['bottom']:.2f}-"
                f"{best_ob['top']:.2f} (+2)")
        else:
            reasons.append("No Bear OB (0)")

    # Check 7: Liquidity (1 pt)
    if direction == "BUY" and liq["sell_swept"]:
        points += 1
        reasons.append("Sell liq swept (+1)")
    elif direction == "SELL" and liq["buy_swept"]:
        points += 1
        reasons.append("Buy liq swept (+1)")
    else:
        reasons.append("No liq sweep (0)")

    # Check 8: Equal Levels (1 pt)
    if eq_levels:
        if (direction == "BUY" and
                eq_levels["near_eq_low"]):
            points += 1
            reasons.append("Near Eq Lows (+1)")
        elif (direction == "SELL" and
              eq_levels["near_eq_high"]):
            points += 1
            reasons.append("Near Eq Highs (+1)")
        else:
            reasons.append("No Eq Level (0)")
    else:
        reasons.append("Eq Level N/A (0)")

    # Check 9: FVG (1 pt)
    if direction == "BUY":
        bull_fvg = [f for f in fvgs
                    if f["type"] == "BULL"
                    and f["retest"]]
        if bull_fvg:
            points += 1
            reasons.append(
                f"Bull FVG "
                f"{bull_fvg[-1]['bottom']:.2f}-"
                f"{bull_fvg[-1]['top']:.2f} (+1)")
        else:
            reasons.append("No Bull FVG (0)")
    else:
        bear_fvg = [f for f in fvgs
                    if f["type"] == "BEAR"
                    and f["retest"]]
        if bear_fvg:
            points += 1
            reasons.append(
                f"Bear FVG "
                f"{bear_fvg[-1]['bottom']:.2f}-"
                f"{bear_fvg[-1]['top']:.2f} (+1)")
        else:
            reasons.append("No Bear FVG (0)")

    # Check 10: RSI (1 pt)
    rsi_ok, rsi_msg = check_rsi(rsi_val, direction)
    if rsi_ok:
        points += 1
        reasons.append(f"{rsi_msg} (+1)")
    else:
        reasons.append(f"{rsi_msg} (0)")

    # Check 11: Moving Average (1 pt)
    if ma_ok:
        points += 1
        reasons.append("MA confirms (+1)")
    else:
        reasons.append("MA against (0)")

    # Volume info
    if not volume_ok:
        reasons.append("Volume weak — caution")
    else:
        reasons.append("Volume OK")

    reasons.append(f"Total: {points}/12")
    return points, direction, reasons


# ─────────────────────────────────────────────
#  PnL CALCULATOR
# ─────────────────────────────────────────────
def calc_pnl(side, entry, exit_price, pos_size):
    if side == "BUY":
        return (exit_price - entry) * pos_size
    else:
        return (entry - exit_price) * pos_size


# ─────────────────────────────────────────────
#  DYNAMIC RR — Score Based
# ─────────────────────────────────────────────
def get_dynamic_rr(score):
    score = int(score)
    if score >= 12:
        sl_mult = RR_CONFIG[12]["sl_mult"]
        tp_mult = RR_CONFIG[12]["tp_mult"]
        rr_type = "Perfect 1:4"
    elif score >= 11:
        sl_mult = RR_CONFIG[11]["sl_mult"]
        tp_mult = RR_CONFIG[11]["tp_mult"]
        rr_type = "Excellent 1:3.5"
    elif score >= 10:
        sl_mult = RR_CONFIG[10]["sl_mult"]
        tp_mult = RR_CONFIG[10]["tp_mult"]
        rr_type = "Strong 1:3"
    elif score >= 9:
        sl_mult = RR_CONFIG[9]["sl_mult"]
        tp_mult = RR_CONFIG[9]["tp_mult"]
        rr_type = "Good 1:2.5"
    elif score >= 8:
        sl_mult = RR_CONFIG[8]["sl_mult"]
        tp_mult = RR_CONFIG[8]["tp_mult"]
        rr_type = "Moderate 1:2"
    else:
        sl_mult = RR_DEFAULT_SL
        tp_mult = RR_DEFAULT_TP
        rr_type = "Default 1:2"
    print(f"[DYNAMIC RR] Score={score}/12 | "
          f"SL={sl_mult}x | TP={tp_mult}x | "
          f"{rr_type}")
    return sl_mult, tp_mult, rr_type


# ─────────────────────────────────────────────
#  SHARED STATE
# ─────────────────────────────────────────────
trade_state = {
    "position":        None,
    "entry_price":     0.0,
    "entry_time":      None,
    "sl_price":        0.0,
    "tp_price":        0.0,
    "pos_size":        0.0,
    "capital_used":    0.0,
    "capital":         CAPITAL,
    "last_signal":     "WAIT",
    "last_conf":       0,
    "last_price":      0.0,
    "last_points":     0,
    "last_tp_zone":    "",
    "last_session":    "",
    "extension_count": 0,
}

def update_state(**kwargs):
    with state_lock:
        for key, val in kwargs.items():
            if key in trade_state:
                trade_state[key] = val

def get_state(key):
    with state_lock:
        return trade_state.get(key)


# ─────────────────────────────────────────────
#  PERIODIC UPDATE
# ─────────────────────────────────────────────
def run_periodic_update():
    time.sleep(UPDATE_INTERVAL)
    while True:
        try:
            now = datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S")
            with state_lock:
                position  = trade_state["position"]
                price     = trade_state["last_price"]
                capital   = trade_state["capital"]
                points    = trade_state["last_points"]
                entry     = trade_state["entry_price"]
                sl        = trade_state["sl_price"]
                tp        = trade_state["tp_price"]
                psize     = trade_state["pos_size"]
                etime     = trade_state["entry_time"]
                tp_zone   = trade_state["last_tp_zone"]
                session   = trade_state["last_session"]
                ext_count = trade_state[
                    "extension_count"]

            if price == 0:
                time.sleep(UPDATE_INTERVAL)
                continue

            if position is not None and \
                    etime is not None:
                pnl  = calc_pnl(
                    position, entry, price, psize)
                dur  = str(
                    datetime.now() -
                    etime).split(".")[0]
                icon = "+" if pnl >= 0 else ""

                if position == "BUY":
                    tp_dist = (
                        (tp - price) / price) * 100
                    sl_dist = (
                        (price - sl) / price) * 100
                else:
                    tp_dist = (
                        (price - tp) / price) * 100
                    sl_dist = (
                        (sl - price) / price) * 100

                tp_line  = (f"\nTP Zone : {tp_zone}"
                            if tp_zone else "")
                ext_line = (
                    f"\nExt     : {ext_count}/"
                    f"{MAX_EXTENSIONS}"
                    if ext_count > 0 else "")

                send_telegram(
                    f"--- SCALP UPDATE ---\n"
                    f"Time    : {now}\n"
                    f"Session : {session}\n"
                    f"Side    : {position}\n"
                    f"Entry   : {entry:.2f}\n"
                    f"Price   : {price:.2f}\n"
                    f"PnL     : "
                    f"{icon}{pnl:.4f} USDT\n"
                    f"Capital : {capital:.4f} USDT\n"
                    f"Duration: {dur}\n"
                    f"--------------------\n"
                    f"TP      : {tp:.2f} "
                    f"({tp_dist:.2f}% door)\n"
                    f"SL      : {sl:.2f} "
                    f"({sl_dist:.2f}% door)\n"
                    f"Score   : {points}/12"
                    f"{tp_line}{ext_line}"
                )
            else:
                send_telegram(
                    f"--- SCALP MARKET ---\n"
                    f"Time    : {now}\n"
                    f"Session : {session}\n"
                    f"Price   : {price:.2f}\n"
                    f"Score   : {points}/12\n"
                    f"Capital : {capital:.4f} USDT\n"
                    f"Status  : Next scalp wait...\n"
                    f"--------------------"
                )
        except Exception as e:
            print(f"[UPDATE ERROR] {e}")
        time.sleep(UPDATE_INTERVAL)


# ─────────────────────────────────────────────
#  DAILY REPORT
# ─────────────────────────────────────────────
def run_daily_report():
    while True:
        try:
            ist = timezone(
                timedelta(hours=5, minutes=30))
            now = datetime.now(ist)
            if now.hour == 23 and now.minute == 59:
                daily   = get_daily_stats()
                overall = get_overall_stats()
                if daily:
                    send_telegram(
                        f"--- SCALP DAILY ---\n"
                        f"Date     : "
                        f"{now.strftime('%d/%m/%Y')}\n"
                        f"Trades   : {daily['total']}\n"
                        f"Win      : {daily['wins']}\n"
                        f"Loss     : {daily['losses']}\n"
                        f"Win Rate : "
                        f"{daily['win_rate']}%\n"
                        f"PnL      : "
                        f"{daily['pnl']:+.4f} USDT\n"
                        f"Capital  : "
                        f"{daily['capital']:.4f} USDT\n"
                        f"Best     : "
                        f"+{daily['best']:.4f} USDT\n"
                        f"Worst    : "
                        f"{daily['worst']:.4f} USDT\n"
                        f"--------------------\n"
                        f"OVERALL:\n"
                        f"Trades   : {overall['total']}\n"
                        f"Win Rate : "
                        f"{overall['win_rate']}%\n"
                        f"Total PnL: "
                        f"{overall['pnl']:+.4f} USDT\n"
                        f"Capital  : "
                        f"{overall['capital']:.4f} USDT\n"
                        f"--------------------"
                    )
                else:
                    send_telegram(
                        f"--- SCALP DAILY ---\n"
                        f"Aaj koi trade nahi hua\n"
                        f"--------------------"
                    )
                time.sleep(70)
        except Exception as e:
            print(f"[DAILY ERROR] {e}")
        time.sleep(30)


# ─────────────────────────────────────────────
#  DECISION ENGINE
# ─────────────────────────────────────────────
def run_decision_engine():
    exchange = get_exchange()
    print("[DECISION] v3.0 Ultimate SMC Started")

    while True:
        try:
            scan_time = datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S")

            good_session, session_name = (
                is_good_session())
            update_state(last_session=session_name)

            bars_5m = safe_fetch_ohlcv(
                exchange, SYMBOL, "5m", 100)
            time.sleep(0.5)
            bars_1m = safe_fetch_ohlcv(
                exchange, SYMBOL, "1m", 100)

            if bars_5m is None or bars_1m is None:
                print("[DECISION] Fetch fail")
                exchange = get_exchange()
                time.sleep(30)
                continue

            df_5m = pd.DataFrame(
                bars_5m,
                columns=["time", "open", "high",
                         "low", "close", "volume"])
            df_1m = pd.DataFrame(
                bars_1m,
                columns=["time", "open", "high",
                         "low", "close", "volume"])

            if len(df_5m) < 50 or len(df_1m) < 50:
                print("[DECISION] Data insufficient")
                time.sleep(30)
                continue

            df_5m["time"] = pd.to_datetime(
                df_5m["time"], unit="ms")
            df_1m["time"] = pd.to_datetime(
                df_1m["time"], unit="ms")

            current_price = float(
                df_1m["close"].iloc[-1])
            atr_1m = calc_atr(df_1m, ATR_PERIOD)
            atr_5m = calc_atr(df_5m, ATR_PERIOD)

            volume_ok    = check_volume(
                df_1m, VOLUME_MULT)
            structure_5m = detect_structure(df_5m)
            structure_1m = detect_structure(df_1m)
            liq          = detect_liquidity(df_1m)
            obs          = detect_order_blocks(df_1m)
            fvgs         = detect_fvg(df_1m)
            bos_choch    = detect_bos_choch(df_1m)
            rsi_val      = calc_rsi(df_1m, 14)
            eq_levels    = detect_equal_levels(df_1m)

            # MA — direction pehle determine karo
            temp_str = structure_5m
            if temp_str == "BULL":
                temp_dir = "BUY"
            elif temp_str == "BEAR":
                temp_dir = "SELL"
            else:
                temp_dir = "BUY"

            ma_ok, ma_status, ema20, ema50 = (
                check_moving_average(
                    df_1m, temp_dir))

            points, direction, reasons = (
                smart_money_score(
                    structure_5m, structure_1m,
                    liq, obs, fvgs,
                    bos_choch=bos_choch,
                    rsi_val=rsi_val,
                    ma_ok=ma_ok,
                    eq_levels=eq_levels,
                    volume_ok=volume_ok,
                ))

            confidence = int((points / 12) * 100)

            if (points >= MIN_SCORE and
                    direction == "BUY"):
                signal = "BUY"
            elif (points >= MIN_SCORE and
                  direction == "SELL"):
                signal = "SELL"
            else:
                signal = "WAIT"

            # Volatility Filter
            if signal != "WAIT":
                if atr_5m < MIN_ATR_VALUE:
                    print(
                        f"[VOL] ATR low: "
                        f"{atr_5m:.2f} — Skip")
                    signal = "WAIT"
                elif atr_5m > MAX_ATR_VALUE:
                    print(
                        f"[VOL] ATR high: "
                        f"{atr_5m:.2f} — Skip")
                    signal = "WAIT"
                else:
                    print(
                        f"[VOL] ATR OK: "
                        f"{atr_5m:.2f} ✅")

            # Session Filter
            if not good_session and \
                    signal != "WAIT":
                if points >= 10:
                    print(
                        f"[SESSION] {session_name}"
                        f" Score {points}/12 HIGH"
                        f" — Asian allowed ✅")
                else:
                    print(
                        f"[SESSION] {session_name}"
                        f" Score {points}/12 LOW"
                        f" — Skip ❌")
                    signal = "WAIT"

            print(
                f"[SCALP] {scan_time} | "
                f"{points}/12 | {signal} | "
                f"ATR={atr_5m:.2f} | "
                f"RSI={rsi_val:.1f} | "
                f"Price={current_price:.2f} | "
                f"{session_name}")

            signal_data = {
                "signal":     signal,
                "confidence": confidence,
                "score":      points,
                "atr_1m":     round(atr_1m, 4),
                "atr_5m":     round(atr_5m, 4),
                "rsi":        round(rsi_val, 2),
                "ma_status":  ma_status,
                "time":       scan_time,
                "reasons":    reasons,
                "volume_ok":  volume_ok,
                "session":    session_name,
                "price":      current_price,
            }

            try:
                signal_queue.get_nowait()
            except queue.Empty:
                pass
            signal_queue.put(signal_data)

            update_state(
                last_signal=signal,
                last_conf=confidence,
                last_points=points,
                last_price=current_price,
            )

            try:
                with open(LOG_FILE, "r",
                          encoding="utf-8") as f:
                    log = json.load(f)
            except:
                log = []
            log.append({
                "time":      scan_time,
                "signal":    signal,
                "points":    points,
                "atr_5m":    round(atr_5m, 4),
                "rsi":       round(rsi_val, 2),
                "price":     current_price,
                "session":   session_name,
                "volume_ok": volume_ok,
            })
            log = log[-3000:]
            with open(LOG_FILE, "w",
                      encoding="utf-8") as f:
                json.dump(log, f, indent=2)

        except Exception as e:
            print(f"[DECISION ERROR] {e}")
            if ("connection" in str(e).lower() or
                    "timeout" in str(e).lower()):
                exchange = get_exchange()
            time.sleep(30)

        time.sleep(DECISION_SCAN)


# ─────────────────────────────────────────────
#  EXECUTION ENGINE
# ─────────────────────────────────────────────
def run_execution_engine():
    ex                 = get_exchange()
    capital            = load_capital()
    position           = None
    entry_price        = 0.0
    entry_time         = None
    pos_size           = 0.0
    sl_price           = 0.0
    tp_price           = 0.0
    capital_used       = 0.0
    cooldown_end       = load_cooldown()
    consecutive_losses = 0
    extension_count    = 0
    sl_mult            = RR_DEFAULT_SL
    tp_mult            = RR_DEFAULT_TP
    rr_type            = "Default"

    print("[EXECUTE] Waiting for first signal...")
    signal_data = signal_queue.get()
    print("[EXECUTE] v3.0 Ultimate SMC Started!")

    send_telegram(
        f"SCALPING BOT v3.0 STARTED\n"
        f"Capital  : {capital:.4f} USDT\n"
        f"Symbol   : {SYMBOL}\n"
        f"Mode     : Paper Trading\n"
        f"Leverage : {LEVERAGE}x\n"
        f"Capital% : {CAPITAL_USE_PCT}%\n"
        f"Min Score: {MIN_SCORE}/12\n"
        f"Max Hold : {MAX_HOLD_SECONDS//60} min\n"
        f"Ext      : {MAX_HOLD_EXTENSION}s "
        f"x {MAX_EXTENSIONS}\n"
        f"Hold Min : {HOLD_SCORE_MINIMUM}/10\n"
        f"TP Zone  : {int(TP_EXIT_MIN_PCT*100)}-"
        f"{int(TP_EXIT_MAX_PCT*100)}%\n"
        f"Dynamic RR: 8=1:2 to 12=1:4\n"
        f"Asian    : 10/12+ only\n"
        f"ATR Range: {MIN_ATR_VALUE}-"
        f"{MAX_ATR_VALUE}\n"
        f"Break Even: {BREAK_EVEN_TRIGGER}%\n"
        f"Trail SL : {TRAIL_TRIGGER_PCT}% trigger"
    )

    signal  = signal_data.get("signal", "WAIT")
    score   = signal_data.get("score", 0)
    atr_5m  = signal_data.get("atr_5m", 0.0)
    reason  = " | ".join(
        signal_data.get("reasons", []))
    session = signal_data.get("session", "")
    vol_ok  = signal_data.get("volume_ok", True)

    while True:
        try:
            # Queue se latest signal
            try:
                new_data = signal_queue.get_nowait()
                signal   = new_data.get(
                    "signal", "WAIT")
                score    = new_data.get("score", 0)
                atr_5m   = new_data.get(
                    "atr_5m", 0.0)
                reason   = " | ".join(
                    new_data.get("reasons", []))
                session  = new_data.get(
                    "session", "")
                vol_ok   = new_data.get(
                    "volume_ok", True)
            except queue.Empty:
                pass

            current_price = get_cached_price(
                ex, SYMBOL)
            if current_price is None:
                print("[EXECUTE] Price fail")
                ex = get_exchange()
                time.sleep(EXECUTE_SCAN)
                continue

            now = datetime.now().strftime("%H:%M:%S")

            update_state(
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
            )

            # ── Smart Max Hold ────────────────────
            if (position is not None and
                    entry_time is not None):
                held_secs = (
                    datetime.now() -
                    entry_time).seconds

                if held_secs >= MAX_HOLD_SECONDS:
                    pnl_now = calc_pnl(
                        position, entry_price,
                        current_price, pos_size)

                    if pnl_now >= 0:
                        pnl      = pnl_now
                        capital += pnl
                        duration = str(
                            datetime.now() -
                            entry_time
                        ).split(".")[0]
                        save_capital(capital)
                        save_trade_history(
                            position, entry_price,
                            current_price, pnl,
                            capital, duration,
                            "Max Hold — Profit")
                        consecutive_losses = 0
                        print(
                            f"[MAX HOLD] Profit "
                            f"PnL={pnl:+.4f}")
                        send_telegram(
                            f"SCALP CLOSED — "
                            f"Max Hold\n"
                            f"Side    : {position}\n"
                            f"Entry   : "
                            f"{entry_price:.2f}\n"
                            f"Exit    : "
                            f"{current_price:.2f}\n"
                            f"PnL     : "
                            f"{pnl:+.4f} USDT\n"
                            f"Capital : "
                            f"{capital:.4f} USDT\n"
                            f"Reason  : Profit ✅"
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
                        save_cooldown(cooldown_end)
                        update_state(
                            position=None,
                            capital_used=0.0,
                            capital=capital,
                            last_tp_zone="",
                            extension_count=0)
                        time.sleep(EXECUTE_SCAN)
                        continue

                    else:
                        if (extension_count >=
                                MAX_EXTENSIONS):
                            pnl      = pnl_now
                            capital += pnl
                            duration = str(
                                datetime.now() -
                                entry_time
                            ).split(".")[0]
                            save_capital(capital)
                            save_trade_history(
                                position, entry_price,
                                current_price, pnl,
                                capital, duration,
                                "Max Hold — Ext Over")
                            consecutive_losses += 1
                            smart_cd = (
                                COOLDOWN_2LOSS
                                if consecutive_losses
                                >= 2
                                else COOLDOWN_LOSS)
                            print(
                                f"[MAX HOLD] "
                                f"Force Close "
                                f"PnL={pnl:+.4f}")
                            send_telegram(
                                f"SCALP CLOSED — "
                                f"Force\n"
                                f"Side    : "
                                f"{position}\n"
                                f"Entry   : "
                                f"{entry_price:.2f}\n"
                                f"Exit    : "
                                f"{current_price:.2f}\n"
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
                                cooldown_end)
                            update_state(
                                position=None,
                                capital_used=0.0,
                                capital=capital,
                                last_tp_zone="",
                                extension_count=0)
                            time.sleep(EXECUTE_SCAN)
                            continue

                        print(
                            f"[MAX HOLD] Loss "
                            f"PnL={pnl_now:+.4f}"
                            f" — Scanning...")
                        send_telegram(
                            f"MAX HOLD SCANNING\n"
                            f"Side : {position}\n"
                            f"PnL  : "
                            f"{pnl_now:+.4f} USDT\n"
                            f"Ext  : "
                            f"{extension_count}/"
                            f"{MAX_EXTENSIONS}"
                        )

                        q_score, q_reasons = (
                            quick_market_scan(
                                ex, SYMBOL,
                                position))

                        if (q_score >=
                                HOLD_SCORE_MINIMUM):
                            extension_count += 1
                            update_state(
                                extension_count=
                                extension_count)
                            print(
                                f"[MAX HOLD] "
                                f"Score={q_score}/10"
                                f" STRONG — Hold "
                                f"{extension_count}/"
                                f"{MAX_EXTENSIONS}")
                            send_telegram(
                                f"MAX HOLD "
                                f"EXTENDED ⏳\n"
                                f"Side  : "
                                f"{position}\n"
                                f"PnL   : "
                                f"{pnl_now:+.4f}\n"
                                f"Score : "
                                f"{q_score}/10\n"
                                f"Ext   : "
                                f"{extension_count}/"
                                f"{MAX_EXTENSIONS}\n"
                                f"Reason: "
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
                            save_capital(capital)
                            save_trade_history(
                                position, entry_price,
                                current_price, pnl,
                                capital, duration,
                                "Max Hold — Weak")
                            consecutive_losses += 1
                            smart_cd = (
                                COOLDOWN_2LOSS
                                if consecutive_losses
                                >= 2
                                else COOLDOWN_LOSS)
                            print(
                                f"[MAX HOLD] "
                                f"Score={q_score}/10"
                                f" WEAK "
                                f"PnL={pnl:+.4f}")
                            send_telegram(
                                f"SCALP CLOSED "
                                f"— Weak\n"
                                f"Side    : "
                                f"{position}\n"
                                f"Entry   : "
                                f"{entry_price:.2f}\n"
                                f"Exit    : "
                                f"{current_price:.2f}\n"
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
                                cooldown_end)
                            update_state(
                                position=None,
                                capital_used=0.0,
                                capital=capital,
                                last_tp_zone="",
                                extension_count=0)
                            time.sleep(EXECUTE_SCAN)
                            continue

            # ── TP Zone 70-90% ────────────────────
            if position is not None:
                try:
                    if position == "BUY":
                        tp_range = (tp_price -
                                    entry_price)
                        tp_prog  = (
                            (current_price -
                             entry_price) /
                            tp_range
                        ) if tp_range != 0 else 0
                    else:
                        tp_range = (entry_price -
                                    tp_price)
                        tp_prog  = (
                            (entry_price -
                             current_price) /
                            tp_range
                        ) if tp_range != 0 else 0

                    if (TP_EXIT_MIN_PCT <= tp_prog
                            <= TP_EXIT_MAX_PCT):
                        pts = get_state("last_points")
                        if pts < TP_HOLD_MIN_SCORE:
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
                            save_capital(capital)
                            save_trade_history(
                                position,
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
                                f"[EARLY EXIT] "
                                f"{tp_prog*100:.0f}%"
                                f" PnL={pnl:+.4f}")
                            send_telegram(
                                f"SCALP EARLY EXIT\n"
                                f"Side  : {position}\n"
                                f"Entry : "
                                f"{entry_price:.2f}\n"
                                f"Exit  : "
                                f"{current_price:.2f}\n"
                                f"PnL   : "
                                f"{pnl:+.4f} USDT\n"
                                f"Zone  : "
                                f"{tp_prog*100:.0f}%\n"
                                f"Score : {pts}/12"
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
                                cooldown_end)
                            update_state(
                                position=None,
                                capital_used=0.0,
                                capital=capital,
                                last_tp_zone="",
                                extension_count=0)
                            time.sleep(EXECUTE_SCAN)
                            continue
                        else:
                            update_state(
                                last_tp_zone=(
                                    f"TP "
                                    f"{tp_prog*100:.0f}%"
                                    f" | Score="
                                    f"{pts}/12 strong"))
                    else:
                        update_state(last_tp_zone="")
                except Exception as e:
                    print(f"[TP ZONE ERROR] {e}")

            # ── Break Even SL ─────────────────────
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
                                sl_price=sl_price)
                            print(
                                f"[BE] BUY SL="
                                f"{sl_price:.2f} ✅")
                            send_telegram(
                                f"BREAK EVEN SET ✅\n"
                                f"Side  : {position}\n"
                                f"Entry : "
                                f"{entry_price:.2f}\n"
                                f"SL    : "
                                f"{sl_price:.2f}\n"
                                f"= Loss impossible!"
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
                                sl_price=sl_price)
                            print(
                                f"[BE] SELL SL="
                                f"{sl_price:.2f} ✅")
                            send_telegram(
                                f"BREAK EVEN SET ✅\n"
                                f"Side  : {position}\n"
                                f"Entry : "
                                f"{entry_price:.2f}\n"
                                f"SL    : "
                                f"{sl_price:.2f}\n"
                                f"= Loss impossible!"
                            )
                except Exception as e:
                    print(f"[BE ERROR] {e}")

            # ── Trailing SL ───────────────────────
            if position is not None:
                try:
                    if position == "BUY":
                        p_pct = (
                            (current_price -
                             entry_price) /
                            entry_price) * 100
                        if p_pct >= TRAIL_TRIGGER_PCT:
                            new_sl = (
                                current_price *
                                (1 -
                                 TRAIL_DISTANCE_PCT /
                                 100))
                            if new_sl > sl_price:
                                sl_price = new_sl
                                update_state(
                                    sl_price=sl_price)
                                print(
                                    f"[TRAIL] BUY "
                                    f"{sl_price:.2f}")
                    elif position == "SELL":
                        p_pct = (
                            (entry_price -
                             current_price) /
                            entry_price) * 100
                        if p_pct >= TRAIL_TRIGGER_PCT:
                            new_sl = (
                                current_price *
                                (1 +
                                 TRAIL_DISTANCE_PCT /
                                 100))
                            if new_sl < sl_price:
                                sl_price = new_sl
                                update_state(
                                    sl_price=sl_price)
                                print(
                                    f"[TRAIL] SELL "
                                    f"{sl_price:.2f}")
                except Exception as e:
                    print(f"[TRAIL ERROR] {e}")

            # ── SL/TP Check ───────────────────────
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
                    label    = ("STOP LOSS"
                                if hit_sl
                                else "TAKE PROFIT")
                    pnl      = calc_pnl(
                        position, entry_price,
                        current_price, pos_size)
                    capital += pnl
                    duration = str(
                        datetime.now() -
                        entry_time
                    ).split(".")[0]
                    save_capital(capital)
                    save_trade_history(
                        position, entry_price,
                        current_price, pnl,
                        capital, duration, label)

                    if pnl > 0:
                        consecutive_losses = 0
                        smart_cd  = COOLDOWN_WIN
                        cd_reason = "Win ✅"
                    else:
                        consecutive_losses += 1
                        if consecutive_losses >= 2:
                            smart_cd  = COOLDOWN_2LOSS
                            cd_reason = (
                                f"{consecutive_losses}"
                                f" Loss streak!")
                        else:
                            smart_cd  = COOLDOWN_LOSS
                            cd_reason = "Loss"

                    print(
                        f"[SCALP] {label} | "
                        f"PnL={pnl:+.4f} | "
                        f"CD={smart_cd}s")
                    send_telegram(
                        f"SCALP CLOSED — {label}\n"
                        f"Side    : {position}\n"
                        f"Entry   : {entry_price:.2f}\n"
                        f"Exit    : "
                        f"{current_price:.2f}\n"
                        f"PnL     : {pnl:+.4f} USDT\n"
                        f"Capital : {capital:.4f} USDT\n"
                        f"RR Type : {rr_type}\n"
                        f"Time    : {duration}\n"
                        f"Cooldown: {smart_cd}s "
                        f"({cd_reason})"
                    )
                    position        = None
                    entry_price     = 0.0
                    entry_time      = None
                    pos_size        = 0.0
                    sl_price        = 0.0
                    tp_price        = 0.0
                    capital_used    = 0.0
                    extension_count = 0
                    cooldown_end    = (time.time() +
                                      smart_cd)
                    save_cooldown(cooldown_end)
                    update_state(
                        position=None,
                        capital_used=0.0,
                        capital=capital,
                        last_tp_zone="",
                        extension_count=0)
                    time.sleep(EXECUTE_SCAN)
                    continue

            # ── Cooldown ──────────────────────────
            if (cooldown_end is not None and
                    time.time() < cooldown_end):
                remaining = int(
                    cooldown_end - time.time())
                print(
                    f"[{now}] Cooldown {remaining}s")
                time.sleep(EXECUTE_SCAN)
                continue

            # ── Entry Check ───────────────────────
            if position is None:
                if (signal in ["BUY", "SELL"] and
                        int(score) >= MIN_SCORE):

                    # Spread check
                    spread_ok = check_spread(
                        ex, SYMBOL)
                    if not spread_ok:
                        print(
                            f"[{now}] SKIP — spread")
                        time.sleep(EXECUTE_SCAN)
                        continue

                    # Volume check
                    if not vol_ok and int(score) < 10:
                        print(
                            f"[{now}] SKIP — "
                            f"volume weak")
                        time.sleep(EXECUTE_SCAN)
                        continue

                    # Asian session check
                    good_sess, sess_name = (
                        is_good_session())
                    if (not good_sess and
                            int(score) < 10):
                        print(
                            f"[{now}] SKIP — Asian "
                            f"score={score} < 10")
                        time.sleep(EXECUTE_SCAN)
                        continue

                    # Dynamic RR
                    sl_mult, tp_mult, rr_type = (
                        get_dynamic_rr(score))

                    if atr_5m > 0:
                        sl_pct = (
                            atr_5m * sl_mult /
                            current_price) * 100
                        tp_pct = (
                            atr_5m * tp_mult /
                            current_price) * 100
                    else:
                        sl_pct = 0.3 * sl_mult
                        tp_pct = 0.3 * tp_mult

                    capital_used = (
                        capital *
                        (CAPITAL_USE_PCT / 100))
                    pos_size     = (
                        (capital_used * LEVERAGE) /
                        current_price)
                    entry_price  = current_price
                    entry_time   = datetime.now()
                    position     = signal
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
                            f"[{now}] SKIP — "
                            f"RR={rr_val} < "
                            f"1:{MIN_RR}")
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
                        f"[SCALP] OPENED "
                        f"{position} | "
                        f"Entry={entry_price:.2f} | "
                        f"SL={sl_price:.2f} | "
                        f"TP={tp_price:.2f} | "
                        f"Score={int(score)}/12 | "
                        f"RR=1:{rr_val} | "
                        f"{rr_type}")
                    send_telegram(
                        f"SCALP OPENED\n"
                        f"Side    : {position}\n"
                        f"Entry   : {entry_price:.2f}\n"
                        f"SL      : {sl_price:.2f}\n"
                        f"TP      : {tp_price:.2f}\n"
                        f"ATR 5m  : {atr_5m:.2f}\n"
                        f"Capital : {capital_used:.2f}\n"
                        f"Score   : {int(score)}/12\n"
                        f"RR Type : {rr_type}\n"
                        f"RR      : 1:{rr_val}\n"
                        f"SL Mult : {sl_mult}x ATR\n"
                        f"TP Mult : {tp_mult}x ATR\n"
                        f"Volume  : "
                        f"{'OK' if vol_ok else 'WEAK'}\n"
                        f"Session : {session}\n"
                        f"Reason  : {reason[:200]}"
                    )
                else:
                    print(
                        f"[{now}] WAIT | "
                        f"Score={int(score)}/12 | "
                        f"Price={current_price:.2f}")

            # ── Holding ───────────────────────────
            else:
                pnl_now = calc_pnl(
                    position, entry_price,
                    current_price, pos_size)
                held = (datetime.now() -
                        entry_time).seconds
                print(
                    f"[{now}] {position} | "
                    f"PnL={pnl_now:+.4f} | "
                    f"Price={current_price:.2f} | "
                    f"Held={held}s | "
                    f"Ext={extension_count}/"
                    f"{MAX_EXTENSIONS} | "
                    f"{rr_type}")

        except Exception as e:
            err_msg = str(e)
            print(f"[EXECUTE ERROR] {err_msg}")
            if ("429" in err_msg or
                    "Too Many" in err_msg):
                print("[RATE LIMIT] 60s...")
                time.sleep(60)
            elif ("connection" in err_msg.lower() or
                  "timeout" in err_msg.lower()):
                print("[CONNECTION] Reconnect...")
                ex = get_exchange()
                time.sleep(10)
            else:
                time.sleep(10)

        time.sleep(EXECUTE_SCAN)


# ─────────────────────────────────────────────
#  START
# ─────────────────────────────────────────────
if __name__ == "__main__":
    total_max = (MAX_HOLD_SECONDS +
                 MAX_HOLD_EXTENSION *
                 MAX_EXTENSIONS)
    print("=" * 55)
    print("  SCALPING BOT v3.0 — Ultimate SMC")
    print("  Strategy  : BOS+CHOCH+OB+LIQ+FVG")
    print("              +RSI+MA+EqLevels")
    print("  Min Score : 8/12")
    print("  Capital   : 90%")
    print("  Dynamic RR: 8=1:2 | 10=1:3 | 12=1:4")
    print(f"  Max Hold  : {MAX_HOLD_SECONDS}s + "
          f"{MAX_HOLD_EXTENSION}s x "
          f"{MAX_EXTENSIONS} "
          f"= {total_max // 60} min max")
    print("  Asian     : 10/12+ only")
    print("  Break Even: 0.5% trigger")
    print("  Min RR    : 1:2")
    print("=" * 55)

    t1 = threading.Thread(
        target=run_server, name="Flask")
    t2 = threading.Thread(
        target=run_decision_engine, name="Decision")
    t3 = threading.Thread(
        target=run_execution_engine, name="Execution")
    t4 = threading.Thread(
        target=run_periodic_update, name="Update")
    t5 = threading.Thread(
        target=run_daily_report, name="Daily")

    for t in [t1, t2, t3, t4, t5]:
        t.daemon = True
        t.start()

    print("[INFO] All engines started!")
    print(f"[INFO] Flask    : port dynamic")
    print(f"[INFO] Decision : har {DECISION_SCAN}s")
    print(f"[INFO] Execute  : har {EXECUTE_SCAN}s")
    print(f"[INFO] Score    : 12 point system")
    print(f"[INFO] Min RR   : 1:{MIN_RR}")
    print(f"[INFO] 24/7     : ON")

    while True:
        time.sleep(60)
