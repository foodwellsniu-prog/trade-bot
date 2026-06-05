"""
ETH Market Making Paper Trading Bot v6.0
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PAPER TRADING MODE
Real market data
Simulated orders
Zero risk!

Jab price hamare bid pe aaye
= Buy simulate karo
Jab price hamare ask pe aaye  
= Sell simulate karo
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import ccxt
import requests
import threading
import time
import json
import os
import numpy as np
from flask import Flask
from datetime import (
    datetime, timezone, timedelta)
from collections import deque

app = Flask(__name__)

@app.route('/')
def home():
    return "ETH MM Paper Trading v6.0 ✅"

def run_server():
    port = int(
        os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  CONFIG
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SYMBOL    = "ETH/USDT:USDT"
BOT_TOKEN = "8161773850:AAFcWw3UnlSe2TrMooB2uvgZQZUqIW0zW2w"
CHAT_ID   = "7102976298"

# ── Capital (Simulated) ───────────────────
CAPITAL     = 10000.0   # Simulated capital
CAPITAL_USE = 80        # 80%
LEVERAGE    = 5

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  PAPER TRADING CONFIG
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Spread config
MIN_HALF_SPREAD  = 0.005
BASE_HALF_SPREAD = 0.01
MAX_HALF_SPREAD  = 0.03

# Volatility
VOL_LOW  = 0.005
VOL_HIGH = 0.05

# Levels
LEVELS           = 3
LEVEL_MULTIPLIER = [1.0, 2.0, 3.0]
LEVEL_QTY        = [0.50, 0.30, 0.20]

# Inventory
MAX_INV       = 3.0
HEDGE_INV     = 2.0
INV_STOP_LOSS = -80.0
SKEW_FACTOR   = 0.01

# Fee (Simulated)
MAKER_FEE = 0.0000   # 0% maker
TAKER_FEE = 0.0001   # 0.01% hedge

# Speed
SCAN_INTERVAL  = 0.5    # 500ms
MAX_MKT_SPREAD = 1.0    # Wide allowed
UPDATE_INTERVAL = 1800  # 30 min
VOL_WINDOW     = 30


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  FILES
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

FILES = {
    "capital": "paper_capital.txt",
    "history": "paper_history.json",
    "stats":   "paper_stats.json",
}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  STATE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

state_lock = threading.Lock()
state = {
    "mid":           0.0,
    "best_bid":      0.0,
    "best_ask":      0.0,
    "mkt_spread":    0.0,
    "volatility":    0.0,
    "dyn_spread":    BASE_HALF_SPREAD,
    "vol_label":     "NORMAL",

    # Simulated orders
    "sim_bids":      [],
    "sim_asks":      [],

    # Inventory
    "inventory":     0.0,
    "avg_price":     0.0,
    "inv_pnl":       0.0,
    "skew":          0.0,

    # Capital
    "capital":       CAPITAL,
    "start_capital": CAPITAL,

    # Stats
    "trade_count":   0,
    "buy_fills":     0,
    "sell_fills":    0,
    "gross_profit":  0.0,
    "hedge_cost":    0.0,
    "net_profit":    0.0,
    "best_trade":    0.0,
    "worst_trade":   0.0,
    "total_volume":  0.0,
    "win_trades":    0,
    "loss_trades":   0,

    # Status
    "cycles":        0,
    "start_time":    time.time(),
    "mode":          "PAPER TRADING",
}

def update_state(**kwargs):
    with state_lock:
        for k, v in kwargs.items():
            if k in state:
                state[k] = v

def get_all_state():
    with state_lock:
        return dict(state)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  CAPITAL
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def load_capital():
    try:
        with open(
                FILES["capital"], "r") as f:
            cap = float(f.read().strip())
            print(
                f"[PAPER] Capital: "
                f"{cap:.2f} USDT")
            return cap
    except Exception:
        save_capital(CAPITAL)
        return CAPITAL

def save_capital(cap):
    try:
        with open(
                FILES["capital"], "w") as f:
            f.write(str(round(cap, 6)))
    except Exception as e:
        print(f"[CAP ERR] {e}")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  HISTORY
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

history_lock = threading.Lock()

def save_trade(
        ttype, price, qty,
        profit, capital, num,
        note=""):
    try:
        with history_lock:
            try:
                with open(
                        FILES["history"],
                        "r",
                        encoding="utf-8") as f:
                    h = json.load(f)
            except Exception:
                h = []

            h.append({
                "num":     num,
                "date":    datetime.now()
                    .strftime("%d/%m/%Y"),
                "time":    datetime.now()
                    .strftime(
                        "%H:%M:%S.%f")[:-3],
                "type":    ttype,
                "price":   round(price, 4),
                "qty":     round(qty, 6),
                "profit":  round(profit, 6),
                "capital": round(capital, 4),
                "note":    note,
                "mode":    "PAPER",
            })

            if len(h) > 100000:
                h = h[-100000:]

            with open(
                    FILES["history"],
                    "w",
                    encoding="utf-8") as f:
                json.dump(h, f, indent=2)

    except Exception as e:
        print(f"[HIST ERR] {e}")


def get_daily_stats():
    try:
        with open(
                FILES["history"],
                "r",
                encoding="utf-8") as f:
            h = json.load(f)
    except Exception:
        return None

    today  = datetime.now().strftime(
        "%d/%m/%Y")
    trades = [
        t for t in h
        if t["date"] == today]

    if not trades:
        return None

    total  = len(trades)
    buys   = len([
        t for t in trades
        if t["type"] == "BUY_FILL"])
    sells  = len([
        t for t in trades
        if t["type"] == "SELL_FILL"])
    hedges = len([
        t for t in trades
        if t["type"] == "HEDGE"])
    gross  = round(sum(
        t["profit"] for t in trades
        if t["type"] in [
            "BUY_FILL",
            "SELL_FILL"]), 4)
    hcost  = round(sum(
        t["profit"] for t in trades
        if t["type"] == "HEDGE"), 4)
    net    = round(gross + hcost, 4)
    vol    = round(sum(
        t["price"] * t["qty"]
        for t in trades), 2)

    profits = [
        t["profit"] for t in trades
        if t["type"] == "SELL_FILL"]
    best  = round(
        max(profits) if profits else 0, 4)
    worst = round(
        min(profits) if profits else 0, 4)
    wins  = len([
        p for p in profits if p > 0])
    losses = len([
        p for p in profits if p <= 0])

    hours  = max(1, len(set(
        t["time"][:2]
        for t in trades)))
    per_hr = round(net / hours, 4)

    return {
        "total":   total,
        "buys":    buys,
        "sells":   sells,
        "hedges":  hedges,
        "gross":   gross,
        "hcost":   hcost,
        "net":     net,
        "volume":  vol,
        "best":    best,
        "worst":   worst,
        "wins":    wins,
        "losses":  losses,
        "per_hr":  per_hr,
        "capital": trades[-1]["capital"],
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  EXCHANGE (Read Only - No API needed)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def get_exchange():
    while True:
        try:
            # No API key needed
            # Public data only
            ex = ccxt.mexc({
                "enableRateLimit": True,
                "rateLimit":       100,
                "options": {
                    "defaultType":
                        "swap",
                },
            })
            ex.load_markets()
            print(
                "[MEXC] Public "
                "Connected ✅")
            return ex
        except Exception as e:
            print(
                f"[RECONNECT] {e}")
            time.sleep(15)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  VOLATILITY
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

price_buf = deque(maxlen=VOL_WINDOW)
vol_lock  = threading.Lock()

def add_price(price):
    with vol_lock:
        price_buf.append(price)

def get_volatility():
    with vol_lock:
        if len(price_buf) < 3:
            return 0.0
        prices = list(price_buf)

    returns = []
    for i in range(1, len(prices)):
        if prices[i-1] > 0:
            r = abs(
                (prices[i] -
                 prices[i-1]) /
                prices[i-1] * 100)
            returns.append(r)

    return float(
        np.mean(returns)
        if returns else 0.0)

def calc_dynamic_spread(vol):
    if vol < VOL_LOW:
        return MAX_HALF_SPREAD, "LOW VOL"
    elif vol > VOL_HIGH:
        return MIN_HALF_SPREAD, "HIGH VOL"
    else:
        ratio  = (
            (vol - VOL_LOW) /
            (VOL_HIGH - VOL_LOW))
        spread = (
            MAX_HALF_SPREAD -
            ratio * (
                MAX_HALF_SPREAD -
                MIN_HALF_SPREAD))
        return round(
            max(MIN_HALF_SPREAD,
                min(MAX_HALF_SPREAD,
                    spread)), 4), "NORMAL"

def calc_skew(inventory):
    return round(
        -inventory * SKEW_FACTOR, 4)

def calc_levels(
        mid, half_spread,
        skew, total_qty):
    adj   = mid + skew
    bids  = []
    asks  = []
    for i in range(LEVELS):
        m   = LEVEL_MULTIPLIER[i]
        q   = round(
            total_qty * LEVEL_QTY[i], 4)
        q   = max(0.001, q)
        bids.append({
            "level": i+1,
            "price": round(
                adj - half_spread * m, 2),
            "qty":   q,
        })
        asks.append({
            "level": i+1,
            "price": round(
                adj + half_spread * m, 2),
            "qty":   q,
        })
    return bids, asks


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  TELEGRAM
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

tg_q    = []
tg_lock = threading.Lock()

def send_telegram(msg):
    with tg_lock:
        tg_q.append(str(msg))

def telegram_worker():
    url = (
        f"https://api.telegram.org"
        f"/bot{BOT_TOKEN}/sendMessage")
    while True:
        try:
            msg = None
            with tg_lock:
                if tg_q:
                    msg = tg_q.pop(0)
            if msg:
                for _ in range(3):
                    try:
                        requests.post(
                            url,
                            data={
                                "chat_id":
                                    CHAT_ID,
                                "text":
                                    f"[PAPER]\n"
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
#  PERIODIC UPDATE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def run_update():
    time.sleep(300)
    while True:
        try:
            st    = get_all_state()
            stats = get_daily_stats()
            now   = datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S")

            cap    = st["capital"]
            s_cap  = st["start_capital"]
            net    = st["net_profit"]
            bf     = st["buy_fills"]
            sf     = st["sell_fills"]
            tc     = st["trade_count"]
            inv    = st["inventory"]
            mid    = st["mid"]
            vol    = st["volatility"]
            ds     = st["dyn_spread"]
            vl     = st["vol_label"]
            cyc    = st["cycles"]
            ipl    = st["inv_pnl"]
            skew   = st["skew"]
            growth = round(
                cap - s_cap, 4)
            grow_p = round(
                growth / s_cap * 100, 4)

            msg = (
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f" 📝 PAPER TRADING\n"
                f"  MM BOT v6.0\n"
                f"  {now}\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🔵 MODE: PAPER TRADING\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"MARKET\n"
                f"ETH Price: {mid:.4f}\n"
                f"Vol      : {vol:.4f}%\n"
                f"Mkt Type : {vl}\n"
                f"Dyn Sprd : ±{ds:.4f}\n"
                f"Skew     : {skew:+.4f}\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"INVENTORY\n"
                f"ETH Held : {inv:.4f}\n"
                f"Value    : "
                f"{inv*mid:.2f} USDT\n"
                f"Inv PnL  : "
                f"{ipl:+.4f} USDT\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"SIMULATED STATS\n"
                f"Cycles   : {cyc}\n"
                f"Trades   : {tc}\n"
                f"BuyFills : {bf}\n"
                f"SellFills: {sf}\n"
                f"Net PnL  : "
                f"{net:+.4f} USDT\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"CAPITAL\n"
                f"Start    : "
                f"{s_cap:.2f} USDT\n"
                f"Current  : "
                f"{cap:.4f} USDT\n"
                f"Growth   : "
                f"{growth:+.4f} USDT\n"
                f"ROI      : "
                f"{grow_p:+.4f}%\n"
                f"━━━━━━━━━━━━━━━━━━━━━━")

            if stats:
                ph  = stats["per_hr"]
                pd  = round(ph * 24, 4)
                pm  = round(pd * 30, 2)
                wr  = round(
                    stats["wins"] /
                    max(1,
                        stats["wins"] +
                        stats["losses"])
                    * 100, 1)
                msg += (
                    f"\nTODAY PAPER STATS\n"
                    f"Total    : "
                    f"{stats['total']}\n"
                    f"Buys     : "
                    f"{stats['buys']}\n"
                    f"Sells    : "
                    f"{stats['sells']}\n"
                    f"Win Rate : {wr}%\n"
                    f"Volume   : "
                    f"${stats['volume']:,.2f}\n"
                    f"Gross    : "
                    f"{stats['gross']:+.4f}\n"
                    f"Net PnL  : "
                    f"{stats['net']:+.4f}\n"
                    f"Per Hour : "
                    f"+{ph:.4f} USDT\n"
                    f"Per Day~ : "
                    f"+{pd:.4f} USDT\n"
                    f"Monthly~ : "
                    f"+{pm:.2f} USDT\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━")

            send_telegram(msg)

        except Exception as e:
            print(f"[UPD ERR] {e}")

        time.sleep(UPDATE_INTERVAL)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  DAILY REPORT
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def run_daily():
    while True:
        try:
            ist = timezone(timedelta(
                hours=5, minutes=30))
            now = datetime.now(ist)
            if (now.hour == 23 and
                    now.minute == 59):
                stats = get_daily_stats()
                today = now.strftime(
                    "%d/%m/%Y")
                st    = get_all_state()
                cap   = st["capital"]
                scap  = st["start_capital"]

                if stats:
                    growth = round(
                        cap - scap, 4)
                    roi    = round(
                        growth/scap*100, 4)
                    pd     = round(
                        stats["net"], 4)
                    pm     = round(
                        pd * 30, 2)
                    wr     = round(
                        stats["wins"] /
                        max(1,
                            stats["wins"]+
                            stats["losses"])
                        * 100, 1)

                    msg = (
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f" 📝 PAPER TRADING\n"
                        f"  DAILY REPORT\n"
                        f"  {today}\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"Mode     : PAPER ✅\n"
                        f"Exchange : MEXC\n"
                        f"Strategy : Mkt Making\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"TRADES\n"
                        f"Total    : "
                        f"{stats['total']}\n"
                        f"Buys     : "
                        f"{stats['buys']}\n"
                        f"Sells    : "
                        f"{stats['sells']}\n"
                        f"Hedges   : "
                        f"{stats['hedges']}\n"
                        f"Win Rate : {wr}%\n"
                        f"Volume   : "
                        f"${stats['volume']:,.0f}\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"PNL (Simulated)\n"
                        f"Gross    : "
                        f"{stats['gross']:+.4f}\n"
                        f"Hedge    : "
                        f"{stats['hcost']:+.4f}\n"
                        f"NET PnL  : "
                        f"{stats['net']:+.4f}\n"
                        f"Best     : "
                        f"+{stats['best']:.4f}\n"
                        f"Worst    : "
                        f"{stats['worst']:.4f}\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"PROJECTION\n"
                        f"Daily    : "
                        f"+{pd:.4f} USDT\n"
                        f"Monthly~ : "
                        f"+{pm:.2f} USDT\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"CAPITAL\n"
                        f"Start    : "
                        f"{scap:.2f} USDT\n"
                        f"Now      : "
                        f"{cap:.4f} USDT\n"
                        f"Growth   : "
                        f"{growth:+.4f} USDT\n"
                        f"ROI      : "
                        f"{roi:+.4f}%\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"FEE (Simulated)\n"
                        f"Maker    : 0.00%\n"
                        f"Hedge    : 0.01%\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━")
                else:
                    msg = (
                        f"PAPER DAILY {today}\n"
                        f"Koi trade nahi hua")

                send_telegram(msg)
                time.sleep(70)

        except Exception as e:
            print(f"[DAY ERR] {e}")
        time.sleep(30)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  PAPER TRADING ENGINE
#  Real API nahi - Simulate karo
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def run_paper_engine():
    """
    Paper Trading Logic:

    FILL SIMULATION:
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    Har cycle mein:
    1. Current price dekho
    2. Hamare simulated orders dekho
    3. Agar market price hamare
       bid price se neeche aaya
       = BUY fill simulate karo

    4. Agar market price hamare
       ask price se upar gaya
       = SELL fill simulate karo

    5. Inventory manage karo
    6. Profit calculate karo
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    """

    ex           = get_exchange()
    capital      = load_capital()
    inventory    = 0.0
    avg_price    = 0.0
    buy_fills    = 0
    sell_fills   = 0
    trade_count  = 0
    gross_profit = 0.0
    hedge_cost   = 0.0
    net_profit   = 0.0
    best_trade   = 0.0
    worst_trade  = 0.0
    total_volume = 0.0
    win_trades   = 0
    loss_trades  = 0
    cycles       = 0
    start_cap    = capital

    # Simulated order book
    # [{level, price, qty, side}]
    sim_bids = []
    sim_asks = []

    prev_price = 0.0

    print("[PAPER ENGINE] Started ✅")

    # Startup
    cap_use = capital * CAPITAL_USE / 100

    send_telegram(
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f" 📝 PAPER TRADING MODE\n"
        f"  MM HFT BOT v6.0\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Capital  : {capital:.2f} USDT\n"
        f"Use(80%) : {cap_use:.2f} USDT\n"
        f"Leverage : {LEVERAGE}x\n"
        f"Mode     : SIMULATION ✅\n"
        f"Risk     : ZERO! ✅\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"STRATEGY:\n"
        f"Market Making Simulate\n"
        f"Real market data\n"
        f"Simulated orders\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"LEVELS:\n"
        f"L1: ±{BASE_HALF_SPREAD} (50%)\n"
        f"L2: ±{BASE_HALF_SPREAD*2} (30%)\n"
        f"L3: ±{BASE_HALF_SPREAD*3} (20%)\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"FEE: 0.00% Maker FREE\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Bot shuru ho gaya!\n"
        f"Fills aana shuru honge...\n"
        f"━━━━━━━━━━━━━━━━━━━━━━"
    )

    while True:
        try:
            loop_start = time.time()
            cycles    += 1

            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            # STEP 1: MARKET DATA
            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            ob = ex.fetch_order_book(
                SYMBOL, limit=5)

            best_bid  = float(
                ob["bids"][0][0])
            best_ask  = float(
                ob["asks"][0][0])
            mid       = round(
                (best_bid + best_ask)
                / 2, 2)
            mkt_sprd  = round(
                best_ask - best_bid, 4)

            add_price(mid)

            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            # STEP 2: VOLATILITY & SPREAD
            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            vol      = get_volatility()
            dyn_sprd, vol_label = (
                calc_dynamic_spread(vol))
            skew     = calc_skew(inventory)

            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            # STEP 3: LEVEL PRICES
            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            cap_use   = (
                capital *
                CAPITAL_USE / 100)
            total_qty = round(
                cap_use *
                LEVERAGE / mid, 4)
            total_qty = max(
                0.003, total_qty)

            new_bids, new_asks = (
                calc_levels(
                    mid, dyn_sprd,
                    skew, total_qty))

            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            # STEP 4: SIMULATE FILLS
            #
            # Real orders ki jagah:
            # Check karo ki price
            # hamare level pe aaya ya nahi
            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━

            # Price move kitna hua
            price_moved_down = (
                prev_price > 0 and
                mid < prev_price)
            price_moved_up = (
                prev_price > 0 and
                mid > prev_price)

            # BUY FILL SIMULATE
            # Jab price neeche aaye
            # = Hamare bid orders fill
            if price_moved_down:
                for bl in new_bids:
                    bid_px = bl["price"]
                    qty    = bl["qty"]

                    # Price hamare bid
                    # se neeche gaya?
                    if mid <= bid_px:
                        # BUY FILL!
                        fill_price = bid_px
                        buy_fills  += 1
                        trade_count += 1
                        total_volume += (
                            fill_price * qty)

                        # Inventory update
                        if avg_price == 0:
                            avg_price = (
                                fill_price)
                        else:
                            total_inv = (
                                inventory +
                                qty)
                            if total_inv > 0:
                                avg_price = (
                                    (avg_price
                                     * inventory
                                     + fill_price
                                     * qty) /
                                    total_inv)
                        inventory += qty

                        print(
                            f"[SIM BUY "
                            f"L{bl['level']}] "
                            f"{qty:.4f}@"
                            f"{fill_price:.2f}"
                            f" | Inv="
                            f"{inventory:.4f}")

                        send_telegram(
                            f"✅ [SIM] BUY "
                            f"L{bl['level']}\n"
                            f"━━━━━━━━━━━━━━━━━━━━━━\n"
                            f"Price    : "
                            f"{fill_price:.4f}\n"
                            f"Qty      : "
                            f"{qty:.4f} ETH\n"
                            f"Fee      : "
                            f"0% FREE\n"
                            f"Inventory: "
                            f"{inventory:.4f} ETH\n"
                            f"Avg Price: "
                            f"{avg_price:.4f}\n"
                            f"━━━━━━━━━━━━━━━━━━━━━━"
                        )

                        save_trade(
                            "BUY_FILL",
                            fill_price,
                            qty, 0.0,
                            capital,
                            trade_count,
                            f"SIM|L"
                            f"{bl['level']}"
                            f"|Inv="
                            f"{inventory:.4f}")

                        # Sirf 1 fill
                        # per cycle
                        break

            # SELL FILL SIMULATE
            # Jab price upar aaye
            # = Hamare ask orders fill
            if (price_moved_up and
                    inventory > 0):
                for al in new_asks:
                    ask_px = al["price"]
                    qty    = min(
                        al["qty"],
                        inventory)

                    # Price hamare ask
                    # se upar gaya?
                    if mid >= ask_px:
                        # SELL FILL!
                        fill_price = ask_px

                        # Profit
                        profit = (
                            (fill_price -
                             avg_price) *
                            qty)

                        sell_fills  += 1
                        trade_count += 1
                        gross_profit += profit
                        net_profit   += profit
                        capital      += profit
                        total_volume += (
                            fill_price * qty)

                        inventory -= qty
                        if inventory <= 0.001:
                            inventory = 0.0
                            avg_price = 0.0

                        if profit > best_trade:
                            best_trade = profit
                        if profit < worst_trade:
                            worst_trade = profit

                        if profit > 0:
                            win_trades += 1
                        else:
                            loss_trades += 1

                        save_capital(capital)
                        save_trade(
                            "SELL_FILL",
                            fill_price,
                            qty, profit,
                            capital,
                            trade_count,
                            f"SIM|L"
                            f"{al['level']}"
                            f"|P="
                            f"{profit:.4f}")

                        print(
                            f"[SIM SELL "
                            f"L{al['level']}] "
                            f"{qty:.4f}@"
                            f"{fill_price:.2f}"
                            f" | P={profit:+.4f}"
                            f" | Net="
                            f"{net_profit:+.4f}")

                        send_telegram(
                            f"💰 [SIM] SELL "
                            f"L{al['level']}\n"
                            f"━━━━━━━━━━━━━━━━━━━━━━\n"
                            f"Price    : "
                            f"{fill_price:.4f}\n"
                            f"Qty      : "
                            f"{qty:.4f} ETH\n"
                            f"Profit   : "
                            f"{profit:+.4f} USDT\n"
                            f"Fee      : "
                            f"0% FREE ✅\n"
                            f"Inventory: "
                            f"{inventory:.4f}\n"
                            f"Capital  : "
                            f"{capital:.4f}\n"
                            f"Net Total: "
                            f"{net_profit:+.4f}\n"
                            f"━━━━━━━━━━━━━━━━━━━━━━"
                        )

                        break

            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            # STEP 5: INVENTORY CHECK
            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            inv_pnl = (
                (mid - avg_price) *
                inventory
                if avg_price > 0
                else 0.0)

            # Stop loss simulate
            if inv_pnl < INV_STOP_LOSS:
                print(
                    f"[SIM STOP] "
                    f"InvPnL={inv_pnl:.4f}")

                # Simulate hedge
                hedge_price = mid
                hedge_fee   = (
                    hedge_price *
                    inventory *
                    TAKER_FEE)
                hloss = inv_pnl - hedge_fee

                capital    += hloss
                hedge_cost += hloss
                net_profit += hloss

                save_capital(capital)
                save_trade(
                    "HEDGE",
                    hedge_price,
                    inventory,
                    hloss, capital,
                    trade_count,
                    "SIM|STOP_LOSS")

                send_telegram(
                    f"🚨 [SIM] STOP LOSS\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"Inv PnL  : "
                    f"{inv_pnl:.4f}\n"
                    f"Hedged   : "
                    f"{inventory:.4f} ETH\n"
                    f"At Price : "
                    f"{hedge_price:.4f}\n"
                    f"Loss     : "
                    f"{hloss:.4f} USDT\n"
                    f"Capital  : "
                    f"{capital:.4f} USDT\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━"
                )

                inventory = 0.0
                avg_price = 0.0

            # Partial hedge simulate
            elif abs(inventory) >= HEDGE_INV:
                h_qty       = round(
                    abs(inventory) / 2, 4)
                hedge_price = mid
                hedge_fee   = (
                    hedge_price *
                    h_qty * TAKER_FEE)

                if inventory > 0:
                    h_profit = (
                        (hedge_price -
                         avg_price) *
                        h_qty - hedge_fee)
                    inventory -= h_qty
                else:
                    h_profit = (
                        (avg_price -
                         hedge_price) *
                        h_qty - hedge_fee)
                    inventory += h_qty

                capital    += h_profit
                hedge_cost += -hedge_fee
                net_profit += h_profit

                if inventory <= 0.001:
                    inventory = 0.0
                    avg_price = 0.0

                save_capital(capital)
                save_trade(
                    "HEDGE",
                    hedge_price,
                    h_qty, h_profit,
                    capital, trade_count,
                    "SIM|PARTIAL")

                send_telegram(
                    f"🔄 [SIM] PARTIAL HEDGE\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"Qty      : "
                    f"{h_qty:.4f} ETH\n"
                    f"Price    : "
                    f"{hedge_price:.4f}\n"
                    f"Profit   : "
                    f"{h_profit:+.4f} USDT\n"
                    f"Inv Left : "
                    f"{inventory:.4f} ETH\n"
                    f"Capital  : "
                    f"{capital:.4f} USDT\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━"
                )

            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            # STEP 6: STATE UPDATE
            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            prev_price = mid

            update_state(
                mid=mid,
                best_bid=best_bid,
                best_ask=best_ask,
                mkt_spread=mkt_sprd,
                volatility=vol,
                dyn_spread=dyn_sprd,
                vol_label=vol_label,
                sim_bids=new_bids,
                sim_asks=new_asks,
                inventory=inventory,
                avg_price=avg_price,
                inv_pnl=inv_pnl,
                skew=skew,
                capital=capital,
                start_capital=start_cap,
                trade_count=trade_count,
                buy_fills=buy_fills,
                sell_fills=sell_fills,
                gross_profit=gross_profit,
                hedge_cost=hedge_cost,
                net_profit=net_profit,
                best_trade=best_trade,
                worst_trade=worst_trade,
                total_volume=total_volume,
                win_trades=win_trades,
                loss_trades=loss_trades,
                cycles=cycles,
            )

            # Print status
            if cycles % 50 == 0:
                wr = round(
                    win_trades /
                    max(1, win_trades +
                        loss_trades)
                    * 100, 1)
                print(
                    f"[P{cycles}] "
                    f"ETH={mid:.2f} | "
                    f"Vol={vol:.4f}% | "
                    f"Sprd=±{dyn_sprd}| "
                    f"Inv={inventory:.3f}| "
                    f"Net={net_profit:+.4f}| "
                    f"BF={buy_fills} "
                    f"SF={sell_fills} "
                    f"WR={wr}%")

            # Speed
            elapsed = (
                time.time() - loop_start)
            sleep_t = max(
                0,
                SCAN_INTERVAL - elapsed)
            if sleep_t > 0:
                time.sleep(sleep_t)

        except Exception as e:
            err = str(e)
            print(f"[ERR] {err}")
            if "429" in err:
                time.sleep(10)
            elif ("connection" in
                  err.lower() or
                  "timeout" in
                  err.lower()):
                ex = get_exchange()
                time.sleep(5)
            else:
                time.sleep(1)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  START
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

if __name__ == "__main__":

    cap_use  = CAPITAL * CAPITAL_USE / 100
    exp      = cap_use * LEVERAGE
    cyc_day  = int(86400 / SCAN_INTERVAL)

    print("=" * 55)
    print(
        "  ETH MM PAPER TRADING "
        "BOT v6.0")
    print("=" * 55)
    print(f"  Mode       : PAPER TRADING")
    print(f"  Capital    : {CAPITAL:,.2f} USDT")
    print(f"  Simulated  : YES")
    print(f"  Real Risk  : ZERO ✅")
    print("-" * 55)
    print(f"  API Key    : NOT NEEDED ✅")
    print(f"  Public API : MEXC")
    print("-" * 55)
    print(f"  Spread Min : ±{MIN_HALF_SPREAD}")
    print(f"  Spread Base: ±{BASE_HALF_SPREAD}")
    print(f"  Spread Max : ±{MAX_HALF_SPREAD}")
    print(f"  Levels     : {LEVELS} each side")
    print(f"  Scan       : {SCAN_INTERVAL}s")
    print(f"  Cycles/Day : {cyc_day:,}")
    print("-" * 55)
    print(f"  Maker Fee  : 0.00% FREE")
    print(f"  Hedge Fee  : 0.01%")
    print("=" * 55)

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
            target=run_update,
            name="Update",
            daemon=True),
        threading.Thread(
            target=run_daily,
            name="Daily",
            daemon=True),
        threading.Thread(
            target=run_paper_engine,
            name="PaperEngine",
            daemon=True),
    ]

    for t in threads:
        t.start()
        print(f"[START] {t.name} ✅")
        time.sleep(0.2)

    print("=" * 55)
    print("[INFO] PAPER TRADING MODE ✅")
    print("[INFO] No API Key Needed ✅")
    print("[INFO] Zero Real Risk ✅")
    print("[INFO] Bot Live 24/7 ✅")
    print("=" * 55)

    while True:
        time.sleep(60)
