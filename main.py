"""
ETH/USDT Market Making Bot
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Exchange : Binance Futures Testnet
Symbol   : ETH/USDT
Strategy : Market Making
Fee      : 0.02% Maker (Testnet)

HOW IT WORKS:
ETH Price = 1670 USDT
Bot lagata hai:
BUY  Limit @ 1669.95
SELL Limit @ 1670.05

Jab dono fill ho:
Profit = 0.10 USDT
Fee    = 0% (Maker)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import ccxt
import requests
import threading
import time
import json
import os
from flask import Flask
from datetime import (
    datetime, timezone, timedelta)
from collections import deque

app = Flask(__name__)

@app.route('/')
def home():
    return "ETH MM Bot - Binance Testnet ✅"

def run_server():
    port = int(
        os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  ⚙️ CONFIG - SIRF YE BHARO
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 🔑 Apni Testnet API Key yahan daalo
API_KEY    = "H647cSQelN9Im9o22wTu3h3oz3ZTBgxSzV5McQzN7qJoWg94lPGmR6JaCawbmS5S "
API_SECRET = "O2Gz79sooHsYAzd2oyJQ2rmE8KwhhF5JCs9KlwHwFToTitszOaLMRDFYCobz6gSW"

# 📱 Telegram
BOT_TOKEN = "8161773850:AAFcWw3UnlSe2TrMooB2uvgZQZUqIW0zW2w"
CHAT_ID   = "7102976298"

# 💰 Symbol
SYMBOL    = "ETH/USDT"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  📊 TRADING CONFIG
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Leverage
LEVERAGE     = 5

# Capital use karo (%)
CAPITAL_USE  = 80      # 80%

# ── Spread ────────────────────────────────
# Kitna spread capture karna hai
# ETH 1670 pe:
# HALF = 0.05 matlab
# BUY  @ 1669.95
# SELL @ 1670.05
# Profit = 0.10 USDT per pair
HALF_SPREAD  = 0.05    # 5 cents each side

# ── Order Refresh ─────────────────────────
# Har kitne second mein
# orders refresh kare
REFRESH_TIME = 1.0     # 1 second

# ── Inventory Limits ──────────────────────
# Max kitna ETH hold kar sakte hain
MAX_INV      = 2.0     # 2 ETH max

# Itna ho jaye to hedge karo
HEDGE_INV    = 1.5     # 1.5 ETH

# Inventory loss limit
INV_SL       = -50.0   # -50 USDT

# ── Fee (Binance Testnet) ─────────────────
MAKER_FEE    = 0.0002  # 0.02%
TAKER_FEE    = 0.0004  # 0.04%

# ── Update ────────────────────────────────
UPDATE_MIN   = 30      # 30 min update


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  📁 FILES
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

FILES = {
    "capital": "capital_mm.txt",
    "history": "history_mm.json",
}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  🧠 STATE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

lock  = threading.Lock()
state = {
    # Market
    "price":       0.0,
    "bid":         0.0,
    "ask":         0.0,
    "spread":      0.0,

    # Our Orders
    "buy_id":      None,
    "sell_id":     None,
    "our_bid":     0.0,
    "our_ask":     0.0,

    # Inventory
    "inventory":   0.0,
    "avg_price":   0.0,
    "inv_pnl":     0.0,

    # Capital
    "capital":     0.0,
    "start_cap":   0.0,

    # Stats
    "trades":      0,
    "buy_fills":   0,
    "sell_fills":  0,
    "gross":       0.0,
    "hedge_cost":  0.0,
    "net":         0.0,
    "best":        0.0,
    "cycles":      0,
    "wins":        0,
    "losses":      0,
}

def set_state(**kw):
    with lock:
        for k, v in kw.items():
            if k in state:
                state[k] = v

def get_state():
    with lock:
        return dict(state)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  💾 CAPITAL
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def load_cap():
    try:
        with open(
                FILES["capital"],
                "r") as f:
            return float(f.read().strip())
    except Exception:
        return None

def save_cap(cap):
    try:
        with open(
                FILES["capital"],
                "w") as f:
            f.write(str(round(cap, 4)))
    except Exception:
        pass


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  📝 HISTORY
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

hist_lock = threading.Lock()

def save_trade(
        ttype, price, qty,
        profit, cap, num):
    try:
        with hist_lock:
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
                    .strftime("%H:%M:%S"),
                "type":    ttype,
                "price":   round(price, 2),
                "qty":     round(qty, 4),
                "profit":  round(profit, 4),
                "capital": round(cap, 4),
            })

            # Last 50000 rakho
            if len(h) > 50000:
                h = h[-50000:]

            with open(
                    FILES["history"],
                    "w",
                    encoding="utf-8") as f:
                json.dump(h, f, indent=2)
    except Exception as e:
        print(f"[HIST] {e}")


def get_today_stats():
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
    today_trades = [
        t for t in h
        if t["date"] == today]

    if not today_trades:
        return None

    buys   = [
        t for t in today_trades
        if t["type"] == "BUY"]
    sells  = [
        t for t in today_trades
        if t["type"] == "SELL"]
    hedges = [
        t for t in today_trades
        if t["type"] == "HEDGE"]

    sell_profits = [
        t["profit"] for t in sells]

    net = round(sum(
        t["profit"]
        for t in today_trades), 4)

    vol = round(sum(
        t["price"] * t["qty"]
        for t in today_trades), 2)

    hours  = max(1, len(set(
        t["time"][:2]
        for t in today_trades)))

    return {
        "total":   len(today_trades),
        "buys":    len(buys),
        "sells":   len(sells),
        "hedges":  len(hedges),
        "net":     net,
        "volume":  vol,
        "per_hr":  round(net/hours, 4),
        "best":    round(
            max(sell_profits)
            if sell_profits else 0, 4),
        "worst":   round(
            min(sell_profits)
            if sell_profits else 0, 4),
        "wins":    len([
            p for p in sell_profits
            if p > 0]),
        "losses":  len([
            p for p in sell_profits
            if p <= 0]),
        "capital": today_trades[
            -1]["capital"],
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  🔌 EXCHANGE - BINANCE TESTNET
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def get_exchange():
    """
    Binance Futures Testnet
    Real orders place hote hain
    Fake money se!
    """
    while True:
        try:
            ex = ccxt.binanceusdm({
                "apiKey":  API_KEY,
                "secret":  API_SECRET,
                "enableRateLimit": True,
                "rateLimit": 50,
                "options": {
                    "defaultType":
                        "future",
                    # ✅ TESTNET
                    "sandboxMode": True,
                },
            })

            # Testnet URL set karo
            ex.set_sandbox_mode(True)
            ex.load_markets()

            # Leverage set karo
            try:
                ex.set_leverage(
                    LEVERAGE, SYMBOL)
            except Exception:
                pass

            print(
                "[BINANCE TESTNET] "
                "Connected ✅")
            return ex

        except Exception as e:
            print(
                f"[RECONNECT] "
                f"{e} - 15s...")
            time.sleep(15)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  📬 TELEGRAM
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

tg_q    = []
tg_lock = threading.Lock()

def send_tg(msg):
    with tg_lock:
        tg_q.append(str(msg))

def tg_worker():
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
                                    f"🤖 MM BOT\n"
                                    f"{msg}",
                            },
                            timeout=10)
                        break
                    except Exception:
                        time.sleep(2)
            else:
                time.sleep(0.1)
        except Exception as e:
            print(f"[TG] {e}")
            time.sleep(2)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  📊 ORDER FUNCTIONS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def place_buy(ex, price, qty):
    """
    BUY Limit Order Place karo
    postOnly = Maker = 0% fee
    """
    try:
        o = ex.create_limit_buy_order(
            SYMBOL, qty, price,
            {"timeInForce": "GTX"})
        print(
            f"[BUY ORDER] "
            f"{qty}@{price} "
            f"ID:{o['id']}")
        return o["id"]
    except Exception as e:
        print(f"[BUY ERR] {e}")
        return None


def place_sell(ex, price, qty):
    """
    SELL Limit Order Place karo
    postOnly = Maker = 0% fee
    """
    try:
        o = ex.create_limit_sell_order(
            SYMBOL, qty, price,
            {"timeInForce": "GTX"})
        print(
            f"[SELL ORDER] "
            f"{qty}@{price} "
            f"ID:{o['id']}")
        return o["id"]
    except Exception as e:
        print(f"[SELL ERR] {e}")
        return None


def cancel(ex, order_id):
    """Order cancel karo"""
    try:
        if order_id:
            ex.cancel_order(
                order_id, SYMBOL)
            return True
    except Exception as e:
        if "unknown" not in str(e).lower():
            print(f"[CANCEL] {e}")
    return False


def get_order_status(ex, order_id):
    """
    Order ka status check karo

    Return:
    status  = filled/open/cancelled
    filled  = kitna fill hua
    price   = kis price pe fill hua
    """
    try:
        if not order_id:
            return "none", 0.0, 0.0

        o      = ex.fetch_order(
            order_id, SYMBOL)
        status = o["status"]
        filled = float(
            o.get("filled", 0))
        price  = float(
            o.get("average") or
            o.get("price") or 0)

        if status == "closed":
            return "filled", filled, price
        elif status == "canceled":
            return "cancelled", 0.0, 0.0
        elif filled > 0:
            return "partial", filled, price
        else:
            return "open", 0.0, 0.0

    except Exception as e:
        print(f"[STATUS] {e}")
        return "error", 0.0, 0.0


def market_close(ex, side, qty):
    """
    Market order se close karo
    Hedge ke liye
    Taker fee lagegi
    """
    try:
        if side == "sell":
            o = ex.create_market_sell_order(
                SYMBOL, qty,
                {"reduceOnly": True})
        else:
            o = ex.create_market_buy_order(
                SYMBOL, qty,
                {"reduceOnly": True})

        price = float(
            o.get("average") or
            o.get("price") or 0)
        fee   = price * qty * TAKER_FEE

        print(
            f"[HEDGE] {side} "
            f"{qty}@{price:.2f} "
            f"fee={fee:.4f}")
        return price, fee

    except Exception as e:
        print(f"[HEDGE ERR] {e}")
        return 0.0, 0.0


def get_account_balance(ex):
    """Testnet balance dekho"""
    try:
        bal = ex.fetch_balance()
        usdt = float(
            bal["USDT"]["free"] or 0)
        return usdt
    except Exception as e:
        print(f"[BAL] {e}")
        return 0.0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  📢 UPDATE MESSAGE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def run_update():
    time.sleep(60)
    while True:
        try:
            st    = get_state()
            stats = get_today_stats()
            now   = datetime.now()\
                .strftime("%Y-%m-%d %H:%M")

            cap   = st["capital"]
            scap  = st["start_cap"]
            net   = st["net"]
            bf    = st["buy_fills"]
            sf    = st["sell_fills"]
            tc    = st["trades"]
            inv   = st["inventory"]
            price = st["price"]
            ipl   = st["inv_pnl"]
            cyc   = st["cycles"]
            wins  = st["wins"]
            losses= st["losses"]
            growth= round(cap - scap, 4)
            growp = round(
                growth / max(1, scap)
                * 100, 2)
            wr    = round(
                wins /
                max(1, wins + losses)
                * 100, 1)

            msg = (
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"  MM BOT UPDATE\n"
                f"  {now}\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🔵 BINANCE TESTNET\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"MARKET\n"
                f"ETH Price: {price:.2f}\n"
                f"Our Bid  : {st['our_bid']:.2f}\n"
                f"Our Ask  : {st['our_ask']:.2f}\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"INVENTORY\n"
                f"ETH Held : {inv:.4f}\n"
                f"Value    : "
                f"{inv*price:.2f} USDT\n"
                f"Inv PnL  : "
                f"{ipl:+.4f} USDT\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"STATS\n"
                f"Cycles   : {cyc}\n"
                f"Trades   : {tc}\n"
                f"Buy Fill : {bf}\n"
                f"Sell Fill: {sf}\n"
                f"Win Rate : {wr}%\n"
                f"Net PnL  : "
                f"{net:+.4f} USDT\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"CAPITAL\n"
                f"Start    : "
                f"{scap:.2f} USDT\n"
                f"Current  : "
                f"{cap:.4f} USDT\n"
                f"Growth   : "
                f"{growth:+.4f} USDT\n"
                f"ROI      : "
                f"{growp:+.2f}%\n"
                f"━━━━━━━━━━━━━━━━━━━━━━")

            if stats:
                ph = stats["per_hr"]
                pd = round(ph * 24, 2)
                pm = round(pd * 30, 2)
                msg += (
                    f"\nTODAY\n"
                    f"Trades   : "
                    f"{stats['total']}\n"
                    f"Buys     : "
                    f"{stats['buys']}\n"
                    f"Sells    : "
                    f"{stats['sells']}\n"
                    f"Wins     : "
                    f"{stats['wins']} ✅\n"
                    f"Losses   : "
                    f"{stats['losses']} ❌\n"
                    f"Net PnL  : "
                    f"{stats['net']:+.4f}\n"
                    f"Per Hour : "
                    f"+{ph:.4f}\n"
                    f"Per Day~ : "
                    f"+{pd:.2f} USDT\n"
                    f"Monthly~ : "
                    f"+{pm:.2f} USDT\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━")

            send_tg(msg)

        except Exception as e:
            print(f"[UPD] {e}")

        time.sleep(UPDATE_MIN * 60)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  📅 DAILY REPORT
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def run_daily():
    while True:
        try:
            ist = timezone(timedelta(
                hours=5, minutes=30))
            now = datetime.now(ist)

            if (now.hour == 23 and
                    now.minute == 59):
                stats = get_today_stats()
                st    = get_state()
                today = now.strftime(
                    "%d/%m/%Y")

                if stats:
                    growth = round(
                        st["capital"] -
                        st["start_cap"], 4)
                    roi    = round(
                        growth /
                        max(1,
                            st["start_cap"])
                        * 100, 2)
                    wr     = round(
                        stats["wins"] /
                        max(1,
                            stats["wins"] +
                            stats["losses"])
                        * 100, 1)
                    pm     = round(
                        stats["net"] * 30,
                        2)

                    msg = (
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"  DAILY REPORT\n"
                        f"  {today}\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"Exchange : Binance\n"
                        f"Mode     : Testnet\n"
                        f"Strategy : Mkt Making\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"TRADES\n"
                        f"Total    : "
                        f"{stats['total']}\n"
                        f"Buy Fill : "
                        f"{stats['buys']}\n"
                        f"Sell Fill: "
                        f"{stats['sells']}\n"
                        f"Hedges   : "
                        f"{stats['hedges']}\n"
                        f"Win Rate : {wr}%\n"
                        f"Volume   : "
                        f"${stats['volume']:,.0f}\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"PNL\n"
                        f"Net PnL  : "
                        f"{stats['net']:+.4f}\n"
                        f"Best     : "
                        f"+{stats['best']:.4f}\n"
                        f"Worst    : "
                        f"{stats['worst']:.4f}\n"
                        f"Per Hour : "
                        f"+{stats['per_hr']:.4f}\n"
                        f"Monthly~ : "
                        f"+{pm:.2f} USDT\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"CAPITAL\n"
                        f"Start    : "
                        f"{st['start_cap']:.2f}\n"
                        f"Now      : "
                        f"{st['capital']:.4f}\n"
                        f"Growth   : "
                        f"{growth:+.4f}\n"
                        f"ROI      : "
                        f"{roi:+.2f}%\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━")
                else:
                    msg = (
                        f"DAILY {today}\n"
                        f"Koi trade nahi")

                send_tg(msg)
                time.sleep(70)

        except Exception as e:
            print(f"[DAY] {e}")
        time.sleep(30)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  🚀 MAIN ENGINE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def run_engine():
    """
    Market Making Engine

    LOOP HAR 1 SECOND:
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    1. Price fetch karo
    2. Fill check karo
    3. Inventory check karo
    4. Old orders cancel karo
    5. Naye orders lagao
    6. Repeat!
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    FILL LOGIC:
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    Exchange khud fill karega
    Jab market price hamare
    order pe aayega

    Hume sirf check karna hai
    Ki order fill hua ya nahi
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    """

    ex          = get_exchange()
    balance     = get_account_balance(ex)
    capital     = load_cap() or balance
    start_cap   = capital
    inventory   = 0.0
    avg_price   = 0.0
    buy_id      = None
    sell_id     = None
    buy_fills   = 0
    sell_fills  = 0
    trades      = 0
    gross       = 0.0
    hedge_cost  = 0.0
    net         = 0.0
    best        = 0.0
    wins        = 0
    losses      = 0
    cycles      = 0

    print(
        f"[ENGINE] Started ✅\n"
        f"Balance: {balance:.2f} USDT\n"
        f"Capital: {capital:.2f} USDT")

    save_cap(capital)

    set_state(
        capital=capital,
        start_cap=start_cap)

    # Startup message
    cap_use = capital * CAPITAL_USE / 100
    exp     = cap_use * LEVERAGE
    profit_per_pair = HALF_SPREAD * 2

    send_tg(
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"  MM BOT STARTED\n"
        f"  Binance Testnet\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Balance  : "
        f"{balance:.2f} USDT\n"
        f"Use(80%) : "
        f"{cap_use:.2f} USDT\n"
        f"Leverage : {LEVERAGE}x\n"
        f"Exposure : {exp:.2f} USDT\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"STRATEGY\n"
        f"Half Spread : "
        f"{HALF_SPREAD} USDT\n"
        f"Per Pair    : "
        f"+{profit_per_pair} USDT\n"
        f"Maker Fee   : "
        f"{MAKER_FEE*100}%\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"LIMITS\n"
        f"Max Inv  : {MAX_INV} ETH\n"
        f"Hedge At : {HEDGE_INV} ETH\n"
        f"Stop Loss: {INV_SL} USDT\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Bot chal raha hai!\n"
        f"Orders place ho rahe...\n"
        f"━━━━━━━━━━━━━━━━━━━━━━"
    )

    while True:
        try:
            loop_start = time.time()
            cycles    += 1

            # ━━━━━━━━━━━━━━━━━━━━━━━━━━
            # 1. PRICE FETCH
            # ━━━━━━━━━━━━━━━━━━━━━━━━━━
            ob = ex.fetch_order_book(
                SYMBOL, limit=5)

            best_bid = float(
                ob["bids"][0][0])
            best_ask = float(
                ob["asks"][0][0])
            mid      = round(
                (best_bid + best_ask)
                / 2, 2)
            spread   = round(
                best_ask - best_bid, 4)

            # Hamare orders
            our_bid = round(
                mid - HALF_SPREAD, 2)
            our_ask = round(
                mid + HALF_SPREAD, 2)

            # Qty calculate karo
            cap_use  = (
                capital *
                CAPITAL_USE / 100)
            qty      = round(
                cap_use *
                LEVERAGE / mid, 3)
            qty      = max(0.001, qty)

            # ━━━━━━━━━━━━━━━━━━━━━━━━━━
            # 2. FILL CHECK
            # Exchange ne fill kiya?
            # ━━━━━━━━━━━━━━━━━━━━━━━━━━

            # BUY fill check
            if buy_id is not None:
                b_stat, b_qty, b_px = (
                    get_order_status(
                        ex, buy_id))

                if b_stat == "filled":
                    # ✅ BUY FILL HUA!
                    buy_fills += 1
                    trades    += 1
                    inventory += b_qty

                    # Avg price update
                    if avg_price == 0:
                        avg_price = b_px
                    else:
                        new_inv   = (
                            inventory)
                        avg_price = (
                            (avg_price *
                             (inventory -
                              b_qty) +
                             b_px * b_qty)
                            / new_inv
                            if new_inv > 0
                            else b_px)

                    buy_id = None

                    print(
                        f"✅ BUY FILLED "
                        f"#{buy_fills} | "
                        f"{b_qty}@{b_px} | "
                        f"Inv={inventory:.4f}")

                    save_trade(
                        "BUY", b_px,
                        b_qty, 0.0,
                        capital, trades)

                    send_tg(
                        f"✅ BUY FILL "
                        f"#{buy_fills}\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"Price    : {b_px:.2f}\n"
                        f"Qty      : "
                        f"{b_qty:.4f} ETH\n"
                        f"Fee      : "
                        f"0% Maker FREE\n"
                        f"Inventory: "
                        f"{inventory:.4f} ETH\n"
                        f"Avg Price: "
                        f"{avg_price:.2f}\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━"
                    )

            # SELL fill check
            if sell_id is not None:
                s_stat, s_qty, s_px = (
                    get_order_status(
                        ex, sell_id))

                if s_stat == "filled":
                    # 💰 SELL FILL HUA!
                    sell_fills += 1
                    trades     += 1

                    # Profit calculate
                    if avg_price > 0:
                        profit = (
                            (s_px -
                             avg_price) *
                            s_qty)
                    else:
                        profit = (
                            HALF_SPREAD *
                            s_qty)

                    # Fee deduct
                    entry_fee = (
                        avg_price *
                        s_qty *
                        MAKER_FEE)
                    exit_fee  = (
                        s_px *
                        s_qty *
                        MAKER_FEE)
                    total_fee = (
                        entry_fee +
                        exit_fee)
                    net_profit = (
                        profit - total_fee)

                    gross     += profit
                    net       += net_profit
                    capital   += net_profit
                    inventory -= s_qty

                    if inventory < 0.001:
                        inventory = 0.0
                        avg_price = 0.0

                    if net_profit > best:
                        best = net_profit
                    if net_profit > 0:
                        wins += 1
                    else:
                        losses += 1

                    sell_id = None

                    save_cap(capital)
                    save_trade(
                        "SELL", s_px,
                        s_qty,
                        net_profit,
                        capital, trades)

                    wr = round(
                        wins /
                        max(1,
                            wins + losses)
                        * 100, 1)

                    print(
                        f"💰 SELL FILLED "
                        f"#{sell_fills} | "
                        f"{s_qty}@{s_px} | "
                        f"P={net_profit:+.4f} | "
                        f"Net={net:+.4f} | "
                        f"WR={wr}%")

                    send_tg(
                        f"💰 SELL FILL "
                        f"#{sell_fills}\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"Price    : {s_px:.2f}\n"
                        f"Qty      : "
                        f"{s_qty:.4f} ETH\n"
                        f"Gross    : "
                        f"{profit:+.4f} USDT\n"
                        f"Fee      : "
                        f"-{total_fee:.4f}\n"
                        f"Net PnL  : "
                        f"{net_profit:+.4f} USDT\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"Total Net: "
                        f"{net:+.4f} USDT\n"
                        f"Capital  : "
                        f"{capital:.4f} USDT\n"
                        f"Win Rate : {wr}%\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━"
                    )

            # ━━━━━━━━━━━━━━━━━━━━━━━━━━
            # 3. INVENTORY CHECK
            # ━━━━━━━━━━━━━━━━━━━━━━━━━━
            inv_pnl = (
                (mid - avg_price) *
                inventory
                if avg_price > 0
                else 0.0)

            # Stop loss hit?
            if inv_pnl < INV_SL:
                print(
                    f"[STOP LOSS] "
                    f"InvPnL={inv_pnl:.2f}")

                # Cancel orders
                cancel(ex, buy_id)
                cancel(ex, sell_id)
                buy_id  = None
                sell_id = None

                # Market mein close karo
                if inventory > 0:
                    hp, hf = market_close(
                        ex, "sell",
                        inventory)
                    if hp > 0:
                        hloss = (
                            inv_pnl - hf)
                        net      += hloss
                        capital  += hloss
                        hedge_cost += hloss
                        save_cap(capital)
                        save_trade(
                            "HEDGE", hp,
                            inventory,
                            hloss,
                            capital,
                            trades)

                        send_tg(
                            f"🚨 STOP LOSS!\n"
                            f"━━━━━━━━━━━━━━━━━━━━━━\n"
                            f"Inv Loss : "
                            f"{inv_pnl:.2f}\n"
                            f"Closed   : "
                            f"{inventory:.4f} ETH\n"
                            f"At Price : {hp:.2f}\n"
                            f"Net Loss : "
                            f"{hloss:.4f} USDT\n"
                            f"Capital  : "
                            f"{capital:.4f}\n"
                            f"━━━━━━━━━━━━━━━━━━━━━━"
                        )

                        inventory = 0.0
                        avg_price = 0.0

                time.sleep(2)
                continue

            # Inventory hedge?
            if inventory >= HEDGE_INV:
                h_qty = round(
                    inventory / 2, 3)

                cancel(ex, buy_id)
                buy_id = None

                hp, hf = market_close(
                    ex, "sell", h_qty)

                if hp > 0:
                    hprofit = (
                        (hp - avg_price) *
                        h_qty - hf)
                    net       += hprofit
                    capital   += hprofit
                    hedge_cost += -hf
                    inventory  -= h_qty

                    if inventory < 0.001:
                        inventory = 0.0
                        avg_price = 0.0

                    save_cap(capital)
                    save_trade(
                        "HEDGE", hp,
                        h_qty, hprofit,
                        capital, trades)

                    send_tg(
                        f"🔄 PARTIAL HEDGE\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"Sold     : "
                        f"{h_qty:.4f} ETH\n"
                        f"Price    : {hp:.2f}\n"
                        f"Profit   : "
                        f"{hprofit:+.4f} USDT\n"
                        f"Inv Left : "
                        f"{inventory:.4f} ETH\n"
                        f"Capital  : "
                        f"{capital:.4f}\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━"
                    )

            # ━━━━━━━━━━━━━━━━━━━━━━━━━━
            # 4. CANCEL OLD ORDERS
            # ━━━━━━━━━━━━━━━━━━━━━━━━━━
            cancel(ex, buy_id)
            cancel(ex, sell_id)
            buy_id  = None
            sell_id = None

            # ━━━━━━━━━━━━━━━━━━━━━━━━━━
            # 5. NAYE ORDERS LAGAO
            # ━━━━━━━━━━━━━━━━━━━━━━━━━━

            # Buy order
            if inventory < MAX_INV:
                buy_id = place_buy(
                    ex, our_bid, qty)

            # Sell order
            if inventory > 0:
                sell_qty = min(
                    qty, inventory)
                sell_id = place_sell(
                    ex, our_ask,
                    sell_qty)
            else:
                sell_id = place_sell(
                    ex, our_ask, qty)

            # ━━━━━━━━━━━━━━━━━━━━━━━━━━
            # 6. STATE UPDATE
            # ━━━━━━━━━━━━━━━━━━━━━━━━━━
            set_state(
                price=mid,
                bid=best_bid,
                ask=best_ask,
                spread=spread,
                buy_id=buy_id,
                sell_id=sell_id,
                our_bid=our_bid,
                our_ask=our_ask,
                inventory=inventory,
                avg_price=avg_price,
                inv_pnl=inv_pnl,
                capital=capital,
                start_cap=start_cap,
                trades=trades,
                buy_fills=buy_fills,
                sell_fills=sell_fills,
                gross=gross,
                hedge_cost=hedge_cost,
                net=net,
                best=best,
                cycles=cycles,
                wins=wins,
                losses=losses,
            )

            # Print
            if cycles % 10 == 0:
                print(
                    f"[{cycles}] "
                    f"ETH={mid:.2f} | "
                    f"Bid={our_bid:.2f} | "
                    f"Ask={our_ask:.2f} | "
                    f"Inv={inventory:.3f} | "
                    f"Net={net:+.4f} | "
                    f"BF={buy_fills} "
                    f"SF={sell_fills}")

            # Speed control
            elapsed = (
                time.time() - loop_start)
            sleep_t = max(
                0,
                REFRESH_TIME - elapsed)
            if sleep_t > 0:
                time.sleep(sleep_t)

        except Exception as e:
            err = str(e)
            print(f"[ERR] {err}")

            if "429" in err:
                time.sleep(10)
            elif ("margin" in
                  err.lower() or
                  "balance" in
                  err.lower()):
                send_tg(
                    f"⚠️ BALANCE LOW!\n"
                    f"Capital: {capital:.2f}")
                time.sleep(30)
            elif ("connection" in
                  err.lower() or
                  "timeout" in
                  err.lower()):
                cancel(ex, buy_id)
                cancel(ex, sell_id)
                buy_id  = None
                sell_id = None
                ex = get_exchange()
                time.sleep(5)
            else:
                cancel(ex, buy_id)
                cancel(ex, sell_id)
                buy_id  = None
                sell_id = None
                time.sleep(2)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  ▶️ START
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

if __name__ == "__main__":

    print("=" * 50)
    print("  ETH MARKET MAKING BOT")
    print("  BINANCE FUTURES TESTNET")
    print("=" * 50)
    print(f"  Symbol    : {SYMBOL}")
    print(f"  Leverage  : {LEVERAGE}x")
    print(f"  Spread    : ±{HALF_SPREAD}")
    print(f"  Refresh   : {REFRESH_TIME}s")
    print(f"  Max Inv   : {MAX_INV} ETH")
    print(f"  Hedge At  : {HEDGE_INV} ETH")
    print(f"  Stop Loss : {INV_SL} USDT")
    print("-" * 50)
    print(f"  Maker Fee : {MAKER_FEE*100}%")
    print(f"  Taker Fee : {TAKER_FEE*100}%")
    print("=" * 50)

    if "YAHAN" in API_KEY:
        print(
            "❌ API KEY DAALO PEHLE!\n"
            "API_KEY = 'apni_key'\n"
            "API_SECRET = 'apna_secret'")
    else:
        threads = [
            threading.Thread(
                target=run_server,
                name="Flask",
                daemon=True),
            threading.Thread(
                target=tg_worker,
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
                target=run_engine,
                name="Engine",
                daemon=True),
        ]

        for t in threads:
            t.start()
            print(f"[✅] {t.name}")
            time.sleep(0.3)

        print("=" * 50)
        print("[✅] Bot Live!")
        print("[✅] Binance Testnet")
        print("[✅] Real Orders!")
        print("=" * 50)

        while True:
            time.sleep(60)
