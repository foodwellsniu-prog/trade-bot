"""
ETH High Frequency Scalping Bot v3.0
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Exchange : MEXC (Zero Maker Fee)
Strategy : Order Book + Trade Flow 
           + Price Velocity
Symbol   : ETH/USDT
Capital  : 1052 USDT
Leverage : 5x
TP       : 0.05%
SL       : 0.03%
Max Hold : 30 seconds
Fee      : 0.01% Taker (MEXC)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import ccxt
import pandas as pd
import numpy as np
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
CAPITAL     = 1052.0
CAPITAL_USE = 90
LEVERAGE    = 5

# ── Trade Config ──────────────────────────
TP_PCT   = 0.05    # 0.05% target
SL_PCT   = 0.03    # 0.03% stop loss
MAX_HOLD = 30      # 30 seconds ← Updated

# ── MEXC Fee ──────────────────────────────
TAKER_FEE = 0.01   # 0.01% taker fee MEXC

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

# ── Update ────────────────────────────────
UPDATE_INTERVAL = 1800


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  FEE CALCULATOR (MEXC)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def calc_fees(exposure):
    """
    MEXC Taker Fee = 0.01%
    Entry fee + Exit fee dono
    """
    entry_fee = exposure * TAKER_FEE / 100
    exit_fee  = exposure * TAKER_FEE / 100
    return round(entry_fee + exit_fee, 6)

def calc_net_tp(exposure):
    """Net Profit after fees"""
    gross = exposure * TP_PCT / 100
    fees  = calc_fees(exposure)
    return round(gross - fees, 6)

def calc_net_sl(exposure):
    """Net Loss after fees"""
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
               duration, label):
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
#  PnL CALCULATOR
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def calc_pnl(side, entry, exit_p, pos_size):
    """Gross PnL before fees"""
    if side == "BUY":
        return (exit_p - entry) * pos_size
    else:
        return (entry - exit_p) * pos_size


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
            psize    = st["pos_size"]
            etime    = st["entry_time"]
            ob_sig   = st["ob_signal"]
            fl_sig   = st["flow_signal"]
            fees     = st["fees"]
            exposure = st["exposure"]

            daily = get_daily_stats()

            if (pos is not None and
                    etime is not None and
                    price > 0):

                gross_pnl = calc_pnl(
                    pos, entry,
                    price, psize)
                net_pnl = gross_pnl - fees
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

    sample_exposure = (
        CAPITAL * CAPITAL_USE / 100 *
        LEVERAGE)
    sample_fees    = calc_fees(sample_exposure)
    sample_net_win = calc_net_tp(sample_exposure)
    sample_net_loss= calc_net_sl(sample_exposure)

    print("[ENGINE] Started ✅")

    send_telegram(
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"  ETH HF BOT v3.0\n"
        f"  MEXC Exchange\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Symbol   : ETH/USDT\n"
        f"Capital  : {capital:.4f} USDT\n"
        f"Use (90%): "
        f"{capital * CAPITAL_USE / 100:.4f}"
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
        f"Strategy : OB+Flow+Velocity\n"
        f"Scan     : Har {SCAN_INTERVAL}s\n"
        f"━━━━━━━━━━━━━━━━━━━━━━"
    )

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
                    f"Held={held}s/{MAX_HOLD}s")

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
                        label)

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

                    if spread > MAX_SPREAD:
                        print(
                            f"[SKIP] "
                            f"Spread "
                            f"{spread:.4f}%")
                        time.sleep(SCAN_INTERVAL)
                        continue

                    # Capital & Exposure
                    capital_used = (
                        capital *
                        CAPITAL_USE / 100)
                    exposure = (
                        capital_used * LEVERAGE)

                    # Position size
                    pos_size = (
                        exposure / cur_price)

                    # MEXC Fee calculate
                    trade_fees = calc_fees(
                        exposure)

                    entry_price  = cur_price
                    entry_time   = datetime.now()
                    position     = final_signal
                    cooldown_end = None

                    # Expected Net PnL
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
                        f"Fees={trade_fees:.4f} | "
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
    print("  Order Book + Flow + Velocity")
    print("=" * 50)
    print(f"  Symbol    : ETH/USDT")
    print(f"  Exchange  : MEXC")
    print(f"  Capital   : {CAPITAL} USDT")
    print(f"  Use (90%) : {cap_use} USDT")
    print(f"  Leverage  : {LEVERAGE}x")
    print(f"  Exposure  : {exposure} USDT")
    print(f"  TP        : {TP_PCT}%")
    print(f"  SL        : {SL_PCT}%")
    print(f"  Max Hold  : {MAX_HOLD}s ✅")
    print(f"  Taker Fee : {TAKER_FEE}%")
    print(f"  Fee/Trade : {fees_per_trade} USDT")
    print(f"  Net Win   : +{net_win} USDT")
    print(f"  Net Loss  : -{net_loss} USDT")
    print(f"  Scan      : Har {SCAN_INTERVAL}s")
    print("=" * 50)
    print(f"  RR Ratio  : "
          f"1:{round(net_win/net_loss, 2)}")
    print(f"  Min WR Req: "
          f"{round(net_loss/(net_win+net_loss)*100,1)}%")
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
