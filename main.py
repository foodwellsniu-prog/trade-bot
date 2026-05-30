"""
ETH Scalping Bot v1.0
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Strategy  : Smart Money Concepts (SMC)
            Market Structure + Liquidity 
            + FVG + Order Block
Symbol    : ETH/USDT
Timeframe : 1 Minute
Capital   : 1000 USDT
Leverage  : 5x
Trade Use : 90%
Min Score : 7/10
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Score System (10 pts):
  Market Structure = 2 pts
  Liquidity        = 3 pts
  FVG              = 3 pts
  Order Block      = 2 pts
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import ccxt
import pandas as pd
import numpy as np
import json
import requests
import threading
import time
import queue
import os
from flask import Flask
from queue import Queue
from datetime import datetime, timezone, timedelta

app = Flask(__name__)

@app.route('/')
def home():
    return "ETH Scalping Bot v1.0 Running!"

def run_server():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  CONFIG
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SYMBOL         = "ETH/USDT:USDT"
API_KEY        = ""
API_SECRET     = ""
BOT_TOKEN      = "8161773850:AAFcWw3UnlSe2TrMooB2uvgZQZUqIW0zW2w"
CHAT_ID        = "7102976298"

# ── Capital ───────────────────────────────
CAPITAL        = 1000.0
CAPITAL_USE    = 90
LEVERAGE       = 5

# ── Score ─────────────────────────────────
MIN_SCORE      = 7

# ── Timing ────────────────────────────────
DECISION_SCAN  = 60    # Har 60s decision
EXECUTE_SCAN   = 5     # Har 5s execution
COOLDOWN_WIN   = 30    # Win ke baad
COOLDOWN_LOSS  = 90    # Loss ke baad
COOLDOWN_2LOSS = 180   # 2 loss ke baad

# ── Max Hold ──────────────────────────────
MAX_HOLD       = 300   # 5 minutes

# ── Dynamic RR ────────────────────────────
RR_CONFIG = {
    7:  {"sl": 1.0, "tp": 1.5},
    8:  {"sl": 1.0, "tp": 2.0},
    9:  {"sl": 0.9, "tp": 2.5},
    10: {"sl": 0.8, "tp": 3.0},
}

# ── Trailing SL ───────────────────────────
TRAIL_TRIGGER  = 0.5   # 0.5% pe activate
TRAIL_DISTANCE = 0.3   # 0.3% distance

# ── Break Even ────────────────────────────
BE_TRIGGER     = 0.3   # 0.3% pe BE

# ── Early TP ──────────────────────────────
EARLY_TP_MIN   = 0.70  # 70%
EARLY_TP_MAX   = 0.90  # 90%

# ── Volume ────────────────────────────────
VOLUME_MULT    = 1.5

# ── Spread ────────────────────────────────
MAX_SPREAD     = 0.05

# ── ATR ───────────────────────────────────
ATR_PERIOD     = 7
ATR_MIN        = 2.0
ATR_MAX        = 80.0

# ── Update ────────────────────────────────
UPDATE_INTERVAL = 1800  # 30 min


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
    "position":        None,
    "entry_price":     0.0,
    "entry_time":      None,
    "sl_price":        0.0,
    "tp_price":        0.0,
    "pos_size":        0.0,
    "capital_used":    0.0,
    "capital":         CAPITAL,
    "last_signal":     "WAIT",
    "last_score":      0,
    "last_price":      0.0,
    "last_session":    "",
    "last_structure":  "RANGE",
    "atr":             0.0,
    "rr_type":         "Default",
    "sl_mult":         1.0,
    "tp_mult":         1.5,
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
#  SIGNAL QUEUE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

signal_queue = Queue(maxsize=1)


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
                    f"Remaining: "
                    f"{int(val - time.time())}s")
                return val
    except Exception:
        pass
    return None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  TRADE HISTORY
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def save_trade(side, entry, exit_p,
               pnl, capital, duration, label):
    try:
        try:
            with open(
                    FILES["history"], "r",
                    encoding="utf-8") as f:
                history = json.load(f)
        except Exception:
            history = []

        history.append({
            "date":     datetime.now().strftime("%d/%m/%Y"),
            "time":     datetime.now().strftime("%H:%M:%S"),
            "symbol":   "ETH",
            "side":     side,
            "entry":    round(entry, 4),
            "exit":     round(exit_p, 4),
            "pnl":      round(pnl, 4),
            "capital":  round(capital, 4),
            "duration": duration,
            "result":   "WIN" if pnl > 0 else "LOSS",
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

    today  = datetime.now().strftime("%d/%m/%Y")
    trades = [t for t in history if t["date"] == today]

    if not trades:
        return None

    total    = len(trades)
    wins     = len([t for t in trades if t["result"] == "WIN"])
    losses   = total - wins
    win_rate = round((wins / total) * 100, 1)
    pnl      = round(sum(t["pnl"] for t in trades), 4)

    return {
        "total":    total,
        "wins":     wins,
        "losses":   losses,
        "win_rate": win_rate,
        "pnl":      pnl,
        "best":     round(max(t["pnl"] for t in trades), 4),
        "worst":    round(min(t["pnl"] for t in trades), 4),
        "capital":  trades[-1]["capital"],
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  EXCHANGE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

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
            print("[INFO] Binance connected ✅")
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
                time.sleep((i+1) * 30)
            else:
                time.sleep(5)
    return None

def safe_fetch_ohlcv(ex, tf, limit):
    for i in range(3):
        try:
            bars = ex.fetch_ohlcv(
                SYMBOL, timeframe=tf, limit=limit)
            return bars
        except Exception as e:
            if "429" in str(e):
                time.sleep((i+1) * 30)
            else:
                time.sleep(5)
    return None

def safe_fetch_orderbook(ex):
    for i in range(3):
        try:
            ob = ex.fetch_order_book(SYMBOL, limit=5)
            return ob
        except Exception as e:
            if "429" in str(e):
                time.sleep((i+1) * 30)
            else:
                time.sleep(5)
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
                    "text":    f"[SCALP] {message}",
                },
                timeout=15)
            if r.status_code == 200:
                return
        except Exception as e:
            print(f"[TELEGRAM] {attempt+1}/3: {e}")
            time.sleep(3)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  CHECKS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def check_spread(ex):
    try:
        ob  = safe_fetch_orderbook(ex)
        if ob is None:
            return True
        bid = ob["bids"][0][0]
        ask = ob["asks"][0][0]
        pct = ((ask - bid) / bid) * 100
        ok  = pct <= MAX_SPREAD
        print(
            f"[SPREAD] {pct:.4f}% "
            f"{'OK ✅' if ok else 'HIGH ❌'}")
        return ok
    except Exception as e:
        print(f"[SPREAD ERROR] {e}")
        return True

def check_volume(df):
    try:
        avg  = df["volume"].tail(20).mean()
        last = df["volume"].iloc[-1]
        if avg == 0:
            return True
        ratio = last / avg
        ok    = ratio >= VOLUME_MULT
        print(
            f"[VOLUME] {ratio:.2f}x "
            f"{'OK ✅' if ok else 'WEAK ❌'}")
        return ok
    except Exception as e:
        print(f"[VOLUME ERROR] {e}")
        return True

def check_atr(atr_val):
    if atr_val < ATR_MIN:
        print(f"[ATR] Too Low: {atr_val:.4f} ❌")
        return False
    if atr_val > ATR_MAX:
        print(f"[ATR] Too High: {atr_val:.4f} ❌")
        return False
    print(f"[ATR] OK: {atr_val:.4f} ✅")
    return True

def is_good_session():
    hour    = datetime.utcnow().hour
    london  = 7  <= hour < 16
    newyork = 12 <= hour < 21
    overlap = 12 <= hour < 16

    if overlap:
        session = "London-NY Overlap 🔥"
    elif london:
        session = "London Session ✅"
    elif newyork:
        session = "New York Session ✅"
    else:
        session = "Asian Session ⚠️"

    is_good = london or newyork
    print(f"[SESSION] {session}")
    return is_good, session


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  INDICATORS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def calc_atr(df):
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
            tr.ewm(span=ATR_PERIOD,
                   adjust=False).mean().iloc[-1])
    except Exception:
        return 0.0

def calc_pnl(side, entry, exit_p, pos_size):
    if side == "BUY":
        return (exit_p - entry) * pos_size
    else:
        return (entry - exit_p) * pos_size

def get_rr(score):
    score = int(score)
    cfg   = RR_CONFIG.get(
        score, RR_CONFIG[7])
    sl    = cfg["sl"]
    tp    = cfg["tp"]
    rtype = {
        7:  "Basic 1:1.5",
        8:  "Good 1:2 ✅",
        9:  "Strong 1:2.5 💪",
        10: "Perfect 1:3 🎯",
    }.get(score, "Basic 1:1.5")
    print(
        f"[RR] Score={score} | "
        f"SL={sl}x | TP={tp}x | {rtype}")
    return sl, tp, rtype


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  MARKET STRUCTURE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def detect_structure(df, swing_bars=2):
    try:
        highs = df["high"].values
        lows  = df["low"].values
        n     = len(highs)
        shs   = []
        sls   = []

        for i in range(swing_bars, n - swing_bars):
            if highs[i] == max(
                    highs[i-swing_bars:i+swing_bars+1]):
                shs.append(highs[i])
            if lows[i] == min(
                    lows[i-swing_bars:i+swing_bars+1]):
                sls.append(lows[i])

        if len(shs) < 2 or len(sls) < 2:
            return "RANGE"

        hh = shs[-1] > shs[-2]
        hl = sls[-1] > sls[-2]
        lh = shs[-1] < shs[-2]
        ll = sls[-1] < sls[-2]

        if hh and hl:
            return "BULL"
        elif lh and ll:
            return "BEAR"
        return "RANGE"

    except Exception:
        return "RANGE"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  BOS / CHOCH
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def detect_bos_choch(df, swing_bars=2):
    try:
        highs  = df["high"].values
        lows   = df["low"].values
        closes = df["close"].values
        n      = len(highs)
        shs    = []
        sls    = []

        for i in range(swing_bars, n - swing_bars):
            if highs[i] == max(
                    highs[i-swing_bars:i+swing_bars+1]):
                shs.append((i, highs[i]))
            if lows[i] == min(
                    lows[i-swing_bars:i+swing_bars+1]):
                sls.append((i, lows[i]))

        if len(shs) < 2 or len(sls) < 2:
            return {"type": "NONE"}

        last_p  = closes[-1]
        last_sh = shs[-1][1]
        last_sl = sls[-1][1]
        prev_sh = shs[-2][1]
        prev_sl = sls[-2][1]

        choch_bull = last_sh < prev_sh and last_p > last_sh
        choch_bear = last_sl > prev_sl and last_p < last_sl
        bos_bull   = last_p > last_sh
        bos_bear   = last_p < last_sl

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

        print(f"[BOS] {result}")
        return {
            "type":    result,
            "last_sh": last_sh,
            "last_sl": last_sl,
        }

    except Exception as e:
        print(f"[BOS ERROR] {e}")
        return {"type": "NONE"}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  LIQUIDITY
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def detect_liquidity(df, lookback=50):
    try:
        recent        = df.tail(lookback).reset_index(drop=True)
        highs         = recent["high"].values
        lows          = recent["low"].values
        closes        = recent["close"].values
        current_price = float(closes[-1])
        n             = len(highs)
        swing_bars    = 2
        bsl           = []
        ssl           = []

        for i in range(swing_bars, n - swing_bars):
            if highs[i] == max(
                    highs[i-swing_bars:i+swing_bars+1]):
                bsl.append(highs[i])
            if lows[i] == min(
                    lows[i-swing_bars:i+swing_bars+1]):
                ssl.append(lows[i])

        # Equal Highs / Lows
        eq_tol      = 0.002
        equal_highs = []
        equal_lows  = []

        for i in range(len(bsl)):
            for j in range(i+1, len(bsl)):
                if abs(bsl[i]-bsl[j])/bsl[i] <= eq_tol:
                    equal_highs.append(
                        round((bsl[i]+bsl[j])/2, 4))

        for i in range(len(ssl)):
            for j in range(i+1, len(ssl)):
                if abs(ssl[i]-ssl[j])/ssl[i] <= eq_tol:
                    equal_lows.append(
                        round((ssl[i]+ssl[j])/2, 4))

        # BSL Sweep (SELL setup)
        bsl_swept   = False
        bsl_quality = "NONE"

        if bsl:
            last_bsl = bsl[-1]
            tol      = last_bsl * 0.002
            r5       = recent.tail(5)
            swept    = any(r5["high"] > last_bsl - tol)
            back     = current_price < last_bsl + tol

            if swept and back:
                bsl_swept = True
                is_eq     = any(
                    abs(last_bsl - eh) /
                    last_bsl <= eq_tol
                    for eh in equal_highs)
                prev      = bsl[:-1]
                if is_eq:
                    bsl_quality = "STRONG"
                elif prev and last_bsl > max(prev):
                    bsl_quality = "NORMAL"
                else:
                    bsl_quality = "WEAK"

        # SSL Sweep (BUY setup)
        ssl_swept   = False
        ssl_quality = "NONE"

        if ssl:
            last_ssl = ssl[-1]
            tol      = last_ssl * 0.002
            r5       = recent.tail(5)
            swept    = any(r5["low"] < last_ssl + tol)
            back     = current_price > last_ssl - tol

            if swept and back:
                ssl_swept = True
                is_eq     = any(
                    abs(last_ssl - el) /
                    last_ssl <= eq_tol
                    for el in equal_lows)
                prev      = ssl[:-1]
                if is_eq:
                    ssl_quality = "STRONG"
                elif prev and last_ssl < min(prev):
                    ssl_quality = "NORMAL"
                else:
                    ssl_quality = "WEAK"

        near_bsl = bsl and abs(
            current_price - bsl[-1]) / current_price <= 0.005
        near_ssl = ssl and abs(
            current_price - ssl[-1]) / current_price <= 0.005

        print(
            f"[LIQ] "
            f"BSL={bsl_swept}({bsl_quality}) | "
            f"SSL={ssl_swept}({ssl_quality})")

        return {
            "bsl_swept":   bsl_swept,
            "ssl_swept":   ssl_swept,
            "bsl_quality": bsl_quality,
            "ssl_quality": ssl_quality,
            "near_bsl":    near_bsl,
            "near_ssl":    near_ssl,
            "equal_highs": equal_highs[-3:],
            "equal_lows":  equal_lows[-3:],
        }

    except Exception as e:
        print(f"[LIQ ERROR] {e}")
        return {
            "bsl_swept":   False,
            "ssl_swept":   False,
            "bsl_quality": "NONE",
            "ssl_quality": "NONE",
            "near_bsl":    False,
            "near_ssl":    False,
            "equal_highs": [],
            "equal_lows":  [],
        }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  FVG
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def detect_fvg(df, lookback=30):
    try:
        fvgs       = []
        recent     = df.tail(lookback).reset_index(drop=True)
        n          = len(recent)
        cur_price  = recent["close"].iloc[-1]
        avg_vol    = recent["volume"].mean()

        for i in range(2, n):
            c1 = recent.iloc[i-2]
            c2 = recent.iloc[i-1]
            c3 = recent.iloc[i]

            # Bullish FVG
            if c1["high"] < c3["low"]:
                gap_top    = c3["low"]
                gap_bottom = c1["high"]
                gap_size   = (
                    (gap_top - gap_bottom) /
                    gap_bottom) * 100

                if gap_size < 0.02:
                    continue

                score = 0
                if gap_size >= 0.1:
                    score += 1
                elif gap_size >= 0.05:
                    score += 0.5

                is_fresh = (i >= n - 8)
                if is_fresh:
                    score += 1

                if c2["volume"] > avg_vol * 1.3:
                    score += 1

                tol     = (gap_top - gap_bottom) * 0.3
                in_zone = (
                    gap_bottom - tol
                    <= cur_price
                    <= gap_top + tol)

                tests = sum(
                    1 for j in range(i+1, n)
                    if gap_bottom - tol
                    <= recent.iloc[j]["low"]
                    <= gap_top + tol)

                if tests >= 3:
                    score -= 1
                score = max(0, score)

                fvgs.append({
                    "type":    "BULL",
                    "top":     round(gap_top, 4),
                    "bottom":  round(gap_bottom, 4),
                    "size":    round(gap_size, 3),
                    "score":   round(score, 1),
                    "fresh":   is_fresh,
                    "retest":  in_zone,
                    "quality": (
                        "STRONG" if score >= 2.5
                        else "GOOD" if score >= 1.5
                        else "WEAK"),
                })

            # Bearish FVG
            elif c1["low"] > c3["high"]:
                gap_top    = c1["low"]
                gap_bottom = c3["high"]
                gap_size   = (
                    (gap_top - gap_bottom) /
                    gap_bottom) * 100

                if gap_size < 0.02:
                    continue

                score = 0
                if gap_size >= 0.1:
                    score += 1
                elif gap_size >= 0.05:
                    score += 0.5

                is_fresh = (i >= n - 8)
                if is_fresh:
                    score += 1

                if c2["volume"] > avg_vol * 1.3:
                    score += 1

                tol     = (gap_top - gap_bottom) * 0.3
                in_zone = (
                    gap_bottom - tol
                    <= cur_price
                    <= gap_top + tol)

                tests = sum(
                    1 for j in range(i+1, n)
                    if gap_bottom - tol
                    <= recent.iloc[j]["high"]
                    <= gap_top + tol)

                if tests >= 3:
                    score -= 1
                score = max(0, score)

                fvgs.append({
                    "type":    "BEAR",
                    "top":     round(gap_top, 4),
                    "bottom":  round(gap_bottom, 4),
                    "size":    round(gap_size, 3),
                    "score":   round(score, 1),
                    "fresh":   is_fresh,
                    "retest":  in_zone,
                    "quality": (
                        "STRONG" if score >= 2.5
                        else "GOOD" if score >= 1.5
                        else "WEAK"),
                })

        bull = [f for f in fvgs if f["type"] == "BULL"]
        bear = [f for f in fvgs if f["type"] == "BEAR"]
        print(
            f"[FVG] Bull={len(bull)} | Bear={len(bear)}")
        return fvgs

    except Exception as e:
        print(f"[FVG ERROR] {e}")
        return []


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  ORDER BLOCK
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def detect_ob(df, lookback=40):
    try:
        recent    = df.tail(lookback).reset_index(drop=True)
        n         = len(recent)
        cur_price = recent["close"].iloc[-1]
        bull_obs  = []
        bear_obs  = []

        for i in range(1, n-1):
            curr = recent.iloc[i]
            next_ = recent.iloc[i+1]
            cb   = abs(curr["close"] - curr["open"])
            nb   = abs(next_["close"] - next_["open"])
            if cb == 0:
                continue

            if (curr["close"] > curr["open"] and
                    next_["close"] < next_["open"] and
                    nb > cb * 1.2):
                top = curr["high"]
                bot = curr["open"]
                tol = (top - bot) * 0.3
                bear_obs.append({
                    "top":         round(top, 4),
                    "bottom":      round(bot, 4),
                    "price_in_ob": (
                        bot - tol
                        <= cur_price
                        <= top + tol),
                    "fresh": (i >= n - 10),
                })

            if (curr["close"] < curr["open"] and
                    next_["close"] > next_["open"] and
                    nb > cb * 1.2):
                top = curr["open"]
                bot = curr["low"]
                tol = (top - bot) * 0.3
                bull_obs.append({
                    "top":         round(top, 4),
                    "bottom":      round(bot, 4),
                    "price_in_ob": (
                        bot - tol
                        <= cur_price
                        <= top + tol),
                    "fresh": (i >= n - 10),
                })

        print(
            f"[OB] Bull={len(bull_obs)} | "
            f"Bear={len(bear_obs)}")
        return {
            "bull_obs": bull_obs[-5:],
            "bear_obs": bear_obs[-5:],
        }

    except Exception as e:
        print(f"[OB ERROR] {e}")
        return {"bull_obs": [], "bear_obs": []}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  SMART MONEY SCORE — 10 Points
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def smart_money_score(structure, liq, fvgs, obs):
    """
    Score System — 10 Points:
    ─────────────────────────
    Market Structure = 2 pts
    Liquidity        = 3 pts
    FVG              = 3 pts
    Order Block      = 2 pts
    ─────────────────────────
    Total            = 10 pts
    Min to Trade     = 7 pts
    """
    points    = 0
    direction = None
    reasons   = []

    # ── Market Structure — 2 pts ──────────
    if structure == "BULL":
        points   += 2
        direction = "BUY"
        reasons.append("Structure BULL (+2) ✅")
    elif structure == "BEAR":
        points   += 2
        direction = "SELL"
        reasons.append("Structure BEAR (+2) ✅")
    else:
        reasons.append("Structure RANGE — Skip ❌")
        return 0, "WAIT", reasons

    # ── Liquidity — 3 pts ─────────────────
    liq_pts = 0
    if direction == "BUY":
        if liq["ssl_swept"]:
            q = liq["ssl_quality"]
            if q == "STRONG":
                liq_pts = 3
                reasons.append("SSL STRONG Sweep (+3) 🔥")
            elif q == "NORMAL":
                liq_pts = 2
                reasons.append("SSL NORMAL Sweep (+2) ✅")
            else:
                liq_pts = 1
                reasons.append("SSL WEAK Sweep (+1) ⚠️")
        elif liq["near_ssl"]:
            reasons.append("Near SSL no sweep (0)")
        else:
            reasons.append("No SSL Sweep (0) ❌")
    else:
        if liq["bsl_swept"]:
            q = liq["bsl_quality"]
            if q == "STRONG":
                liq_pts = 3
                reasons.append("BSL STRONG Sweep (+3) 🔥")
            elif q == "NORMAL":
                liq_pts = 2
                reasons.append("BSL NORMAL Sweep (+2) ✅")
            else:
                liq_pts = 1
                reasons.append("BSL WEAK Sweep (+1) ⚠️")
        elif liq["near_bsl"]:
            reasons.append("Near BSL no sweep (0)")
        else:
            reasons.append("No BSL Sweep (0) ❌")

    points += liq_pts

    # ── FVG — 3 pts ───────────────────────
    fvg_pts = 0
    if direction == "BUY":
        bull_fvgs = [
            f for f in fvgs
            if f["type"] == "BULL" and f["retest"]]
        if bull_fvgs:
            best = sorted(
                bull_fvgs,
                key=lambda x: x["score"],
                reverse=True)[0]
            if best["score"] >= 2.5:
                fvg_pts = 3
                reasons.append(
                    f"BULL FVG STRONG "
                    f"{best['bottom']:.2f}-"
                    f"{best['top']:.2f} (+3) 🔥")
            elif best["score"] >= 1.5:
                fvg_pts = 2
                reasons.append(
                    f"BULL FVG GOOD (+2) ✅")
            else:
                fvg_pts = 1
                reasons.append(
                    f"BULL FVG WEAK (+1) ⚠️")
        else:
            reasons.append("No Bull FVG (0) ❌")
    else:
        bear_fvgs = [
            f for f in fvgs
            if f["type"] == "BEAR" and f["retest"]]
        if bear_fvgs:
            best = sorted(
                bear_fvgs,
                key=lambda x: x["score"],
                reverse=True)[0]
            if best["score"] >= 2.5:
                fvg_pts = 3
                reasons.append(
                    f"BEAR FVG STRONG "
                    f"{best['bottom']:.2f}-"
                    f"{best['top']:.2f} (+3) 🔥")
            elif best["score"] >= 1.5:
                fvg_pts = 2
                reasons.append(
                    f"BEAR FVG GOOD (+2) ✅")
            else:
                fvg_pts = 1
                reasons.append(
                    f"BEAR FVG WEAK (+1) ⚠️")
        else:
            reasons.append("No Bear FVG (0) ❌")

    points += fvg_pts

    # ── Order Block — 2 pts ───────────────
    ob_pts = 0
    if direction == "BUY":
        ob_hit = [
            o for o in obs["bull_obs"]
            if o["price_in_ob"]]
        if ob_hit:
            fresh = [o for o in ob_hit if o["fresh"]]
            if fresh:
                ob_pts = 2
                reasons.append("Bull OB Fresh (+2) ✅")
            else:
                ob_pts = 1
                reasons.append("Bull OB Old (+1) ⚠️")
        else:
            reasons.append("No Bull OB (0)")
    else:
        ob_hit = [
            o for o in obs["bear_obs"]
            if o["price_in_ob"]]
        if ob_hit:
            fresh = [o for o in ob_hit if o["fresh"]]
            if fresh:
                ob_pts = 2
                reasons.append("Bear OB Fresh (+2) ✅")
            else:
                ob_pts = 1
                reasons.append("Bear OB Old (+1) ⚠️")
        else:
            reasons.append("No Bear OB (0)")

    points += ob_pts

    # ── Summary ───────────────────────────
    reasons.append("━━━━━━━━━━━━━━━━━━━━")
    reasons.append(f"Total : {points}/10")
    reasons.append(f"Dir   : {direction}")
    reasons.append(
        f"LIQ={liq_pts}/3 | "
        f"FVG={fvg_pts}/3 | "
        f"OB={ob_pts}/2")

    return points, direction, reasons


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
            score    = st["last_score"]
            entry    = st["entry_price"]
            sl       = st["sl_price"]
            tp       = st["tp_price"]
            psize    = st["pos_size"]
            etime    = st["entry_time"]
            rr_t     = st["rr_type"]
            session  = st["last_session"]
            struct   = st["last_structure"]

            daily = get_daily_stats()

            if (pos is not None and
                    etime is not None and
                    price > 0):
                pnl_now = calc_pnl(
                    pos, entry, price, psize)
                dur = str(
                    datetime.now() - etime
                ).split(".")[0]
                icon = (
                    "🟢" if pnl_now >= 0
                    else "🔴")
                tp_dist = abs(
                    tp - price) / price * 100
                sl_dist = abs(
                    price - sl) / price * 100

                msg = (
                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"  ETH BOT UPDATE\n"
                    f"  {now}\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"{icon} POSITION: {pos}\n"
                    f"Entry  : {entry:.4f}\n"
                    f"Price  : {price:.4f}\n"
                    f"PnL    : {pnl_now:+.4f} USDT\n"
                    f"TP dist: {tp_dist:.2f}%\n"
                    f"SL dist: {sl_dist:.2f}%\n"
                    f"Score  : {score}/10\n"
                    f"RR     : {rr_t}\n"
                    f"Held   : {dur}\n"
                    f"Session: {session}\n"
                    f"Struct : {struct}\n"
                    f"Capital: {capital:.4f} USDT\n")
            else:
                msg = (
                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"  ETH BOT UPDATE\n"
                    f"  {now}\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"⏳ WAITING\n"
                    f"Price  : {price:.4f}\n"
                    f"Score  : {score}/10\n"
                    f"Session: {session}\n"
                    f"Struct : {struct}\n"
                    f"Capital: {capital:.4f} USDT\n")

            if daily:
                msg += (
                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"TODAY\n"
                    f"Trades : {daily['total']}\n"
                    f"Wins   : {daily['wins']} ✅\n"
                    f"Losses : {daily['losses']} ❌\n"
                    f"WR     : {daily['win_rate']}%\n"
                    f"PnL    : {daily['pnl']:+.4f} USDT\n"
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
                timedelta(hours=5, minutes=30))
            now = datetime.now(ist)

            if now.hour == 23 and now.minute == 59:
                daily = get_daily_stats()
                today = now.strftime("%d/%m/%Y")

                if daily:
                    msg = (
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"  DAILY REPORT\n"
                        f"  {today}\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"Symbol  : ETH/USDT\n"
                        f"Trades  : {daily['total']}\n"
                        f"Wins    : {daily['wins']} ✅\n"
                        f"Losses  : {daily['losses']} ❌\n"
                        f"Win Rate: {daily['win_rate']}%\n"
                        f"PnL     : {daily['pnl']:+.4f} USDT\n"
                        f"Best    : +{daily['best']:.4f}\n"
                        f"Worst   : {daily['worst']:.4f}\n"
                        f"Capital : {daily['capital']:.4f} USDT\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━")
                else:
                    msg = (
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"  DAILY REPORT — {today}\n"
                        f"  Aaj koi trade nahi hua\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━")

                send_telegram(msg)
                time.sleep(70)

        except Exception as e:
            print(f"[DAILY ERROR] {e}")

        time.sleep(30)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  DECISION ENGINE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def run_decision_engine():
    exchange = get_exchange()
    print("[DECISION] Started ✅")

    while True:
        try:
            scan_time = datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S")

            good_session, session_name = is_good_session()
            update_state(last_session=session_name)

            # Data Fetch
            bars = safe_fetch_ohlcv(
                exchange, "1m", 100)

            if bars is None:
                print("[DECISION] Fetch fail")
                exchange = get_exchange()
                time.sleep(30)
                continue

            df = pd.DataFrame(
                bars,
                columns=[
                    "time", "open", "high",
                    "low", "close", "volume"])

            if len(df) < 50:
                print("[DECISION] Insufficient data")
                time.sleep(30)
                continue

            df["time"] = pd.to_datetime(
                df["time"], unit="ms")

            cur_price = float(df["close"].iloc[-1])

            # ATR
            atr = calc_atr(df)
            print(f"[ATR] {atr:.4f}")

            # Volume
            vol_ok = check_volume(df)

            # Structure
            structure = detect_structure(df)
            print(f"[STRUCT] {structure}")

            # BOS/CHOCH
            bos = detect_bos_choch(df)

            # Liquidity
            liq = detect_liquidity(df)

            # FVG
            fvgs = detect_fvg(df)

            # Order Block
            obs = detect_ob(df)

            # Score
            points, direction, reasons = (
                smart_money_score(
                    structure, liq, fvgs, obs))

            # Signal
            if points >= MIN_SCORE and direction == "BUY":
                signal = "BUY"
            elif points >= MIN_SCORE and direction == "SELL":
                signal = "SELL"
            else:
                signal = "WAIT"

            # ATR Filter
            if signal != "WAIT":
                if not check_atr(atr):
                    signal = "WAIT"

            # Session Filter
            if signal != "WAIT" and not good_session:
                if points >= 8:
                    print(
                        f"[SESSION] Asian "
                        f"{points}/10 HIGH ✅")
                else:
                    print(
                        f"[SESSION] Asian "
                        f"{points}/10 LOW — Skip ❌")
                    signal = "WAIT"

            # State Update
            update_state(
                last_signal=signal,
                last_score=points,
                last_price=cur_price,
                last_structure=structure,
                atr=atr,
            )

            print(
                f"[{scan_time}] "
                f"Score={points}/10 | "
                f"Signal={signal} | "
                f"Struct={structure} | "
                f"BOS={bos['type']} | "
                f"Price={cur_price:.4f}")

            # Queue mein dalo
            signal_data = {
                "signal":    signal,
                "score":     points,
                "atr":       round(atr, 6),
                "reasons":   reasons,
                "vol_ok":    vol_ok,
                "session":   session_name,
                "price":     cur_price,
                "structure": structure,
                "bos":       bos["type"],
            }

            try:
                signal_queue.get_nowait()
            except queue.Empty:
                pass
            signal_queue.put(signal_data)

            # Log
            try:
                with open(
                        FILES["log"], "r",
                        encoding="utf-8") as f:
                    log = json.load(f)
            except Exception:
                log = []

            log.append({
                "time":      scan_time,
                "signal":    signal,
                "score":     points,
                "atr":       round(atr, 6),
                "price":     cur_price,
                "session":   session_name,
                "vol_ok":    vol_ok,
                "structure": structure,
                "bos":       bos["type"],
            })
            log = log[-3000:]

            with open(
                    FILES["log"], "w",
                    encoding="utf-8") as f:
                json.dump(log, f, indent=2)

        except Exception as e:
            print(f"[DECISION ERROR] {e}")
            if ("connection" in str(e).lower() or
                    "timeout" in str(e).lower()):
                exchange = get_exchange()
            time.sleep(30)

        time.sleep(DECISION_SCAN)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  EXECUTION ENGINE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

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
    sl_mult            = 1.0
    tp_mult            = 1.5
    rr_type            = "Basic 1:1.5"
    signal             = "WAIT"
    score              = 0
    atr                = 0.0
    session            = ""
    vol_ok             = True
    structure          = "RANGE"
    bos                = "NONE"
    reason             = ""

    print("[EXECUTE] Waiting for signal...")
    signal_data = signal_queue.get()
    print("[EXECUTE] Started ✅")

    send_telegram(
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"  ETH BOT v1.0 STARTED\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Symbol  : ETH/USDT\n"
        f"Capital : {capital:.4f} USDT\n"
        f"Use     : "
        f"{capital * CAPITAL_USE / 100:.4f} USDT\n"
        f"Leverage: {LEVERAGE}x\n"
        f"Min Score: {MIN_SCORE}/10\n"
        f"Max Hold : {MAX_HOLD//60} min\n"
        f"Strategy : Structure+LIQ+FVG+OB\n"
        f"━━━━━━━━━━━━━━━━━━━━━━"
    )

    # First signal read
    signal    = signal_data.get("signal",    "WAIT")
    score     = signal_data.get("score",     0)
    atr       = signal_data.get("atr",       0.0)
    session   = signal_data.get("session",   "")
    vol_ok    = signal_data.get("vol_ok",    True)
    structure = signal_data.get("structure", "RANGE")
    bos       = signal_data.get("bos",       "NONE")
    reason    = " | ".join(
        signal_data.get("reasons", []))

    while True:
        try:
            # Latest signal
            try:
                nd        = signal_queue.get_nowait()
                signal    = nd.get("signal",    "WAIT")
                score     = nd.get("score",     0)
                atr       = nd.get("atr",       0.0)
                session   = nd.get("session",   "")
                vol_ok    = nd.get("vol_ok",    True)
                structure = nd.get("structure", "RANGE")
                bos       = nd.get("bos",       "NONE")
                reason    = " | ".join(
                    nd.get("reasons", []))
            except queue.Empty:
                pass

            # Price
            cur_price = get_cached_price(ex)
            if cur_price is None:
                ex = get_exchange()
                time.sleep(EXECUTE_SCAN)
                continue

            now = datetime.now().strftime("%H:%M:%S")

            # State sync
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
                rr_type=rr_type,
            )

            # ══════════════════════════════
            #  MAX HOLD
            # ══════════════════════════════
            if (position is not None and
                    entry_time is not None):
                held = (
                    datetime.now() -
                    entry_time).seconds

                if held >= MAX_HOLD:
                    pnl      = calc_pnl(
                        position, entry_price,
                        cur_price, pos_size)
                    capital += pnl
                    duration = str(
                        datetime.now() -
                        entry_time
                    ).split(".")[0]
                    save_capital(capital)
                    save_trade(
                        position, entry_price,
                        cur_price, pnl,
                        capital, duration,
                        "Max Hold")

                    if pnl >= 0:
                        consecutive_losses = 0
                        cd = COOLDOWN_WIN
                        icon = "✅"
                    else:
                        consecutive_losses += 1
                        cd = (
                            COOLDOWN_2LOSS
                            if consecutive_losses >= 2
                            else COOLDOWN_LOSS)
                        icon = "❌"

                    send_telegram(
                        f"{icon} MAX HOLD CLOSE\n"
                        f"Symbol : ETH\n"
                        f"Side   : {position}\n"
                        f"Entry  : {entry_price:.4f}\n"
                        f"Exit   : {cur_price:.4f}\n"
                        f"PnL    : {pnl:+.4f} USDT\n"
                        f"Capital: {capital:.4f} USDT"
                    )

                    position     = None
                    entry_price  = 0.0
                    entry_time   = None
                    pos_size     = 0.0
                    sl_price     = 0.0
                    tp_price     = 0.0
                    capital_used = 0.0
                    cooldown_end = time.time() + cd
                    save_cooldown(cooldown_end)
                    update_state(
                        position=None,
                        capital_used=0.0,
                        capital=capital)
                    time.sleep(EXECUTE_SCAN)
                    continue

            # ══════════════════════════════
            #  EARLY TP ZONE 70-90%
            # ══════════════════════════════
            if position is not None:
                try:
                    if position == "BUY":
                        tp_range = tp_price - entry_price
                        tp_prog  = (
                            (cur_price - entry_price) /
                            tp_range
                        ) if tp_range != 0 else 0
                    else:
                        tp_range = entry_price - tp_price
                        tp_prog  = (
                            (entry_price - cur_price) /
                            tp_range
                        ) if tp_range != 0 else 0

                    if EARLY_TP_MIN <= tp_prog <= EARLY_TP_MAX:
                        cur_score = get_state("last_score")
                        if cur_score < 9:
                            pnl      = calc_pnl(
                                position, entry_price,
                                cur_price, pos_size)
                            capital += pnl
                            duration = str(
                                datetime.now() -
                                entry_time
                            ).split(".")[0]
                            save_capital(capital)
                            save_trade(
                                position, entry_price,
                                cur_price, pnl,
                                capital, duration,
                                "Early TP")

                            if pnl > 0:
                                consecutive_losses = 0
                                cd = COOLDOWN_WIN
                            else:
                                consecutive_losses += 1
                                cd = COOLDOWN_LOSS

                            send_telegram(
                                f"🎯 EARLY TP EXIT\n"
                                f"Symbol : ETH\n"
                                f"Side   : {position}\n"
                                f"Entry  : {entry_price:.4f}\n"
                                f"Exit   : {cur_price:.4f}\n"
                                f"PnL    : {pnl:+.4f} USDT\n"
                                f"Zone   : {tp_prog*100:.0f}%\n"
                                f"Capital: {capital:.4f} USDT"
                            )

                            position     = None
                            entry_price  = 0.0
                            entry_time   = None
                            pos_size     = 0.0
                            sl_price     = 0.0
                            tp_price     = 0.0
                            capital_used = 0.0
                            cooldown_end = time.time() + cd
                            save_cooldown(cooldown_end)
                            update_state(
                                position=None,
                                capital_used=0.0,
                                capital=capital)
                            time.sleep(EXECUTE_SCAN)
                            continue

                except Exception as e:
                    print(f"[EARLY TP ERROR] {e}")

            # ══════════════════════════════
            #  BREAK EVEN
            # ══════════════════════════════
            if position is not None:
                try:
                    if position == "BUY":
                        be_pct = (
                            (cur_price - entry_price) /
                            entry_price) * 100
                        if (be_pct >= BE_TRIGGER and
                                sl_price < entry_price):
                            sl_price = entry_price
                            update_state(sl_price=sl_price)
                            print(
                                f"[BE] BUY "
                                f"SL={sl_price:.4f} ✅")
                            send_telegram(
                                f"BREAK EVEN ✅\n"
                                f"ETH {position}\n"
                                f"SL → {sl_price:.4f}\n"
                                f"Loss impossible!")
                    elif position == "SELL":
                        be_pct = (
                            (entry_price - cur_price) /
                            entry_price) * 100
                        if (be_pct >= BE_TRIGGER and
                                sl_price > entry_price):
                            sl_price = entry_price
                            update_state(sl_price=sl_price)
                            print(
                                f"[BE] SELL "
                                f"SL={sl_price:.4f} ✅")
                            send_telegram(
                                f"BREAK EVEN ✅\n"
                                f"ETH {position}\n"
                                f"SL → {sl_price:.4f}\n"
                                f"Loss impossible!")
                except Exception as e:
                    print(f"[BE ERROR] {e}")

            # ══════════════════════════════
            #  TRAILING SL
            # ══════════════════════════════
            if position is not None:
                try:
                    if position == "BUY":
                        p_pct = (
                            (cur_price - entry_price) /
                            entry_price) * 100
                        if p_pct >= TRAIL_TRIGGER:
                            new_sl = cur_price * (
                                1 - TRAIL_DISTANCE / 100)
                            if new_sl > sl_price:
                                sl_price = new_sl
                                update_state(
                                    sl_price=sl_price)
                                print(
                                    f"[TRAIL] BUY "
                                    f"SL={sl_price:.4f} ✅")
                    elif position == "SELL":
                        p_pct = (
                            (entry_price - cur_price) /
                            entry_price) * 100
                        if p_pct >= TRAIL_TRIGGER:
                            new_sl = cur_price * (
                                1 + TRAIL_DISTANCE / 100)
                            if new_sl < sl_price:
                                sl_price = new_sl
                                update_state(
                                    sl_price=sl_price)
                                print(
                                    f"[TRAIL] SELL "
                                    f"SL={sl_price:.4f} ✅")
                except Exception as e:
                    print(f"[TRAIL ERROR] {e}")

            # ══════════════════════════════
            #  SL / TP HIT
            # ══════════════════════════════
            if position is not None:
                hit_sl = (
                    (position == "BUY" and
                     cur_price <= sl_price) or
                    (position == "SELL" and
                     cur_price >= sl_price))
                hit_tp = (
                    (position == "BUY" and
                     cur_price >= tp_price) or
                    (position == "SELL" and
                     cur_price <= tp_price))

                if hit_sl or hit_tp:
                    label = (
                        "STOP LOSS ❌"
                        if hit_sl
                        else "TAKE PROFIT ✅")
                    pnl      = calc_pnl(
                        position, entry_price,
                        cur_price, pos_size)
                    capital += pnl
                    duration = str(
                        datetime.now() -
                        entry_time
                    ).split(".")[0]
                    save_capital(capital)
                    save_trade(
                        position, entry_price,
                        cur_price, pnl,
                        capital, duration, label)

                    if pnl > 0:
                        consecutive_losses = 0
                        cd   = COOLDOWN_WIN
                        icon = "🟢"
                    else:
                        consecutive_losses += 1
                        cd = (
                            COOLDOWN_2LOSS
                            if consecutive_losses >= 2
                            else COOLDOWN_LOSS)
                        icon = "🔴"

                    send_telegram(
                        f"{icon} CLOSED — {label}\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"Symbol  : ETH\n"
                        f"Side    : {position}\n"
                        f"Entry   : {entry_price:.4f}\n"
                        f"Exit    : {cur_price:.4f}\n"
                        f"PnL     : {pnl:+.4f} USDT\n"
                        f"Capital : {capital:.4f} USDT\n"
                        f"Score   : {score}/10\n"
                        f"RR      : {rr_type}\n"
                        f"Time    : {duration}\n"
                        f"Session : {session}\n"
                        f"Struct  : {structure}\n"
                        f"BOS     : {bos}\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━"
                    )

                    position     = None
                    entry_price  = 0.0
                    entry_time   = None
                    pos_size     = 0.0
                    sl_price     = 0.0
                    tp_price     = 0.0
                    capital_used = 0.0
                    cooldown_end = time.time() + cd
                    save_cooldown(cooldown_end)
                    update_state(
                        position=None,
                        capital_used=0.0,
                        capital=capital)
                    time.sleep(EXECUTE_SCAN)
                    continue

            # ══════════════════════════════
            #  COOLDOWN
            # ══════════════════════════════
            if (cooldown_end is not None and
                    time.time() < cooldown_end):
                remaining = int(
                    cooldown_end - time.time())
                print(
                    f"[{now}] Cooldown {remaining}s...")
                time.sleep(EXECUTE_SCAN)
                continue

            # ══════════════════════════════
            #  ENTRY
            # ══════════════════════════════
            if position is None:
                if (signal in ["BUY", "SELL"] and
                        int(score) >= MIN_SCORE):

                    # Spread check
                    if not check_spread(ex):
                        time.sleep(EXECUTE_SCAN)
                        continue

                    # Volume check
                    if not vol_ok and int(score) < 9:
                        print("[SKIP] Volume weak")
                        time.sleep(EXECUTE_SCAN)
                        continue

                    # Session check
                    good_sess, _ = is_good_session()
                    if not good_sess and int(score) < 8:
                        print(
                            f"[SKIP] Asian "
                            f"Score={score}<8")
                        time.sleep(EXECUTE_SCAN)
                        continue

                    # RR
                    sl_mult, tp_mult, rr_type = (
                        get_rr(score))

                    # SL/TP
                    if atr > 0:
                        sl_pct = (
                            atr * sl_mult /
                            cur_price) * 100
                        tp_pct = (
                            atr * tp_mult /
                            cur_price) * 100
                    else:
                        sl_pct = 0.3 * sl_mult
                        tp_pct = 0.3 * tp_mult

                    capital_used = (
                        capital * CAPITAL_USE / 100)
                    pos_size     = (
                        (capital_used * LEVERAGE) /
                        cur_price)

                    entry_price = cur_price
                    entry_time  = datetime.now()
                    position    = signal
                    cooldown_end = None

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

                    print(
                        f"[OPENED] {position} | "
                        f"Entry={entry_price:.4f} | "
                        f"SL={sl_price:.4f} | "
                        f"TP={tp_price:.4f} | "
                        f"Score={score}/10")

                    send_telegram(
                        f"🚀 SCALP OPENED\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"Symbol  : ETH\n"
                        f"Side    : {position}\n"
                        f"Entry   : {entry_price:.4f}\n"
                        f"SL      : {sl_price:.4f}\n"
                        f"TP      : {tp_price:.4f}\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"Capital : {capital_used:.2f} USDT\n"
                        f"Leverage: {LEVERAGE}x\n"
                        f"Exposure: "
                        f"{capital_used*LEVERAGE:.2f} USDT\n"
                        f"Score   : {score}/10\n"
                        f"RR      : {rr_type}\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"Struct  : {structure}\n"
                        f"BOS     : {bos}\n"
                        f"Volume  : "
                        f"{'OK ✅' if vol_ok else 'WEAK ⚠️'}\n"
                        f"Session : {session}\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"Reason  : {reason[:200]}"
                    )

                else:
                    print(
                        f"[{now}] WAIT | "
                        f"Score={score}/10 | "
                        f"Signal={signal} | "
                        f"Struct={structure} | "
                        f"Price={cur_price:.4f}")

            # ══════════════════════════════
            #  HOLDING
            # ══════════════════════════════
            else:
                pnl_now = calc_pnl(
                    position, entry_price,
                    cur_price, pos_size)
                held = (
                    datetime.now() -
                    entry_time).seconds
                icon = (
                    "🟢" if pnl_now >= 0
                    else "🔴")
                print(
                    f"[{now}] {icon} {position} | "
                    f"PnL={pnl_now:+.4f} | "
                    f"Price={cur_price:.4f} | "
                    f"SL={sl_price:.4f} | "
                    f"TP={tp_price:.4f} | "
                    f"Held={held}s")

        except Exception as e:
            err = str(e)
            print(f"[EXECUTE ERROR] {err}")
            if "429" in err or "Too Many" in err:
                time.sleep(60)
            elif ("connection" in err.lower() or
                  "timeout" in err.lower()):
                ex = get_exchange()
                time.sleep(10)
            else:
                time.sleep(10)

        time.sleep(EXECUTE_SCAN)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  PRICE CACHE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

price_cache = {
    "price": 0.0,
    "time":  0.0,
    "lock":  threading.Lock()
}

def get_cached_price(ex, max_age=5):
    with price_cache["lock"]:
        if time.time() - price_cache["time"] < max_age:
            return price_cache["price"]
    price = safe_fetch_ticker(ex)
    if price:
        with price_cache["lock"]:
            price_cache["price"] = price
            price_cache["time"]  = time.time()
    return price


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  START
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

if __name__ == "__main__":

    print("=" * 50)
    print("  ETH SCALPING BOT v1.0")
    print("  Smart Money Concepts")
    print("=" * 50)
    print(f"  Symbol   : ETH/USDT")
    print(f"  Capital  : {CAPITAL} USDT")
    print(
        f"  Use      : "
        f"{CAPITAL * CAPITAL_USE / 100} USDT")
    print(f"  Leverage : {LEVERAGE}x")
    print(
        f"  Exposure : "
        f"{CAPITAL * CAPITAL_USE / 100 * LEVERAGE} USDT")
    print(f"  Min Score: {MIN_SCORE}/10")
    print(f"  Max Hold : {MAX_HOLD//60} min")
    print(f"  Strategy : STR+LIQ+FVG+OB")
    print(f"  Score    : 2+3+3+2 = 10 pts")
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
            target=run_decision_engine,
            name="Decision",
            daemon=True),
        threading.Thread(
            target=run_execution_engine,
            name="Execution",
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
