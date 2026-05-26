"""
SCALPING BOT v3.0 — Smart Max Hold Edition
Strategy  : Smart Money (OB + Liquidity + FVG)
Sessions  : 24/7
Min Score : 6/8
Capital   : 90% per trade
TP Zone   : 70-90% early exit
Max Hold  : 3 min base + Smart Extension
"""

import threading
import time
import queue
from flask import Flask
from queue import Queue

app = Flask(__name__)

@app.route('/')
def home():
    return "Scalping Bot v3.0 Smart Max Hold Running!"

def run_server():
    app.run(host='0.0.0.0', port=8081)


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

CAPITAL          = 100.0
CAPITAL_USE_PCT  = 90
LEVERAGE         = 10
MIN_SCORE        = 6
MIN_CONFIDENCE   = int((MIN_SCORE / 8) * 100)

EXECUTE_SCAN     = 8
DECISION_SCAN    = 60
COOLDOWN         = 60

# Max Hold — Smart Logic
# Max Hold — Smart Logic
MAX_HOLD_SECONDS   = 180    # 3 min base
MAX_HOLD_EXTENSION = 140    # 2m20s extra per extension
HOLD_SCORE_MINIMUM = 7      # 7/10 = hold karo
MAX_EXTENSIONS     = 3      # Max 3 baar extend
                             # Total = 3+2.3+2.3+2.3 = 10 min

ATR_PERIOD       = 7
# Dynamic RR — Score Based
# Score 6/8 = Conservative 1:1.5
# Score 7/8 = Moderate     1:2
# Score 8/8 = Aggressive   1:3
RR_CONFIG = {
    6: {"sl_mult": 1.0, "tp_mult": 1.5},
    7: {"sl_mult": 1.0, "tp_mult": 2.0},
    8: {"sl_mult": 0.8, "tp_mult": 2.5},
}
RR_DEFAULT_SL = 1.0   # Fallback
RR_DEFAULT_TP = 1.5   # Fallback

# TP Early Exit
TP_EXIT_MIN_PCT   = 0.70
TP_EXIT_MAX_PCT   = 0.90
TP_HOLD_MIN_SCORE = 7

# Trailing SL
TRAIL_TRIGGER_PCT  = 1.0
TRAIL_DISTANCE_PCT = 0.5

# Volume
VOLUME_MULT = 1.5

# Spread
MAX_SPREAD_PCT = 0.05

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
            with open(TRADE_HISTORY, "r", encoding="utf-8") as f:
                history = json.load(f)
        except:
            history = []
        history.append({
            "date":     datetime.now().strftime("%d/%m/%Y"),
            "time":     datetime.now().strftime("%H:%M:%S"),
            "side":     side,
            "entry":    round(entry, 2),
            "exit":     round(exit_price, 2),
            "pnl":      round(pnl, 4),
            "capital":  round(capital, 4),
            "duration": duration,
            "result":   "WIN" if pnl > 0 else "LOSS",
            "label":    label,
        })
        with open(TRADE_HISTORY, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2)
    except Exception as e:
        print(f"[HISTORY ERROR] {e}")


def get_daily_stats():
    try:
        with open(TRADE_HISTORY, "r", encoding="utf-8") as f:
            history = json.load(f)
    except:
        return None
    today  = datetime.now().strftime("%d/%m/%Y")
    trades = [t for t in history if t["date"] == today]
    if not trades:
        return None
    total     = len(trades)
    wins      = len([t for t in trades if t["result"] == "WIN"])
    losses    = total - wins
    win_rate  = round((wins / total) * 100, 1) if total > 0 else 0
    daily_pnl = round(sum(t["pnl"] for t in trades), 4)
    best      = round(max(t["pnl"] for t in trades), 4)
    worst     = round(min(t["pnl"] for t in trades), 4)
    return {
        "total": total, "wins": wins, "losses": losses,
        "win_rate": win_rate, "pnl": daily_pnl,
        "best": best, "worst": worst,
        "capital": trades[-1]["capital"],
    }


def get_overall_stats():
    try:
        with open(TRADE_HISTORY, "r", encoding="utf-8") as f:
            history = json.load(f)
    except:
        return None
    if not history:
        return None
    total     = len(history)
    wins      = len([t for t in history if t["result"] == "WIN"])
    losses    = total - wins
    win_rate  = round((wins / total) * 100, 1) if total > 0 else 0
    total_pnl = round(sum(t["pnl"] for t in history), 4)
    return {
        "total": total, "wins": wins, "losses": losses,
        "win_rate": win_rate, "pnl": total_pnl,
        "best":  round(max(t["pnl"] for t in history), 4),
        "worst": round(min(t["pnl"] for t in history), 4),
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
            print("[INFO] Binance USDT-M Futures connected")
            return ex
        except Exception as e:
            print(f"[RECONNECT] Exchange connect fail: {e}")
            print("[RECONNECT] 30s baad retry...")
            time.sleep(30)


def safe_fetch_ticker(ex, symbol, retries=3):
    for i in range(retries):
        try:
            ticker = ex.fetch_ticker(symbol)
            return float(ticker["last"])
        except Exception as e:
            if "429" in str(e) or "Too Many" in str(e):
                wait = (i + 1) * 30
                print(f"[RATE LIMIT] Ticker wait {wait}s...")
                time.sleep(wait)
            else:
                print(f"[TICKER ERROR] {e}")
                time.sleep(5)
    return None


def safe_fetch_ohlcv(ex, symbol, tf, limit, retries=3):
    for i in range(retries):
        try:
            bars = ex.fetch_ohlcv(
                symbol, timeframe=tf, limit=limit)
            return bars
        except Exception as e:
            if "429" in str(e) or "Too Many" in str(e):
                wait = (i + 1) * 30
                print(f"[RATE LIMIT] {tf} wait {wait}s...")
                time.sleep(wait)
            else:
                print(f"[OHLCV ERROR] {tf}: {e}")
                time.sleep(5)
    return None


def safe_fetch_orderbook(ex, symbol, retries=3):
    for i in range(retries):
        try:
            ob = ex.fetch_order_book(symbol, limit=5)
            return ob
        except Exception as e:
            if "429" in str(e) or "Too Many" in str(e):
                wait = (i + 1) * 30
                print(f"[RATE LIMIT] OB wait {wait}s...")
                time.sleep(wait)
            else:
                print(f"[OB ERROR] {e}")
                time.sleep(5)
    return None


# ─────────────────────────────────────────────
#  TELEGRAM
# ─────────────────────────────────────────────
def send_telegram(message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
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
            print(f"[TELEGRAM] attempt {attempt+1}/3: {e}")
            time.sleep(3)
    print("[TELEGRAM] Message send nahi hua")


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
            print(f"[SPREAD] Too high: "
                  f"{spread_pct:.4f}% > {MAX_SPREAD_PCT}%")
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
        print(f"[VOLUME] Ratio: {ratio:.2f}x | "
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
        tr    = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        return float(
            tr.ewm(span=period, adjust=False).mean().iloc[-1])
    except:
        return 0.0


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
                    highs[i - swing_bars: i + swing_bars + 1]):
                swing_highs.append(highs[i])
            if lows[i] == min(
                    lows[i - swing_bars: i + swing_bars + 1]):
                swing_lows.append(lows[i])
        if len(swing_highs) < 2 or len(swing_lows) < 2:
            return "RANGE"
        hh = swing_highs[-1] > swing_highs[-2]
        hl = swing_lows[-1]  > swing_lows[-2]
        lh = swing_highs[-1] < swing_highs[-2]
        ll = swing_lows[-1]  < swing_lows[-2]
        if hh and hl:   return "BULL"
        elif lh and ll: return "BEAR"
        return "RANGE"
    except:
        return "RANGE"


# ─────────────────────────────────────────────
#  ORDER BLOCKS
# ─────────────────────────────────────────────
def detect_order_blocks(df, lookback=40):
    try:
        recent        = df.tail(lookback).reset_index(drop=True)
        n             = len(recent)
        current_price = recent["close"].iloc[-1]
        bullish_obs   = []
        bearish_obs   = []

        for i in range(1, n - 1):
            curr  = recent.iloc[i]
            next_ = recent.iloc[i + 1]

            curr_body = abs(curr["close"] - curr["open"])
            next_body = abs(next_["close"] - next_["open"])

            if curr_body == 0:
                continue

            if (curr["close"] > curr["open"] and
                    next_["close"] < next_["open"] and
                    next_body > curr_body * 1.2):
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
                    next_["close"] > next_["open"] and
                    next_body > curr_body * 1.2):
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
                    highs[i - swing_bars: i + swing_bars + 1]):
                buy_liq.append(highs[i])
            if lows[i] == min(
                    lows[i - swing_bars: i + swing_bars + 1]):
                sell_liq.append(lows[i])

        buy_swept  = False
        sell_swept = False

        if buy_liq:
            last_high = buy_liq[-1]
            recent_5  = df.tail(5)
            tolerance = last_high * 0.002
            if (any(recent_5["high"] > last_high - tolerance) and
                    current_price < last_high + tolerance):
                buy_swept = True

        if sell_liq:
            last_low  = sell_liq[-1]
            recent_5  = df.tail(5)
            tolerance = last_low * 0.002
            if (any(recent_5["low"] < last_low + tolerance) and
                    current_price > last_low - tolerance):
                sell_swept = True

        return {
            "buy_swept":   buy_swept,
            "sell_swept":  sell_swept,
            "buy_levels":  buy_liq[-3:] if buy_liq else [],
            "sell_levels": sell_liq[-3:] if sell_liq else [],
        }
    except:
        return {
            "buy_swept": False, "sell_swept": False,
            "buy_levels": [], "sell_levels": []
        }


# ─────────────────────────────────────────────
#  FVG
# ─────────────────────────────────────────────
def detect_fvg(df, lookback=30):
    try:
        fvgs          = []
        recent        = df.tail(lookback).reset_index(drop=True)
        n             = len(recent)
        current_price = recent["close"].iloc[-1]

        for i in range(2, n):
            c1 = recent.iloc[i - 2]
            c3 = recent.iloc[i]

            if c1["high"] < c3["low"]:
                gap_size = ((c3["low"] - c1["high"]) /
                            c1["high"]) * 100
                if gap_size >= 0.02:
                    tolerance = (c3["low"] - c1["high"]) * 0.3
                    fvgs.append({
                        "type":   "BULL",
                        "top":    round(c3["low"], 4),
                        "bottom": round(c1["high"], 4),
                        "size":   round(gap_size, 3),
                        "fresh":  (i >= n - 8),
                        "retest": (c1["high"] - tolerance
                                   <= current_price
                                   <= c3["low"] + tolerance),
                    })

            elif c1["low"] > c3["high"]:
                gap_size = ((c1["low"] - c3["high"]) /
                            c3["high"]) * 100
                if gap_size >= 0.02:
                    tolerance = (c1["low"] - c3["high"]) * 0.3
                    fvgs.append({
                        "type":   "BEAR",
                        "top":    round(c1["low"], 4),
                        "bottom": round(c3["high"], 4),
                        "size":   round(gap_size, 3),
                        "fresh":  (i >= n - 8),
                        "retest": (c3["high"] - tolerance
                                   <= current_price
                                   <= c1["low"] + tolerance),
                    })

        return fvgs
    except:
        return []


# ─────────────────────────────────────────────
#  QUICK MARKET SCAN — Loss Hold Decision
# ─────────────────────────────────────────────
def quick_market_scan(ex, symbol, position):
    """
    Jab trade loss mai ho aur 3 min ho jayein
    Market ko scan karo aur 10 mai se rate karo
    7+  = Hold karo
    6-  = Close karo
    """
    try:
        score   = 0
        reasons = []

        bars_1m = safe_fetch_ohlcv(ex, symbol, "1m", 50)
        bars_5m = safe_fetch_ohlcv(ex, symbol, "5m", 50)

        if bars_1m is None or bars_5m is None:
            print("[QUICK SCAN] Data nahi mila — close karo")
            return 0, ["Data fetch fail — close"]

        df_1m = pd.DataFrame(
            bars_1m,
            columns=["time","open","high","low","close","volume"])
        df_5m = pd.DataFrame(
            bars_5m,
            columns=["time","open","high","low","close","volume"])

        # ── Check 1: 5m Structure (2 pts) ────
        structure_5m = detect_structure(df_5m)
        if position == "BUY" and structure_5m == "BULL":
            score += 2
            reasons.append("5m BULL (+2)")
        elif position == "SELL" and structure_5m == "BEAR":
            score += 2
            reasons.append("5m BEAR (+2)")
        else:
            reasons.append(f"5m {structure_5m} weak (0)")

        # ── Check 2: 1m Structure (2 pts) ────
        structure_1m = detect_structure(df_1m)
        if position == "BUY" and structure_1m == "BULL":
            score += 2
            reasons.append("1m BULL confirm (+2)")
        elif position == "SELL" and structure_1m == "BEAR":
            score += 2
            reasons.append("1m BEAR confirm (+2)")
        else:
            reasons.append(f"1m {structure_1m} weak (0)")

        # ── Check 3: Order Block (2 pts) ─────
        obs = detect_order_blocks(df_1m)
        if position == "BUY":
            ob_hit = [o for o in obs["bullish_obs"]
                      if o["price_in_ob"]]
            if ob_hit:
                score += 2
                reasons.append("Bullish OB active (+2)")
            else:
                reasons.append("No Bullish OB (0)")
        else:
            ob_hit = [o for o in obs["bearish_obs"]
                      if o["price_in_ob"]]
            if ob_hit:
                score += 2
                reasons.append("Bearish OB active (+2)")
            else:
                reasons.append("No Bearish OB (0)")

        # ── Check 4: Volume (2 pts) ───────────
        avg_vol   = df_1m["volume"].tail(20).mean()
        last_vol  = df_1m["volume"].iloc[-1]
        vol_ratio = last_vol / avg_vol if avg_vol > 0 else 0

        if vol_ratio >= 1.5:
            score += 2
            reasons.append(f"Volume strong {vol_ratio:.1f}x (+2)")
        elif vol_ratio >= 1.0:
            score += 1
            reasons.append(f"Volume ok {vol_ratio:.1f}x (+1)")
        else:
            reasons.append(f"Volume weak {vol_ratio:.1f}x (0)")

        # ── Check 5: Momentum (2 pts) ─────────
        closes = df_1m["close"].tail(5).values
        if position == "BUY":
            going_up = sum(
                1 for i in range(1, len(closes))
                if closes[i] > closes[i - 1]
            )
            if going_up >= 4:
                score += 2
                reasons.append(
                    f"Strong UP momentum {going_up}/4 (+2)")
            elif going_up >= 3:
                score += 1
                reasons.append(
                    f"Weak UP momentum {going_up}/4 (+1)")
            else:
                reasons.append(
                    f"No UP momentum {going_up}/4 (0)")
        else:
            going_down = sum(
                1 for i in range(1, len(closes))
                if closes[i] < closes[i - 1]
            )
            if going_down >= 4:
                score += 2
                reasons.append(
                    f"Strong DOWN momentum {going_down}/4 (+2)")
            elif going_down >= 3:
                score += 1
                reasons.append(
                    f"Weak DOWN momentum {going_down}/4 (+1)")
            else:
                reasons.append(
                    f"No DOWN momentum {going_down}/4 (0)")

        reasons.append(f"Quick Score: {score}/10")
        print(f"[QUICK SCAN] Score={score}/10 | "
              f"{' | '.join(reasons)}")
        return score, reasons

    except Exception as e:
        print(f"[QUICK SCAN ERROR] {e}")
        return 0, [f"Scan error: {e}"]


# ─────────────────────────────────────────────
#  SMART MONEY SCORE
# ─────────────────────────────────────────────
def smart_money_score(structure_5m, structure_1m,
                      liq, obs, fvgs, volume_ok=True):
    points    = 0
    direction = None
    reasons   = []

    if structure_5m == "BULL":
        points += 2
        direction = "BUY"
        reasons.append("5m BULL (+2)")
    elif structure_5m == "BEAR":
        points += 2
        direction = "SELL"
        reasons.append("5m BEAR (+2)")
    else:
        reasons.append("5m RANGE — no direction (0)")
        reasons.append("Total: 0/8 — RANGE skip")
        return 0, "WAIT", reasons

    if (direction == "BUY"  and structure_1m == "BULL") or \
       (direction == "SELL" and structure_1m == "BEAR"):
        points += 1
        reasons.append(f"1m confirms {direction} (+1)")
    elif structure_1m == "RANGE":
        reasons.append("1m RANGE — no confirm (0)")
    else:
        reasons.append("1m opposite — weak (0)")

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
                f"Bullish OB "
                f"{best_ob['bottom']:.2f}-"
                f"{best_ob['top']:.2f} (+2)")
        else:
            reasons.append("No Bullish OB hit (0)")
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
                f"Bearish OB "
                f"{best_ob['bottom']:.2f}-"
                f"{best_ob['top']:.2f} (+2)")
        else:
            reasons.append("No Bearish OB hit (0)")

    if direction == "BUY" and liq["sell_swept"]:
        points += 2
        reasons.append("Sell liquidity swept (+2)")
    elif direction == "SELL" and liq["buy_swept"]:
        points += 2
        reasons.append("Buy liquidity swept (+2)")
    else:
        reasons.append("No liquidity sweep (0)")

    if direction == "BUY":
        bull_fvg = [f for f in fvgs
                    if f["type"] == "BULL" and f["retest"]]
        if bull_fvg:
            points += 1
            reasons.append(
                f"Bull FVG "
                f"{bull_fvg[-1]['bottom']:.2f}-"
                f"{bull_fvg[-1]['top']:.2f} (+1)")
        else:
            reasons.append("No Bull FVG retest (0)")
    else:
        bear_fvg = [f for f in fvgs
                    if f["type"] == "BEAR" and f["retest"]]
        if bear_fvg:
            points += 1
            reasons.append(
                f"Bear FVG "
                f"{bear_fvg[-1]['bottom']:.2f}-"
                f"{bear_fvg[-1]['top']:.2f} (+1)")
        else:
            reasons.append("No Bear FVG retest (0)")

    if not volume_ok:
        reasons.append("Volume weak — caution")
    else:
        reasons.append("Volume confirmed")

    reasons.append(f"Total: {points}/8")
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
    """
    Score ke hisaab se SL aur TP multiplier lo

    Score 6/8 = Conservative = 1:1.5
    Score 7/8 = Moderate     = 1:2
    Score 8/8 = Aggressive   = 1:3
    """
    score = int(score)

    if score >= 8:
        sl_mult = RR_CONFIG[8]["sl_mult"]
        tp_mult = RR_CONFIG[8]["tp_mult"]
        rr_type = "Aggressive 1:3.1"
    elif score == 7:
        sl_mult = RR_CONFIG[7]["sl_mult"]
        tp_mult = RR_CONFIG[7]["tp_mult"]
        rr_type = "Moderate 1:2"
    elif score == 6:
        sl_mult = RR_CONFIG[6]["sl_mult"]
        tp_mult = RR_CONFIG[6]["tp_mult"]
        rr_type = "Conservative 1:1.5"
    else:
        sl_mult = RR_DEFAULT_SL
        tp_mult = RR_DEFAULT_TP
        rr_type = "Default 1:1.5"

    print(f"[DYNAMIC RR] Score={score}/8 | "
          f"SL={sl_mult}x | TP={tp_mult}x | "
          f"Type={rr_type}")

    return sl_mult, tp_mult, rr_type


# ─────────────────────────────────────────────
#  SHARED STATE
# ─────────────────────────────────────────────
trade_state = {
    "position":     None,
    "entry_price":  0.0,
    "entry_time":   None,
    "sl_price":     0.0,
    "tp_price":     0.0,
    "pos_size":     0.0,
    "capital_used": 0.0,
    "capital":      CAPITAL,
    "last_signal":  "WAIT",
    "last_conf":    0,
    "last_price":   0.0,
    "last_points":  0,
    "last_tp_zone": "",
    "last_session": "",
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
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with state_lock:
                position        = trade_state["position"]
                price           = trade_state["last_price"]
                capital         = trade_state["capital"]
                points          = trade_state["last_points"]
                entry           = trade_state["entry_price"]
                sl              = trade_state["sl_price"]
                tp              = trade_state["tp_price"]
                psize           = trade_state["pos_size"]
                etime           = trade_state["entry_time"]
                capital_used    = trade_state["capital_used"]
                tp_zone         = trade_state["last_tp_zone"]
                session         = trade_state["last_session"]
                ext_count       = trade_state["extension_count"]

            if price == 0:
                time.sleep(UPDATE_INTERVAL)
                continue

            if position is not None and etime is not None:
                pnl      = calc_pnl(position, entry, price, psize)
                dur      = str(datetime.now() - etime).split(".")[0]
                pnl_icon = "+" if pnl >= 0 else ""

                if position == "BUY":
                    tp_dist = ((tp - price) / price) * 100
                    sl_dist = ((price - sl) / price) * 100
                else:
                    tp_dist = ((price - tp) / price) * 100
                    sl_dist = ((sl - price) / price) * 100

                tp_zone_line = (f"\nTP Zone : {tp_zone}"
                                if tp_zone else "")
                ext_line = (f"\nExt     : {ext_count}/"
                            f"{MAX_EXTENSIONS}"
                            if ext_count > 0 else "")

                send_telegram(
                    f"--- SCALP UPDATE ---\n"
                    f"Time    : {now}\n"
                    f"Session : {session}\n"
                    f"Side    : {position}\n"
                    f"Entry   : {entry:.2f}\n"
                    f"Price   : {price:.2f}\n"
                    f"PnL     : {pnl_icon}{pnl:.4f} USDT\n"
                    f"Capital : {capital:.4f} USDT\n"
                    f"Duration: {dur}\n"
                    f"--------------------\n"
                    f"TP      : {tp:.2f} "
                    f"({tp_dist:.2f}% door)\n"
                    f"SL      : {sl:.2f} "
                    f"({sl_dist:.2f}% door)\n"
                    f"Score   : {points}/8"
                    f"{tp_zone_line}"
                    f"{ext_line}"
                )
            else:
                send_telegram(
                    f"--- SCALP MARKET ---\n"
                    f"Time    : {now}\n"
                    f"Session : {session}\n"
                    f"Price   : {price:.2f}\n"
                    f"Score   : {points}/8\n"
                    f"Capital : {capital:.4f} USDT\n"
                    f"Status  : Next scalp ka wait...\n"
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
            ist = timezone(timedelta(hours=5, minutes=30))
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
                        f"Win Rate : {daily['win_rate']}%\n"
                        f"PnL      : {daily['pnl']:+.4f} USDT\n"
                        f"Capital  : "
                        f"{daily['capital']:.4f} USDT\n"
                        f"Best     : "
                        f"+{daily['best']:.4f} USDT\n"
                        f"Worst    : "
                        f"{daily['worst']:.4f} USDT\n"
                        f"--------------------\n"
                        f"OVERALL:\n"
                        f"Trades   : {overall['total']}\n"
                        f"Win Rate : {overall['win_rate']}%\n"
                        f"Total PnL: "
                        f"{overall['pnl']:+.4f} USDT\n"
                        f"Capital  : "
                        f"{overall['capital']:.4f} USDT\n"
                        f"--------------------"
                    )
                else:
                    send_telegram(
                        f"--- SCALP DAILY ---\n"
                        f"Aaj koi scalp trade nahi hua\n"
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
    print("[SCALP DECISION] v3.0 Smart Max Hold started")

    while True:
        try:
            scan_time = datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S")

            good_session, session_name = is_good_session()
            update_state(last_session=session_name)

            bars_5m = safe_fetch_ohlcv(
                exchange, SYMBOL, "5m", 100)
            time.sleep(0.5)
            bars_1m = safe_fetch_ohlcv(
                exchange, SYMBOL, "1m", 100)

            if bars_5m is None or bars_1m is None:
                print("[DECISION] Data fetch fail "
                      "— reconnecting...")
                exchange = get_exchange()
                time.sleep(30)
                continue

            df_5m = pd.DataFrame(
                bars_5m,
                columns=["time","open","high",
                         "low","close","volume"])
            df_1m = pd.DataFrame(
                bars_1m,
                columns=["time","open","high",
                         "low","close","volume"])

            if len(df_5m) < 20 or len(df_1m) < 20:
                print("[DECISION] Data insufficient")
                time.sleep(30)
                continue

            df_5m["time"] = pd.to_datetime(
                df_5m["time"], unit="ms")
            df_1m["time"] = pd.to_datetime(
                df_1m["time"], unit="ms")

            current_price = float(df_1m["close"].iloc[-1])

            atr_1m = calc_atr(df_1m, ATR_PERIOD)
            atr_5m = calc_atr(df_5m, ATR_PERIOD)

            volume_ok = check_volume(df_1m, VOLUME_MULT)

            structure_5m = detect_structure(df_5m)
            structure_1m = detect_structure(df_1m)
            liq          = detect_liquidity(df_1m)
            obs          = detect_order_blocks(df_1m)
            fvgs         = detect_fvg(df_1m)

            points, direction, reasons = smart_money_score(
                structure_5m, structure_1m,
                liq, obs, fvgs, volume_ok
            )

            confidence = int((points / 8) * 100)

            if points >= MIN_SCORE and direction == "BUY":
                signal = "BUY"
            elif points >= MIN_SCORE and direction == "SELL":
                signal = "SELL"
            else:
                signal = "WAIT"

                       if not good_session and signal != "WAIT":
                # Asian session mai sirf 7/8+ score pe trade
                if points >= 7:
                    print(f"[SESSION] {session_name} "
                          f"— Score {points}/8 HIGH "
                          f"— Asian session trade allowed")
                else:
                    print(f"[SESSION] {session_name} "
                          f"— Score {points}/8 LOW "
                          f"— Skip")
                    signal = "WAIT"

            print(f"[SCALP] {scan_time} | {points}/8 | "
                  f"{signal} | ATR_1m={atr_1m:.2f} | "
                  f"ATR_5m={atr_5m:.2f} | "
                  f"Price={current_price:.2f} | "
                  f"Session={session_name}")

            signal_data = {
                "signal":     signal,
                "confidence": confidence,
                "score":      points,
                "atr_1m":     round(atr_1m, 4),
                "atr_5m":     round(atr_5m, 4),
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
                "atr_1m":    round(atr_1m, 4),
                "atr_5m":    round(atr_5m, 4),
                "price":     current_price,
                "reasons":   reasons,
                "volume_ok": volume_ok,
                "session":   session_name,
            })
            log = log[-3000:]
            with open(LOG_FILE, "w",
                      encoding="utf-8") as f:
                json.dump(log, f, indent=2)

        except Exception as e:
            print(f"[DECISION ERROR] {e}")
            if ("connection" in str(e).lower() or
                    "timeout" in str(e).lower()):
                print("[DECISION] Reconnecting...")
                exchange = get_exchange()
            time.sleep(30)

        time.sleep(DECISION_SCAN)


# ─────────────────────────────────────────────
#  EXECUTION ENGINE — Smart Max Hold
# ─────────────────────────────────────────────
def run_execution_engine():
    ex              = get_exchange()
    capital         = load_capital()
    position        = None
    entry_price     = 0.0
    entry_time      = None
    pos_size        = 0.0
    sl_price        = 0.0
    tp_price        = 0.0
    capital_used    = 0.0
    cooldown_end    = load_cooldown()
    extension_count = 0          # Smart Max Hold counter

    print("[SCALP EXECUTE] Waiting for first signal...")
    signal_data = signal_queue.get()
    print("[SCALP EXECUTE] v3.0 Smart Max Hold started!")

    send_telegram(
        f"SCALPING BOT v3.0 STARTED\n"
        f"Capital  : {capital:.2f} USDT\n"
        f"Symbol   : {SYMBOL}\n"
        f"Mode     : Paper Trading\n"
        f"Strategy : Smart Money 24/7\n"
        f"Leverage : {LEVERAGE}x\n"
        f"Capital% : {CAPITAL_USE_PCT}%\n"
        f"Min Score: {MIN_SCORE}/8\n"
        f"Max Hold : {MAX_HOLD_SECONDS//60} min base\n"
        f"Extension: {MAX_HOLD_EXTENSION}s x "
        f"{MAX_EXTENSIONS} times\n"
        f"Hold Min : {HOLD_SCORE_MINIMUM}/10\n"
        f"TP Zone  : {int(TP_EXIT_MIN_PCT*100)}-"
        f"{int(TP_EXIT_MAX_PCT*100)}%\n"
        f"Trail SL : {TRAIL_TRIGGER_PCT}% trigger\n"
        f"Volume   : {VOLUME_MULT}x confirm\n"
        f"Spread   : {MAX_SPREAD_PCT}% max"
    )

    signal   = signal_data.get("signal", "WAIT")
    score    = signal_data.get("score", 0)
    atr_5m   = signal_data.get("atr_5m", 0.0)
    reason   = " | ".join(signal_data.get("reasons", []))
    session  = signal_data.get("session", "")
    vol_ok   = signal_data.get("volume_ok", True)

    while True:
        try:
            # Queue se latest signal lo
            try:
                new_data = signal_queue.get_nowait()
                signal   = new_data.get("signal", "WAIT")
                score    = new_data.get("score", 0)
                atr_5m   = new_data.get("atr_5m", 0.0)
                reason   = " | ".join(
                    new_data.get("reasons", []))
                session  = new_data.get("session", "")
                vol_ok   = new_data.get("volume_ok", True)
            except queue.Empty:
                pass

            current_price = get_cached_price(ex, SYMBOL)
            if current_price is None:
                print("[EXECUTE] Price fetch fail "
                      "— reconnect...")
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

            # ── Smart Max Hold Check ──────────────
            if position is not None and entry_time is not None:
                held_secs = (
                    datetime.now() - entry_time).seconds

                if held_secs >= MAX_HOLD_SECONDS:
                    pnl_now = calc_pnl(
                        position, entry_price,
                        current_price, pos_size
                    )

                    # Profit mai hai — Normal Close
                    if pnl_now >= 0:
                        pnl      = pnl_now
                        capital += pnl
                        duration = str(
                            datetime.now() - entry_time
                        ).split(".")[0]
                        save_capital(capital)
                        save_trade_history(
                            position, entry_price,
                            current_price, pnl,
                            capital, duration,
                            "Max Hold — Profit"
                        )
                        print(
                            f"[MAX HOLD] Profit mai tha"
                            f" — Normal Close | "
                            f"PnL={pnl:+.4f}")
                        send_telegram(
                            f"SCALP CLOSED — Max Hold\n"
                            f"Side    : {position}\n"
                            f"Entry   : {entry_price:.2f}\n"
                            f"Exit    : {current_price:.2f}\n"
                            f"PnL     : {pnl:+.4f} USDT\n"
                            f"Capital : {capital:.4f} USDT\n"
                            f"Reason  : Profit mai tha ✅\n"
                            f"Time    : {duration}"
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
                                          COOLDOWN)
                        save_cooldown(cooldown_end)
                        update_state(
                            position=None,
                            capital_used=0.0,
                            capital=capital,
                            last_tp_zone="",
                            extension_count=0
                        )
                        time.sleep(EXECUTE_SCAN)
                        continue

                    # Loss mai hai
                    else:
                        # Max extensions khatam?
                        if extension_count >= MAX_EXTENSIONS:
                            pnl      = pnl_now
                            capital += pnl
                            duration = str(
                                datetime.now() - entry_time
                            ).split(".")[0]
                            save_capital(capital)
                            save_trade_history(
                                position, entry_price,
                                current_price, pnl,
                                capital, duration,
                                "Max Hold — Extension Over"
                            )
                            print(
                                f"[MAX HOLD] Max extensions"
                                f" ({MAX_EXTENSIONS}) khatam"
                                f" — Force Close | "
                                f"PnL={pnl:+.4f}")
                            send_telegram(
                                f"SCALP CLOSED — Force\n"
                                f"Side    : {position}\n"
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
                                f"{MAX_EXTENSIONS} khatam\n"
                                f"Time    : {duration}"
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
                                              COOLDOWN)
                            save_cooldown(cooldown_end)
                            update_state(
                                position=None,
                                capital_used=0.0,
                                capital=capital,
                                last_tp_zone="",
                                extension_count=0
                            )
                            time.sleep(EXECUTE_SCAN)
                            continue

                        # Market Scan Karo
                        print(
                            f"[MAX HOLD] Loss mai hai "
                            f"PnL={pnl_now:+.4f} "
                            f"— Scanning...")
                        send_telegram(
                            f"MAX HOLD — SCANNING\n"
                            f"Side   : {position}\n"
                            f"PnL    : "
                            f"{pnl_now:+.4f} USDT\n"
                            f"Status : Loss mai hain\n"
                            f"Action : Market scan...\n"
                            f"Ext    : {extension_count}/"
                            f"{MAX_EXTENSIONS}"
                        )

                        q_score, q_reasons = (
                            quick_market_scan(
                                ex, SYMBOL, position
                            )
                        )

                        # Score 7+ = Hold karo
                        if q_score >= HOLD_SCORE_MINIMUM:
                            extension_count += 1
                            update_state(
                                extension_count=extension_count
                            )
                            print(
                                f"[MAX HOLD] "
                                f"Score={q_score}/10 "
                                f"STRONG — Hold "
                                f"({extension_count}/"
                                f"{MAX_EXTENSIONS})")
                            send_telegram(
                                f"MAX HOLD EXTENDED ⏳\n"
                                f"Side  : {position}\n"
                                f"PnL   : "
                                f"{pnl_now:+.4f} USDT\n"
                                f"Score : "
                                f"{q_score}/10 STRONG\n"
                                f"Hold  : "
                                f"{extension_count}/"
                                f"{MAX_EXTENSIONS}\n"
                                f"Reason: "
                                f"{' | '.join(q_reasons[:3])}"
                            )
                            time.sleep(MAX_HOLD_EXTENSION)
                            continue

                        # Score 6- = Close karo
                        else:
                            pnl      = pnl_now
                            capital += pnl
                            duration = str(
                                datetime.now() - entry_time
                            ).split(".")[0]
                            save_capital(capital)
                            save_trade_history(
                                position, entry_price,
                                current_price, pnl,
                                capital, duration,
                                "Max Hold — Scan Weak"
                            )
                            print(
                                f"[MAX HOLD] "
                                f"Score={q_score}/10 "
                                f"WEAK — Closing | "
                                f"PnL={pnl:+.4f}")
                            send_telegram(
                                f"SCALP CLOSED — Weak\n"
                                f"Side    : {position}\n"
                                f"Entry   : "
                                f"{entry_price:.2f}\n"
                                f"Exit    : "
                                f"{current_price:.2f}\n"
                                f"PnL     : "
                                f"{pnl:+.4f} USDT\n"
                                f"Capital : "
                                f"{capital:.4f} USDT\n"
                                f"Score   : "
                                f"{q_score}/10 weak\n"
                                f"Reason  : "
                                f"{' | '.join(q_reasons[:3])}\n"
                                f"Time    : {duration}"
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
                                              COOLDOWN)
                            save_cooldown(cooldown_end)
                            update_state(
                                position=None,
                                capital_used=0.0,
                                capital=capital,
                                last_tp_zone="",
                                extension_count=0
                            )
                            time.sleep(EXECUTE_SCAN)
                            continue

            # ── TP Zone Check 70-90% ─────────────
            if position is not None:
                try:
                    if position == "BUY":
                        tp_range = tp_price - entry_price
                        tp_prog  = (
                            (current_price - entry_price) /
                            tp_range
                        ) if tp_range != 0 else 0
                    else:
                        tp_range = entry_price - tp_price
                        tp_prog  = (
                            (entry_price - current_price) /
                            tp_range
                        ) if tp_range != 0 else 0

                    if (TP_EXIT_MIN_PCT
                            <= tp_prog
                            <= TP_EXIT_MAX_PCT):
                        pts = get_state("last_points")
                        if pts < TP_HOLD_MIN_SCORE:
                            pnl      = calc_pnl(
                                position, entry_price,
                                current_price, pos_size)
                            capital += pnl
                            duration = str(
                                datetime.now() - entry_time
                            ).split(".")[0]
                            save_capital(capital)
                            save_trade_history(
                                position, entry_price,
                                current_price, pnl,
                                capital, duration,
                                "Early Exit"
                            )
                            update_state(
                                last_tp_zone=(
                                    f"TP {tp_prog*100:.0f}%"
                                    f" exit | Score={pts}/8"
                                    f" | PnL={pnl:+.4f}"
                                )
                            )
                            print(
                                f"[EARLY EXIT] "
                                f"TP {tp_prog*100:.0f}% | "
                                f"Score={pts}/8 | "
                                f"PnL={pnl:+.4f}")
                            send_telegram(
                                f"SCALP EARLY EXIT\n"
                                f"Side  : {position}\n"
                                f"Entry : {entry_price:.2f}\n"
                                f"Exit  : "
                                f"{current_price:.2f}\n"
                                f"PnL   : {pnl:+.4f} USDT\n"
                                f"Zone  : "
                                f"{tp_prog*100:.0f}%\n"
                                f"Score : {pts}/8 weak"
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
                                              COOLDOWN)
                            save_cooldown(cooldown_end)
                            update_state(
                                position=None,
                                capital_used=0.0,
                                capital=capital,
                                last_tp_zone="",
                                extension_count=0
                            )
                            time.sleep(EXECUTE_SCAN)
                            continue
                        else:
                            update_state(
                                last_tp_zone=(
                                    f"TP {tp_prog*100:.0f}%"
                                    f" zone | Score={pts}/8"
                                    f" strong — wait"
                                )
                            )
                    else:
                        update_state(last_tp_zone="")
                except Exception as e:
                    print(f"[TP ZONE ERROR] {e}")

            # ── Trailing SL ──────────────────────
            if position is not None:
                try:
                    if position == "BUY":
                        p_pct = (
                            (current_price - entry_price) /
                            entry_price
                        ) * 100
                        if p_pct >= TRAIL_TRIGGER_PCT:
                            new_sl = current_price * (
                                1 - TRAIL_DISTANCE_PCT / 100)
                            if new_sl > sl_price:
                                sl_price = new_sl
                                update_state(
                                    sl_price=sl_price)
                                print(
                                    f"[TRAIL] BUY SL "
                                    f"-> {sl_price:.2f}")
                    elif position == "SELL":
                        p_pct = (
                            (entry_price - current_price) /
                            entry_price
                        ) * 100
                        if p_pct >= TRAIL_TRIGGER_PCT:
                            new_sl = current_price * (
                                1 + TRAIL_DISTANCE_PCT / 100)
                            if new_sl < sl_price:
                                sl_price = new_sl
                                update_state(
                                    sl_price=sl_price)
                                print(
                                    f"[TRAIL] SELL SL "
                                    f"-> {sl_price:.2f}")
                except Exception as e:
                    print(f"[TRAIL ERROR] {e}")

            # ── SL/TP Check ──────────────────────
            if position is not None:
                hit_sl = (
                    (position == "BUY" and
                     current_price <= sl_price) or
                    (position == "SELL" and
                     current_price >= sl_price)
                )
                hit_tp = (
                    (position == "BUY" and
                     current_price >= tp_price) or
                    (position == "SELL" and
                     current_price <= tp_price)
                )

                if hit_sl or hit_tp:
                    label    = ("STOP LOSS" if hit_sl
                                else "TAKE PROFIT")
                    pnl      = calc_pnl(
                        position, entry_price,
                        current_price, pos_size)
                    capital += pnl
                    duration = str(
                        datetime.now() - entry_time
                    ).split(".")[0]
                    save_capital(capital)
                    save_trade_history(
                        position, entry_price,
                        current_price, pnl,
                        capital, duration, label
                    )
                    print(
                        f"[SCALP] {label} | {position} | "
                        f"PnL={pnl:+.4f} | "
                        f"Capital={capital:.4f}")
                    send_telegram(
                        f"SCALP CLOSED — {label}\n"
                        f"Side    : {position}\n"
                        f"Entry   : {entry_price:.2f}\n"
                        f"Exit    : {current_price:.2f}\n"
                        f"PnL     : {pnl:+.4f} USDT\n"
                        f"Capital : {capital:.4f} USDT\n"
                        f"Time    : {duration}"
                    )
                    position        = None
                    entry_price     = 0.0
                    entry_time      = None
                    pos_size        = 0.0
                    sl_price        = 0.0
                    tp_price        = 0.0
                    capital_used    = 0.0
                    extension_count = 0
                    cooldown_end    = time.time() + COOLDOWN
                    save_cooldown(cooldown_end)
                    update_state(
                        position=None,
                        capital_used=0.0,
                        capital=capital,
                        last_tp_zone="",
                        extension_count=0
                    )
                    time.sleep(EXECUTE_SCAN)
                    continue

            # ── Cooldown Check ───────────────────
            if (cooldown_end is not None and
                    time.time() < cooldown_end):
                remaining = int(cooldown_end - time.time())
                print(f"[{now}] Cooldown {remaining}s | "
                      f"Price={current_price:.2f}")
                time.sleep(EXECUTE_SCAN)
                continue

            # ── Entry Check ──────────────────────
            if position is None:
                if (signal in ["BUY", "SELL"] and
                        int(score) >= MIN_SCORE):

                    spread_ok = check_spread(ex, SYMBOL)
                    if not spread_ok:
                        print(f"[{now}] SKIP — spread high")
                        time.sleep(EXECUTE_SCAN)
                        continue

                                       if not vol_ok and int(score) < 7:
                        print(
                            f"[{now}] SKIP — volume weak "
                            f"+ score={score}")
                        time.sleep(EXECUTE_SCAN)
                        continue

                    # Asian session extra check
                    good_sess, sess_name = is_good_session()
                    if not good_sess and int(score) < 7:
                        print(
                            f"[{now}] SKIP — Asian session "
                            f"+ score={score} < 7")
                        time.sleep(EXECUTE_SCAN)
                        continue

                                       # Dynamic RR — Score based
                    sl_mult, tp_mult, rr_type = (
                        get_dynamic_rr(score)
                    )

                    if atr_5m > 0:
                        sl_pct = (atr_5m * sl_mult /
                                  current_price) * 100
                        tp_pct = (atr_5m * tp_mult /
                                  current_price) * 100
                    else:
                        sl_pct = 0.3 * sl_mult
                        tp_pct = 0.3 * tp_mult

                    capital_used    = (capital *
                                      (CAPITAL_USE_PCT / 100))
                    pos_size        = ((capital_used *
                                       LEVERAGE) /
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

                    print(
                        f"[SCALP] OPENED | {position} | "
                        f"Entry={entry_price:.2f} | "
                        f"SL={sl_price:.2f} | "
                        f"TP={tp_price:.2f} | "
                        f"Score={int(score)}/8")
                                      
                    send_telegram(
                        f"SCALP OPENED\n"
                        f"Side    : {position}\n"
                        f"Entry   : {entry_price:.2f}\n"
                        f"SL      : {sl_price:.2f}\n"
                        f"TP      : {tp_price:.2f}\n"
                        f"ATR 5m  : {atr_5m:.2f}\n"
                        f"Capital : {capital_used:.2f} USDT\n"
                        f"Score   : {int(score)}/8\n"
                        f"RR Type : {rr_type}\n"
                        f"SL Mult : {sl_mult}x ATR\n"
                        f"TP Mult : {tp_mult}x ATR\n"
                        f"Volume  : "
                        f"{'OK' if vol_ok else 'WEAK'}\n"
                        f"Session : {session}\n"
                        f"Reason  : {reason[:250]}"
                    )
                else:
                    print(
                        f"[{now}] WAIT | "
                        f"Score={int(score)}/8 | "
                        f"Price={current_price:.2f} | "
                        f"Session={session}")

            # ── Holding ──────────────────────────
            else:
                pnl_now = calc_pnl(
                    position, entry_price,
                    current_price, pos_size)
                held = (datetime.now() -
                        entry_time).seconds
                print(
                    f"[{now}] Holding {position} | "
                    f"PnL={pnl_now:+.4f} | "
                    f"Price={current_price:.2f} | "
                    f"Held={held}s | "
                    f"Ext={extension_count}/"
                    f"{MAX_EXTENSIONS}")

        except Exception as e:
            err_msg = str(e)
            print(f"[EXECUTE ERROR] {err_msg}")
            if "429" in err_msg or "Too Many" in err_msg:
                print("[RATE LIMIT] 60s wait...")
                time.sleep(60)
            elif ("connection" in err_msg.lower() or
                  "timeout" in err_msg.lower()):
                print("[CONNECTION] Reconnecting...")
                ex = get_exchange()
                time.sleep(10)
            else:
                time.sleep(10)

        time.sleep(EXECUTE_SCAN)


# ─────────────────────────────────────────────
#  START
# ─────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 55)
    print("  SCALPING BOT v3.0 — Smart Max Hold")
    print("  Strategy  : Smart Money 24/7")
    print("  Min Score : 6/8")
    print("  Capital   : 90%")
   print("  Max Hold  : 3 min + Smart Extension")
print(f"  Extension : {MAX_HOLD_EXTENSION}s "
      f"x {MAX_EXTENSIONS} = "
      f"{(MAX_HOLD_SECONDS + MAX_HOLD_EXTENSION * MAX_EXTENSIONS)//60} min max")
    print("  Hold Score: 7/10")
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
    print(f"[INFO] Flask    : port 8081")
    print(f"[INFO] Decision : har {DECISION_SCAN}s")
    print(f"[INFO] Execute  : har {EXECUTE_SCAN}s")
    print(f"[INFO] Max Hold : "
          f"{MAX_HOLD_SECONDS}s base + "
          f"{MAX_HOLD_EXTENSION}s x {MAX_EXTENSIONS}")
    print(f"[INFO] Hold Min : {HOLD_SCORE_MINIMUM}/10")
    print(f"[INFO] 24/7     : ON")

    while True:
        time.sleep(60)
