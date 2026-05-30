"""
ETH Momentum Scalping Bot v2.0
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Strategy : 30s Momentum
           Market direction dekho
           Us taraf entry lo
           Profit pe exit
Symbol   : ETH/USDT
Capital  : 1000 USDT
Leverage : 5x
Target   : 0.15% per trade
SL       : 0.10% per trade
Max Hold : 60 seconds
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import ccxt
import pandas as pd
import numpy as np
import requests
import threading
import time
import json
import os
import queue
from flask import Flask
from queue import Queue
from datetime import datetime, timezone, timedelta

app = Flask(__name__)

@app.route('/')
def home():
    return "ETH Momentum Bot v2.0 Running!"

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
CAPITAL     = 1000.0
CAPITAL_USE = 90       # 90% = 900 USDT
LEVERAGE    = 5

# ── Trade Config ──────────────────────────
TP_PCT      = 0.15     # 0.15% target
SL_PCT      = 0.10     # 0.10% stop loss
MAX_HOLD    = 60       # 60 seconds max

# ── Momentum Config ───────────────────────
MOMENTUM_CANDLES = 6   # 6 candles of 5s = 30s
MOMENTUM_TF      = "1m"
SCAN_INTERVAL    = 5   # Har 5 second scan

# ── Cooldown ──────────────────────────────
COOLDOWN_WIN   = 10    # Win ke baad 10s
COOLDOWN_LOSS  = 20    # Loss ke baad 20s
COOLDOWN_2LOSS = 40    # 2 loss ke baad 40s

# ── Spread ────────────────────────────────
MAX_SPREAD = 0.05

# ── Update ────────────────────────────────
UPDATE_INTERVAL = 1800


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
    "capital":      CAPITAL,
    "last_price":   0.0,
    "momentum":     "FLAT",
    "last_signal":  "WAIT",
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
            "date":     datetime.now().strftime(
                "%d/%m/%Y"),
            "time":     datetime.now().strftime(
                "%H:%M:%S"),
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
    trades = [
        t for t in history
        if t["date"] == today]

    if not trades:
        return None

    total    = len(trades)
    wins     = len([
        t for t in trades
        if t["result"] == "WIN"])
    losses   = total - wins
    win_rate = round(
        (wins / total) * 100, 1)
    pnl      = round(
        sum(t["pnl"] for t in trades), 4)

    return {
        "total":    total,
        "wins":     wins,
        "losses":   losses,
        "win_rate": win_rate,
        "pnl":      pnl,
        "best":     round(
            max(t["pnl"] for t in trades), 4),
        "worst":    round(
            min(t["pnl"] for t in trades), 4),
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


def safe_fetch_ohlcv(ex, tf, limit):
    for i in range(3):
        try:
            bars = ex.fetch_ohlcv(
                SYMBOL,
                timeframe=tf,
                limit=limit)
            return bars
        except Exception as e:
            if "429" in str(e):
                time.sleep((i+1) * 30)
            else:
                time.sleep(3)
    return None


def safe_fetch_ticker(ex):
    for i in range(3):
        try:
            t = ex.fetch_ticker(SYMBOL)
            return float(t["last"])
        except Exception as e:
            if "429" in str(e):
                time.sleep((i+1) * 30)
            else:
                time.sleep(3)
    return None


def safe_fetch_orderbook(ex):
    for i in range(3):
        try:
            ob = ex.fetch_order_book(
                SYMBOL, limit=5)
            return ob
        except Exception as e:
            if "429" in str(e):
                time.sleep((i+1) * 30)
            else:
                time.sleep(3)
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
                    "text": (
                        f"[SCALP] {message}"),
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
#  SPREAD CHECK
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


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  PnL CALCULATOR
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def calc_pnl(side, entry, exit_p, pos_size):
    if side == "BUY":
        return (exit_p - entry) * pos_size
    else:
        return (entry - exit_p) * pos_size


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  MOMENTUM DETECTOR
#  30 Second direction detect karta hai
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def detect_momentum(ex):
    """
    Last 30 seconds ka momentum check karta hai

    1m candles fetch karta hai
    Last candle ka direction dekha jata hai
    Volume confirm karta hai
    """
    try:
        # 1m candles — last 10 fetch karo
        bars = safe_fetch_ohlcv(ex, "1m", 10)
        if bars is None or len(bars) < 3:
            return "FLAT", 0.0, 0.0

        df = pd.DataFrame(
            bars,
            columns=[
                "time", "open", "high",
                "low", "close", "volume"])

        # Current incomplete candle
        last   = df.iloc[-1]
        prev   = df.iloc[-2]
        prev2  = df.iloc[-3]

        cur_open  = float(last["open"])
        cur_close = float(last["close"])
        cur_high  = float(last["high"])
        cur_low   = float(last["low"])
        cur_vol   = float(last["volume"])

        prev_close = float(prev["close"])
        prev_open  = float(prev["open"])
        prev_vol   = float(prev["volume"])

        avg_vol = float(
            df["volume"].tail(5).mean())

        # ── Momentum Calculate ────────────
        # Current candle ka move
        cur_move = (
            (cur_close - cur_open) /
            cur_open) * 100

        # Previous candle ka move
        prev_move = (
            (prev_close - prev_open) /
            prev_open) * 100

        # Volume strong hai?
        vol_strong = cur_vol > avg_vol * 0.8

        # Price direction
        price_up   = cur_close > cur_open
        price_down = cur_close < cur_open

        # Consecutive movement
        both_up   = (
            price_up and
            prev_close > prev_open)
        both_down = (
            price_down and
            prev_close < prev_open)

        # Body size (candle strength)
        body_size = abs(cur_close - cur_open)
        total_size = cur_high - cur_low
        body_ratio = (
            body_size / total_size
            if total_size > 0 else 0)

        # ── Signal Decision ───────────────
        if (both_up and
                vol_strong and
                body_ratio > 0.3):
            momentum = "UP"
        elif (both_down and
              vol_strong and
              body_ratio > 0.3):
            momentum = "DOWN"
        elif price_up and vol_strong:
            momentum = "UP"
        elif price_down and vol_strong:
            momentum = "DOWN"
        else:
            momentum = "FLAT"

        print(
            f"[MOMENTUM] {momentum} | "
            f"Move={cur_move:.3f}% | "
            f"Vol={cur_vol/avg_vol:.1f}x | "
            f"Body={body_ratio:.2f} | "
            f"Price={cur_close:.4f}")

        return momentum, cur_close, cur_move

    except Exception as e:
        print(f"[MOMENTUM ERROR] {e}")
        return "FLAT", 0.0, 0.0


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
            sl       = st["sl_price"]
            tp       = st["tp_price"]
            psize    = st["pos_size"]
            etime    = st["entry_time"]
            momentum = st["momentum"]

            daily = get_daily_stats()

            if (pos is not None and
                    etime is not None and
                    price > 0):
                pnl_now = calc_pnl(
                    pos, entry, price, psize)
                dur = str(
                    datetime.now() -
                    etime).split(".")[0]
                icon = (
                    "🟢" if pnl_now >= 0
                    else "🔴")

                msg = (
                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"  ETH BOT UPDATE\n"
                    f"  {now}\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"{icon} {pos}\n"
                    f"Entry  : {entry:.4f}\n"
                    f"Price  : {price:.4f}\n"
                    f"PnL    : "
                    f"{pnl_now:+.4f} USDT\n"
                    f"Momentum: {momentum}\n"
                    f"Capital: "
                    f"{capital:.4f} USDT\n")
            else:
                msg = (
                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"  ETH BOT UPDATE\n"
                    f"  {now}\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"⏳ WAITING\n"
                    f"Price   : {price:.4f}\n"
                    f"Momentum: {momentum}\n"
                    f"Capital : "
                    f"{capital:.4f} USDT\n")

            if daily:
                msg += (
                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"TODAY\n"
                    f"Trades : {daily['total']}\n"
                    f"Wins   : {daily['wins']} ✅\n"
                    f"Losses : "
                    f"{daily['losses']} ❌\n"
                    f"WR     : "
                    f"{daily['win_rate']}%\n"
                    f"PnL    : "
                    f"{daily['pnl']:+.4f} USDT\n"
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

            if (now.hour == 23 and
                    now.minute == 59):
                daily = get_daily_stats()
                today = now.strftime("%d/%m/%Y")

                if daily:
                    msg = (
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"  DAILY REPORT\n"
                        f"  {today}\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"Symbol  : ETH/USDT\n"
                        f"Trades  : "
                        f"{daily['total']}\n"
                        f"Wins    : "
                        f"{daily['wins']} ✅\n"
                        f"Losses  : "
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
                        f"{daily['capital']:.4f} USDT\n"
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
#  Sab kuch yahan hota hai
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def run_trading_engine():
    """
    Main engine:
    1. Har 5s momentum check
    2. Signal mila = Entry
    3. TP/SL/MaxHold = Exit
    4. Repeat
    """
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

    print("[ENGINE] Started ✅")

    send_telegram(
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"  ETH MOMENTUM BOT v2.0\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Symbol  : ETH/USDT\n"
        f"Capital : {capital:.4f} USDT\n"
        f"Use     : "
        f"{capital * CAPITAL_USE / 100:.4f} USDT\n"
        f"Leverage: {LEVERAGE}x\n"
        f"Target  : {TP_PCT}%\n"
        f"SL      : {SL_PCT}%\n"
        f"Max Hold: {MAX_HOLD}s\n"
        f"Strategy: 30s Momentum\n"
        f"━━━━━━━━━━━━━━━━━━━━━━"
    )

    while True:
        try:
            now = datetime.now().strftime(
                "%H:%M:%S")

            # ── Momentum Check ────────────
            momentum, cur_price, move = (
                detect_momentum(ex))

            if cur_price == 0.0:
                time.sleep(SCAN_INTERVAL)
                continue

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
                momentum=momentum,
                last_signal=(
                    momentum
                    if position is None
                    else position),
            )

            # ══════════════════════════════
            #  POSITION MONITOR
            # ══════════════════════════════
            if position is not None:
                held = (
                    datetime.now() -
                    entry_time).seconds

                pnl_now = calc_pnl(
                    position,
                    entry_price,
                    cur_price,
                    pos_size)

                icon = (
                    "🟢" if pnl_now >= 0
                    else "🔴")

                print(
                    f"[{now}] {icon} "
                    f"{position} | "
                    f"PnL={pnl_now:+.4f} | "
                    f"Price={cur_price:.4f} | "
                    f"Held={held}s")

                # ── TP Hit ────────────────
                hit_tp = (
                    (position == "BUY" and
                     cur_price >= tp_price) or
                    (position == "SELL" and
                     cur_price <= tp_price))

                # ── SL Hit ────────────────
                hit_sl = (
                    (position == "BUY" and
                     cur_price <= sl_price) or
                    (position == "SELL" and
                     cur_price >= sl_price))

                # ── Max Hold ──────────────
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
                            if pnl_now >= 0
                            else "🔴")

                    pnl      = calc_pnl(
                        position,
                        entry_price,
                        cur_price,
                        pos_size)
                    capital += pnl
                    duration = f"{held}s"

                    save_capital(capital)
                    save_trade(
                        position,
                        entry_price,
                        cur_price,
                        pnl,
                        capital,
                        duration,
                        label)

                    if pnl > 0:
                        consecutive_losses = 0
                        cd = COOLDOWN_WIN
                    else:
                        consecutive_losses += 1
                        cd = (
                            COOLDOWN_2LOSS
                            if consecutive_losses >= 2
                            else COOLDOWN_LOSS)

                    print(
                        f"[CLOSED] {label} | "
                        f"PnL={pnl:+.4f} | "
                        f"Cap={capital:.4f}")

                    send_telegram(
                        f"{icon} {label}\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"Symbol : ETH\n"
                        f"Side   : {position}\n"
                        f"Entry  : "
                        f"{entry_price:.4f}\n"
                        f"Exit   : "
                        f"{cur_price:.4f}\n"
                        f"PnL    : "
                        f"{pnl:+.4f} USDT\n"
                        f"Capital: "
                        f"{capital:.4f} USDT\n"
                        f"Time   : {duration}\n"
                        f"Move   : {move:.3f}%\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━"
                    )

                    # Reset
                    position     = None
                    entry_price  = 0.0
                    entry_time   = None
                    pos_size     = 0.0
                    sl_price     = 0.0
                    tp_price     = 0.0
                    capital_used = 0.0
                    cooldown_end = (
                        time.time() + cd)
                    save_cooldown(cooldown_end)

                    update_state(
                        position=None,
                        capital_used=0.0,
                        capital=capital)

                    time.sleep(SCAN_INTERVAL)
                    continue

            # ══════════════════════════════
            #  COOLDOWN CHECK
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
                if momentum in ["UP", "DOWN"]:

                    # Spread check
                    if not check_spread(ex):
                        time.sleep(SCAN_INTERVAL)
                        continue

                    # Signal
                    signal = (
                        "BUY"
                        if momentum == "UP"
                        else "SELL")

                    # Capital
                    capital_used = (
                        capital *
                        CAPITAL_USE / 100)

                    # Position size
                    pos_size = (
                        (capital_used * LEVERAGE) /
                        cur_price)

                    # Entry
                    entry_price = cur_price
                    entry_time  = datetime.now()
                    position    = signal
                    cooldown_end = None

                    # TP / SL
                    if signal == "BUY":
                        tp_price = entry_price * (
                            1 + TP_PCT / 100)
                        sl_price = entry_price * (
                            1 - SL_PCT / 100)
                    else:
                        tp_price = entry_price * (
                            1 - TP_PCT / 100)
                        sl_price = entry_price * (
                            1 + SL_PCT / 100)

                    # Expected PnL
                    exp_win = round(
                        capital_used *
                        LEVERAGE *
                        TP_PCT / 100, 4)
                    exp_loss = round(
                        capital_used *
                        LEVERAGE *
                        SL_PCT / 100, 4)

                    print(
                        f"[OPENED] {position} | "
                        f"Entry={entry_price:.4f} | "
                        f"TP={tp_price:.4f} | "
                        f"SL={sl_price:.4f}")

                    send_telegram(
                        f"🚀 ENTRY\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"Symbol : ETH\n"
                        f"Side   : {position}\n"
                        f"Entry  : "
                        f"{entry_price:.4f}\n"
                        f"TP     : "
                        f"{tp_price:.4f}\n"
                        f"SL     : "
                        f"{sl_price:.4f}\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"Capital: "
                        f"{capital_used:.2f} USDT\n"
                        f"Leverage: {LEVERAGE}x\n"
                        f"Exposure: "
                        f"{capital_used*LEVERAGE:.2f} USDT\n"
                        f"Exp Win : +{exp_win} USDT\n"
                        f"Exp Loss: -{exp_loss} USDT\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"Momentum: {momentum}\n"
                        f"Move    : {move:.3f}%\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━"
                    )

                else:
                    print(
                        f"[{now}] FLAT | "
                        f"Momentum={momentum} | "
                        f"Price={cur_price:.4f}")

        except Exception as e:
            err = str(e)
            print(f"[ENGINE ERROR] {err}")
            if "429" in err:
                time.sleep(60)
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

    print("=" * 50)
    print("  ETH MOMENTUM BOT v2.0")
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
    print(f"  Target   : {TP_PCT}%")
    print(f"  SL       : {SL_PCT}%")
    print(f"  Max Hold : {MAX_HOLD}s")
    print(f"  Strategy : 30s Momentum")
    print(
        f"  Exp Win  : "
        f"+{CAPITAL * CAPITAL_USE / 100 * LEVERAGE * TP_PCT / 100:.2f} USDT")
    print(
        f"  Exp Loss : "
        f"-{CAPITAL * CAPITAL_USE / 100 * LEVERAGE * SL_PCT / 100:.2f} USDT")
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

    print(
        f"\n[INFO] Threads: {len(threads)}")
    print("[INFO] Bot Running 24/7 ✅")
    print("=" * 50)

    while True:
        time.sleep(60)
