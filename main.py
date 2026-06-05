"""
ETH High Frequency Scalping Bot v3.0
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Strategy : Order Book + Trade Flow 
           + Price Velocity
Exchange : MEXC Futures
Symbol   : ETH/USDT
Capital  : 10000 USDT
Leverage : 5x
TP       : 0.05%
SL       : 0.03%
Max Hold : 10 seconds

MEXC SAHI Fee:
Maker Fee : 0.00% (FREE!)
Taker Fee : 0.01% only
Total/Trade: 0.02%
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
from concurrent.futures import ThreadPoolExecutor

app = Flask(__name__)

@app.route('/')
def home():
    return "ETH HF Scalping Bot v3.0 Running!"

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
CAPITAL     = 10000.0
CAPITAL_USE = 90
LEVERAGE    = 5

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  MEXC SAHI FEE
#  Futures ETH/USDT:
#  Maker = 0.00% (limit order)
#  Taker = 0.01% (market order)
#  HF bot market orders use karta hai
#  isliye 0.01% entry + 0.01% exit
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

MEXC_MAKER_FEE = 0.0000   # 0.00% FREE!
MEXC_TAKER_FEE = 0.0001   # 0.01% only

# Entry pe market order = Taker
# Exit pe market order  = Taker
MEXC_ENTRY_FEE = MEXC_TAKER_FEE   # 0.01%
MEXC_EXIT_FEE  = MEXC_TAKER_FEE   # 0.01%
MEXC_TOTAL_FEE = MEXC_ENTRY_FEE + MEXC_EXIT_FEE  # 0.02%

# Fee Example:
# Capital Used = 9000 USDT
# Leverage 5x  = 45000 USDT exposure
# Entry Fee    = 45000 × 0.01% = 4.5 USDT
# Exit Fee     = 45000 × 0.01% = 4.5 USDT
# Total Fee    = 9 USDT per trade ✅

# ── Trade Config ──────────────────────────
TP_PCT   = 0.05    # 0.05% = 22.5 USDT gross
SL_PCT   = 0.03    # 0.03% stop loss
MAX_HOLD = 10      # 10 seconds max

# Net TP after fee:
# 22.5 - 9 = 13.5 USDT profit ✅

# ── Speed ─────────────────────────────────
SCAN_INTERVAL    = 0.05   # 50ms
ANALYSIS_WORKERS = 4      # Parallel threads

# ── Cooldown ──────────────────────────────
COOLDOWN_WIN   = 0.1
COOLDOWN_LOSS  = 0.5
COOLDOWN_2LOSS = 1.0

# ── Spread ────────────────────────────────
MAX_SPREAD = 0.05

# ── Order Book ────────────────────────────
OB_LEVELS    = 10
OB_IMBALANCE = 1.5

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
    "fees":     "fees_eth.json",
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
    "last_signal":  "WAIT",
    "ob_signal":    "FLAT",
    "flow_signal":  "FLAT",
    "velocity":     0.0,
    "total_fees":   0.0,
    "trade_count":  0,
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
#  MEXC FEE CALCULATOR (SAHI)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def calculate_mexc_fee(capital_used, leverage):
    """
    MEXC Futures Sahi Fee:

    Exposure   = capital_used × leverage
    Entry Fee  = exposure × 0.01%
    Exit Fee   = exposure × 0.01%
    Total Fee  = 0.02% of exposure

    Example:
    9000 × 5 = 45000 USDT exposure
    Entry     = 45000 × 0.0001 = 4.5 USDT
    Exit      = 45000 × 0.0001 = 4.5 USDT
    Total     = 9.0 USDT only ✅
    """
    exposure  = capital_used * leverage
    entry_fee = exposure * MEXC_ENTRY_FEE
    exit_fee  = exposure * MEXC_EXIT_FEE
    total_fee = entry_fee + exit_fee

    return {
        "exposure":  round(exposure, 4),
        "entry_fee": round(entry_fee, 4),
        "exit_fee":  round(exit_fee, 4),
        "total_fee": round(total_fee, 4),
    }


def calc_net_pnl(
        side, entry, exit_p,
        pos_size, capital_used, leverage):
    """
    Net PnL = Gross PnL - MEXC Fee (0.02%)

    Gross = price_diff × pos_size
    Fee   = exposure × 0.02%
    Net   = Gross - Fee
    """
    # Gross PnL
    if side == "BUY":
        gross_pnl = (exit_p - entry) * pos_size
    else:
        gross_pnl = (entry - exit_p) * pos_size

    # MEXC Fee (0.02% total)
    fees      = calculate_mexc_fee(
        capital_used, leverage)
    total_fee = fees["total_fee"]

    # Net PnL
    net_pnl = gross_pnl - total_fee

    return {
        "gross_pnl": round(gross_pnl, 6),
        "entry_fee": fees["entry_fee"],
        "exit_fee":  fees["exit_fee"],
        "total_fee": total_fee,
        "net_pnl":   round(net_pnl, 6),
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  CAPITAL
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def load_capital():
    try:
        with open(FILES["capital"], "r") as f:
            cap = float(f.read().strip())
            print(f"[CAPITAL] {cap} USDT")
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
        gross_pnl, net_pnl,
        total_fee, capital,
        duration, label):
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
                "date":      datetime.now()
                    .strftime("%d/%m/%Y"),
                "time":      datetime.now()
                    .strftime("%H:%M:%S"),
                "symbol":    "ETH",
                "side":      side,
                "entry":     round(entry, 4),
                "exit":      round(exit_p, 4),
                "gross_pnl": round(gross_pnl, 4),
                "fee":       round(total_fee, 4),
                "net_pnl":   round(net_pnl, 4),
                "capital":   round(capital, 4),
                "duration":  duration,
                "result":    (
                    "WIN" if net_pnl > 0
                    else "LOSS"),
                "label":     label,
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

    total     = len(trades)
    wins      = len([
        t for t in trades
        if t["result"] == "WIN"])
    losses    = total - wins
    win_rate  = round(
        (wins / total) * 100, 1)
    net_pnl   = round(
        sum(t["net_pnl"]   for t in trades), 4)
    gross_pnl = round(
        sum(t["gross_pnl"] for t in trades), 4)
    total_fees = round(
        sum(t["fee"]       for t in trades), 4)

    return {
        "total":      total,
        "wins":       wins,
        "losses":     losses,
        "win_rate":   win_rate,
        "net_pnl":    net_pnl,
        "gross_pnl":  gross_pnl,
        "total_fees": total_fees,
        "best":  round(
            max(t["net_pnl"] for t in trades), 4),
        "worst": round(
            min(t["net_pnl"] for t in trades), 4),
        "capital": trades[-1]["capital"],
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  EXCHANGE (MEXC)
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
                    "defaultType": "swap",
                    "adjustForTimeDifference": True,
                },
            })
            ex.load_markets()
            print("[INFO] MEXC Connected ✅")
            return ex
        except Exception as e:
            print(f"[RECONNECT] {e} — 30s...")
            time.sleep(30)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  CACHE (Fast Data)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

cache_lock = threading.Lock()
data_cache = {
    "ticker":       None,
    "orderbook":    None,
    "trades":       None,
    "ticker_ts":    0,
    "orderbook_ts": 0,
    "trades_ts":    0,
}

TICKER_TTL    = 0.05
ORDERBOOK_TTL = 0.1
TRADES_TTL    = 0.2


def safe_fetch_ticker(ex):
    now = time.time()
    with cache_lock:
        if (data_cache["ticker"] is not None and
                now - data_cache["ticker_ts"]
                < TICKER_TTL):
            return data_cache["ticker"]
    for i in range(3):
        try:
            t     = ex.fetch_ticker(SYMBOL)
            price = float(t["last"])
            with cache_lock:
                data_cache["ticker"]    = price
                data_cache["ticker_ts"] = time.time()
            return price
        except Exception as e:
            if "429" in str(e):
                time.sleep((i+1) * 2)
            else:
                time.sleep(0.1)
    return None


def safe_fetch_orderbook(ex, limit=10):
    now = time.time()
    with cache_lock:
        if (data_cache["orderbook"] is not None and
                now - data_cache["orderbook_ts"]
                < ORDERBOOK_TTL):
            return data_cache["orderbook"]
    for i in range(3):
        try:
            ob = ex.fetch_order_book(
                SYMBOL, limit=limit)
            with cache_lock:
                data_cache["orderbook"]    = ob
                data_cache["orderbook_ts"] = time.time()
            return ob
        except Exception as e:
            if "429" in str(e):
                time.sleep((i+1) * 2)
            else:
                time.sleep(0.1)
    return None


def safe_fetch_trades(ex, limit=50):
    now = time.time()
    with cache_lock:
        if (data_cache["trades"] is not None and
                now - data_cache["trades_ts"]
                < TRADES_TTL):
            return data_cache["trades"]
    for i in range(3):
        try:
            trades = ex.fetch_trades(
                SYMBOL, limit=limit)
            with cache_lock:
                data_cache["trades"]    = trades
                data_cache["trades_ts"] = time.time()
            return trades
        except Exception as e:
            if "429" in str(e):
                time.sleep((i+1) * 2)
            else:
                time.sleep(0.1)
    return None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  TELEGRAM (Async)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

telegram_queue = []
telegram_lock  = threading.Lock()

def send_telegram(message):
    with telegram_lock:
        telegram_queue.append(message)

def telegram_worker():
    url = (
        f"https://api.telegram.org/bot"
        f"{BOT_TOKEN}/sendMessage")
    while True:
        try:
            msg = None
            with telegram_lock:
                if telegram_queue:
                    msg = telegram_queue.pop(0)
            if msg:
                for attempt in range(3):
                    try:
                        requests.post(
                            url,
                            data={
                                "chat_id": CHAT_ID,
                                "text": f"[SCALP] {msg}",
                            },
                            timeout=10)
                        break
                    except Exception:
                        time.sleep(1)
            else:
                time.sleep(0.1)
        except Exception as e:
            print(f"[TG ERROR] {e}")
            time.sleep(1)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  ANALYSIS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def analyze_orderbook(ex):
    try:
        ob = safe_fetch_orderbook(ex, limit=OB_LEVELS)
        if ob is None:
            return "FLAT", 0.0, 0.0, 0.0

        bids = ob["bids"]
        asks = ob["asks"]

        if not bids or not asks:
            return "FLAT", 0.0, 0.0, 0.0

        best_bid = float(bids[0][0])
        best_ask = float(asks[0][0])
        spread   = (
            (best_ask - best_bid) /
            best_bid) * 100

        if spread > MAX_SPREAD:
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

        mid = (best_bid + best_ask) / 2
        return signal, mid, spread, ratio

    except Exception as e:
        print(f"[OB ERROR] {e}")
        return "FLAT", 0.0, 0.0, 0.0


def analyze_trade_flow(ex):
    try:
        trades = safe_fetch_trades(ex, limit=50)
        if not trades:
            return "FLAT", 0.0, 0.0

        buy_vol  = 0.0
        sell_vol = 0.0

        for t in trades:
            side = t.get("side", "")
            amt  = float(t.get("amount", 0))
            if side == "buy":
                buy_vol  += amt
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

        return signal, buy_vol, sell_vol

    except Exception as e:
        print(f"[FLOW ERROR] {e}")
        return "FLAT", 0.0, 0.0


price_history = []
price_lock    = threading.Lock()

def update_price_history(price):
    with price_lock:
        price_history.append({
            "price": price,
            "time":  time.time(),
        })
        cutoff = time.time() - 10
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

            change = last - first
            pct    = (change / first) * 100

            if pct > 0.008:
                signal = "BUY"
            elif pct < -0.008:
                signal = "SELL"
            else:
                signal = "FLAT"

            return signal, pct

    except Exception as e:
        print(f"[VEL ERROR] {e}")
        return "FLAT", 0.0


def get_combined_signal(ob_sig, flow_sig, vel_sig):
    signals    = [ob_sig, flow_sig, vel_sig]
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

            pos     = st["position"]
            price   = st["last_price"]
            capital = st["capital"]
            entry   = st["entry_price"]
            psize   = st["pos_size"]
            etime   = st["entry_time"]
            ob_sig  = st["ob_signal"]
            fl_sig  = st["flow_signal"]

            daily = get_daily_stats()

            cap_used = capital * CAPITAL_USE / 100

            if (pos is not None and
                    etime is not None and
                    price > 0):

                pnl_data = calc_net_pnl(
                    pos, entry, price,
                    psize, cap_used, LEVERAGE)

                icon = (
                    "🟢"
                    if pnl_data["net_pnl"] >= 0
                    else "🔴")

                msg = (
                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"  ETH BOT UPDATE\n"
                    f"  {now}\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"{icon} {pos}\n"
                    f"Entry    : {entry:.4f}\n"
                    f"Price    : {price:.4f}\n"
                    f"Gross    : "
                    f"{pnl_data['gross_pnl']:+.4f}\n"
                    f"Fee(0.02%): "
                    f"-{pnl_data['total_fee']:.4f}\n"
                    f"Net PnL  : "
                    f"{pnl_data['net_pnl']:+.4f} USDT\n"
                    f"Capital  : {capital:.4f} USDT\n")
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
                    f"Capital  : {capital:.4f} USDT\n")

            if daily:
                msg += (
                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"TODAY\n"
                    f"Trades   : {daily['total']}\n"
                    f"Wins     : {daily['wins']} ✅\n"
                    f"Losses   : {daily['losses']} ❌\n"
                    f"WR       : {daily['win_rate']}%\n"
                    f"Gross    : "
                    f"{daily['gross_pnl']:+.4f}\n"
                    f"Fees Paid: "
                    f"-{daily['total_fees']:.4f} USDT\n"
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
                        f"Exchange : MEXC\n"
                        f"Trades   : {daily['total']}\n"
                        f"Wins     : {daily['wins']} ✅\n"
                        f"Losses   : "
                        f"{daily['losses']} ❌\n"
                        f"Win Rate : {daily['win_rate']}%\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"Gross PnL: "
                        f"{daily['gross_pnl']:+.4f}\n"
                        f"Fees Paid: "
                        f"-{daily['total_fees']:.4f} USDT\n"
                        f"Net PnL  : "
                        f"{daily['net_pnl']:+.4f} USDT\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"Best     : +{daily['best']:.4f}\n"
                        f"Worst    : {daily['worst']:.4f}\n"
                        f"Capital  : "
                        f"{daily['capital']:.4f} USDT\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"MEXC Fee : 0.02%/trade\n"
                        f"Maker    : 0.00% FREE\n"
                        f"Taker    : 0.01% only\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━")
                else:
                    msg = (
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"DAILY REPORT - {today}\n"
                        f"Koi trade nahi hua\n"
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
    cooldown_end       = load_cooldown()
    consecutive_losses = 0
    trade_count        = 0

    print("[ENGINE] Started ✅")

    # Fee example
    cap_use  = capital * CAPITAL_USE / 100
    fees_ex  = calculate_mexc_fee(cap_use, LEVERAGE)

    send_telegram(
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"  ETH HF BOT v3.0\n"
        f"  MEXC Exchange\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Capital  : {capital:.2f} USDT\n"
        f"Use      : {cap_use:.2f} USDT\n"
        f"Leverage : {LEVERAGE}x\n"
        f"Exposure : {fees_ex['exposure']:.2f} USDT\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"MEXC FEE (SAHI):\n"
        f"Maker Fee: 0.00% FREE ✅\n"
        f"Taker Fee: 0.01% only ✅\n"
        f"Entry Fee: "
        f"{fees_ex['entry_fee']:.4f} USDT\n"
        f"Exit Fee : "
        f"{fees_ex['exit_fee']:.4f} USDT\n"
        f"Total Fee: "
        f"{fees_ex['total_fee']:.4f} USDT\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"TP    : {TP_PCT}% ✅\n"
        f"SL    : {SL_PCT}%\n"
        f"Scan  : {SCAN_INTERVAL*1000:.0f}ms\n"
        f"━━━━━━━━━━━━━━━━━━━━━━"
    )

    executor = ThreadPoolExecutor(
        max_workers=ANALYSIS_WORKERS)

    while True:
        try:
            loop_start = time.time()

            # ── Price ─────────────────────
            cur_price = safe_fetch_ticker(ex)
            if cur_price is None:
                time.sleep(SCAN_INTERVAL)
                continue

            update_price_history(cur_price)

            # ── Parallel Analysis ─────────
            f_ob   = executor.submit(
                analyze_orderbook, ex)
            f_flow = executor.submit(
                analyze_trade_flow, ex)
            f_vel  = executor.submit(
                analyze_velocity)

            ob_signal, mid_price, spread, ob_ratio = (
                f_ob.result(timeout=2))
            flow_signal, buy_vol, sell_vol = (
                f_flow.result(timeout=2))
            vel_signal, velocity = (
                f_vel.result(timeout=1))

            # ── Combined Signal ───────────
            final_signal, strength = (
                get_combined_signal(
                    ob_signal,
                    flow_signal,
                    vel_signal))

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
                ob_signal=ob_signal,
                flow_signal=flow_signal,
                velocity=velocity,
                last_signal=final_signal,
                trade_count=trade_count,
            )

            # ══════════════════════════════
            #  POSITION MONITOR
            # ══════════════════════════════
            if position is not None:
                held = (
                    datetime.now() -
                    entry_time).total_seconds()

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
                    # Net PnL with MEXC fee
                    final_pnl = calc_net_pnl(
                        position, entry_price,
                        cur_price, pos_size,
                        capital_used, LEVERAGE)

                    gross_pnl = final_pnl["gross_pnl"]
                    total_fee = final_pnl["total_fee"]
                    net_pnl   = final_pnl["net_pnl"]

                    if hit_tp:
                        label = "TAKE PROFIT ✅"
                        icon  = "🟢"
                    elif hit_sl:
                        label = "STOP LOSS ❌"
                        icon  = "🔴"
                    else:
                        label = "MAX HOLD ⏰"
                        icon  = (
                            "🟢" if net_pnl >= 0
                            else "🔴")

                    capital     += net_pnl
                    duration     = f"{held:.1f}s"
                    trade_count += 1

                    save_capital(capital)
                    save_trade(
                        position,
                        entry_price,
                        cur_price,
                        gross_pnl,
                        net_pnl,
                        total_fee,
                        capital,
                        duration,
                        label)

                    if net_pnl > 0:
                        consecutive_losses = 0
                        cd = COOLDOWN_WIN
                    else:
                        consecutive_losses += 1
                        cd = (
                            COOLDOWN_2LOSS
                            if consecutive_losses >= 2
                            else COOLDOWN_LOSS)

                    print(
                        f"[#{trade_count}] "
                        f"{label} | "
                        f"Gross={gross_pnl:+.4f} | "
                        f"Fee=-{total_fee:.4f} | "
                        f"Net={net_pnl:+.4f} | "
                        f"Cap={capital:.4f}")

                    send_telegram(
                        f"{icon} {label}\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"Trade #  : {trade_count}\n"
                        f"Side     : {position}\n"
                        f"Entry    : "
                        f"{entry_price:.4f}\n"
                        f"Exit     : "
                        f"{cur_price:.4f}\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"Gross PnL: "
                        f"{gross_pnl:+.4f} USDT\n"
                        f"MEXC Fee : "
                        f"-{total_fee:.4f} USDT\n"
                        f"Net PnL  : "
                        f"{net_pnl:+.4f} USDT\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"Capital  : "
                        f"{capital:.4f} USDT\n"
                        f"Time     : {duration}\n"
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
                    cooldown_end = time.time() + cd
                    save_cooldown(cooldown_end)
                    update_state(
                        position=None,
                        capital_used=0.0,
                        capital=capital)

                    elapsed = time.time() - loop_start
                    time.sleep(max(
                        0, SCAN_INTERVAL - elapsed))
                    continue

            # ══════════════════════════════
            #  COOLDOWN
            # ══════════════════════════════
            if (cooldown_end is not None and
                    time.time() < cooldown_end):
                elapsed = time.time() - loop_start
                time.sleep(max(
                    0, SCAN_INTERVAL - elapsed))
                continue

            # ══════════════════════════════
            #  ENTRY
            # ══════════════════════════════
            if position is None:
                if final_signal in ["BUY", "SELL"]:
                    if spread > MAX_SPREAD:
                        elapsed = (
                            time.time() - loop_start)
                        time.sleep(max(
                            0, SCAN_INTERVAL - elapsed))
                        continue

                    capital_used = (
                        capital * CAPITAL_USE / 100)
                    pos_size = (
                        (capital_used * LEVERAGE) /
                        cur_price)

                    entry_price  = cur_price
                    entry_time   = datetime.now()
                    position     = final_signal
                    cooldown_end = None

                    if final_signal == "BUY":
                        tp_price = entry_price * (
                            1 + TP_PCT / 100)
                        sl_price = entry_price * (
                            1 - SL_PCT / 100)
                    else:
                        tp_price = entry_price * (
                            1 - TP_PCT / 100)
                        sl_price = entry_price * (
                            1 + SL_PCT / 100)

                    fees = calculate_mexc_fee(
                        capital_used, LEVERAGE)

                    # Net expected
                    exp_gross_win = round(
                        capital_used * LEVERAGE *
                        TP_PCT / 100, 4)
                    exp_net_win = round(
                        exp_gross_win -
                        fees["total_fee"], 4)

                    exp_gross_loss = round(
                        capital_used * LEVERAGE *
                        SL_PCT / 100, 4)
                    exp_net_loss = round(
                        exp_gross_loss +
                        fees["total_fee"], 4)

                    print(
                        f"[ENTRY #{trade_count+1}] "
                        f"{position} | "
                        f"Price={entry_price:.4f} | "
                        f"Fee={fees['total_fee']:.4f} | "
                        f"ExpNet=+{exp_net_win}")

                    send_telegram(
                        f"🚀 ENTRY #{trade_count+1}\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"Side     : {position}\n"
                        f"Entry    : "
                        f"{entry_price:.4f}\n"
                        f"TP       : "
                        f"{tp_price:.4f}\n"
                        f"SL       : "
                        f"{sl_price:.4f}\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"Capital  : "
                        f"{capital_used:.2f} USDT\n"
                        f"Exposure : "
                        f"{fees['exposure']:.2f} USDT\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"MEXC Fee :\n"
                        f"Entry    : "
                        f"-{fees['entry_fee']:.4f}\n"
                        f"Exit     : "
                        f"-{fees['exit_fee']:.4f}\n"
                        f"Total    : "
                        f"-{fees['total_fee']:.4f} USDT\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"Exp Win  : "
                        f"+{exp_net_win} USDT ✅\n"
                        f"Exp Loss : "
                        f"-{exp_net_loss} USDT\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"OB       : {ob_signal}\n"
                        f"Flow     : {flow_signal}\n"
                        f"Velocity : {vel_signal}\n"
                        f"Strength : {strength}/3\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━"
                    )

            # ── Speed Control ─────────────
            elapsed = time.time() - loop_start
            sleep_t = max(0, SCAN_INTERVAL - elapsed)
            if sleep_t > 0:
                time.sleep(sleep_t)

        except Exception as e:
            err = str(e)
            print(f"[ENGINE ERROR] {err}")
            if "429" in err:
                time.sleep(5)
            elif ("connection" in err.lower() or
                  "timeout" in err.lower()):
                ex = get_exchange()
                time.sleep(2)
            else:
                time.sleep(0.5)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  START
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

if __name__ == "__main__":

    cap_use  = CAPITAL * CAPITAL_USE / 100
    fees_ex  = calculate_mexc_fee(cap_use, LEVERAGE)
    exposure = fees_ex["exposure"]

    exp_gross_win  = round(
        exposure * TP_PCT / 100, 4)
    exp_net_win    = round(
        exp_gross_win - fees_ex["total_fee"], 4)
    exp_gross_loss = round(
        exposure * SL_PCT / 100, 4)
    exp_net_loss   = round(
        exp_gross_loss + fees_ex["total_fee"], 4)

    trades_per_day = int(86400 / SCAN_INTERVAL)

    print("=" * 50)
    print("  ETH HF SCALPING BOT v3.0 — MEXC")
    print("=" * 50)
    print(f"  Capital    : {CAPITAL} USDT")
    print(f"  Use        : {cap_use} USDT")
    print(f"  Leverage   : {LEVERAGE}x")
    print(f"  Exposure   : {exposure} USDT")
    print("-" * 50)
    print(f"  MEXC FEE (SAHI):")
    print(f"  Maker Fee  : 0.00% FREE ✅")
    print(f"  Taker Fee  : 0.01% only ✅")
    print(f"  Entry Fee  : {fees_ex['entry_fee']} USDT")
    print(f"  Exit Fee   : {fees_ex['exit_fee']} USDT")
    print(f"  Total/Trade: {fees_ex['total_fee']} USDT")
    print("-" * 50)
    print(f"  Gross Win  : +{exp_gross_win} USDT")
    print(f"  Net Win    : +{exp_net_win} USDT ✅")
    print(f"  Gross Loss : -{exp_gross_loss} USDT")
    print(f"  Net Loss   : -{exp_net_loss} USDT")
    print("-" * 50)
    print(f"  Scan Speed : {SCAN_INTERVAL*1000:.0f}ms")
    print(f"  Est Trades : ~{trades_per_day:,}/day")
    print("=" * 50)

    threads = [
        threading.Thread(
            target=run_server,
            name="Flask",
            daemon=True),
        threading.Thread(
            target=telegram_worker,
            name="Telegram",
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
        time.sleep(0.3)

    print(f"[INFO] Bot Running 24/7 ✅")
    print("=" * 50)

    while True:
        time.sleep(60)
