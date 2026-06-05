"""
ETH Trading Bot
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Sirf YE choose karo:
MODE = "TESTNET"  → Demo trading
MODE = "REAL"     → Real trading

Bas ek line change karo!
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
    return "ETH Bot Running ✅"

def run_server():
    port = int(
        os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  ⚙️ MAIN CONFIG
#  SIRF YAHAN CHANGES KARO
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# ✅ MODE CHOOSE KARO:
# "TESTNET" = Demo trading (safe)
# "REAL"    = Real money trading
MODE = "TESTNET"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TESTNET API KEYS
# testnet.binancefuture.com se lo
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TESTNET_API_KEY    = "H647cSQelN9Im9o22wTu3h3oz3ZTBgxSzV5McQzN7qJoWg94lPGmR6JaCawbmS5S"
TESTNET_API_SECRET = "O2Gz79sooHsYAzd2oyJQ2rmE8KwhhF5JCs9KlwHwFToTitszOaLMRDFYCobz6gSW"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# REAL API KEYS
# binance.com se lo (baad mein)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
REAL_API_KEY    = "REAL_KEY_YAHAN"
REAL_API_SECRET = "REAL_SECRET_YAHAN"

# Telegram
BOT_TOKEN = "8161773850:AAFcWw3UnlSe2TrMooB2uvgZQZUqIW0zW2w"
CHAT_ID   = "7102976298"

# Symbol
SYMBOL = "ETH/USDT"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  TRADING CONFIG
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
LEVERAGE     = 5
CAPITAL_USE  = 80     # 80% use karo
TP_PCT       = 0.15   # 0.15% TP
SL_PCT       = 0.08   # 0.08% SL

# Fees
TAKER_FEE    = 0.0004  # 0.04%

# Speed
SCAN_SEC     = 2       # Har 2 second

# Cooldown
CD_WIN       = 1       # 1s win ke baad
CD_LOSS      = 3       # 3s loss ke baad

# Update
UPDATE_MIN   = 30      # 30 min

# Files
FILES = {
    "capital": "capital_bot.txt",
    "history": "history_bot.json",
}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  AUTO CONFIG
#  Mode ke hisab se automatic set hoga
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

if MODE == "TESTNET":
    API_KEY    = TESTNET_API_KEY
    API_SECRET = TESTNET_API_SECRET
    IS_TESTNET = True
    MODE_NAME  = "🔵 TESTNET (Demo)"
    print("=" * 40)
    print("  MODE: TESTNET (DEMO)")
    print("  Fake money - Safe!")
    print("=" * 40)
else:
    API_KEY    = REAL_API_KEY
    API_SECRET = REAL_API_SECRET
    IS_TESTNET = False
    MODE_NAME  = "🔴 REAL TRADING"
    print("=" * 40)
    print("  MODE: REAL TRADING")
    print("  REAL MONEY!")
    print("=" * 40)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  STATE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

lock  = threading.Lock()
state = {
    "price":     0.0,
    "position":  None,
    "entry":     0.0,
    "tp":        0.0,
    "sl":        0.0,
    "qty":       0.0,
    "cap_used":  0.0,
    "capital":   0.0,
    "start_cap": 0.0,
    "trades":    0,
    "wins":      0,
    "losses":    0,
    "net":       0.0,
    "best":      0.0,
    "worst":     0.0,
    "cycles":    0,
    "mode":      MODE_NAME,
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
#  CAPITAL MANAGER
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def load_cap():
    try:
        with open(
                FILES["capital"],
                "r") as f:
            cap = float(f.read().strip())
            if cap > 0:
                print(
                    f"[CAP] Loaded: "
                    f"{cap:.2f} USDT")
                return cap
    except Exception:
        pass
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
#  HISTORY
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

hist_lock = threading.Lock()

def save_trade(
        side, entry, exit_p,
        gross, fee, net_pnl,
        capital, dur, label, num):
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
                "mode":    MODE,
                "side":    side,
                "entry":   round(entry, 2),
                "exit":    round(exit_p, 2),
                "gross":   round(gross, 4),
                "fee":     round(fee, 4),
                "net":     round(net_pnl, 4),
                "capital": round(capital, 4),
                "dur":     dur,
                "result":  (
                    "WIN" if net_pnl > 0
                    else "LOSS"),
                "label":   label,
            })

            if len(h) > 50000:
                h = h[-50000:]

            with open(
                    FILES["history"],
                    "w",
                    encoding="utf-8") as f:
                json.dump(h, f, indent=2)
    except Exception as e:
        print(f"[HIST] {e}")


def get_today():
    try:
        with open(
                FILES["history"],
                "r",
                encoding="utf-8") as f:
            h = json.load(f)
    except Exception:
        return None

    today = datetime.now().strftime(
        "%d/%m/%Y")
    t = [
        x for x in h
        if x["date"] == today]

    if not t:
        return None

    nets   = [x["net"] for x in t]
    fees   = [x["fee"] for x in t]
    wins   = len([
        x for x in t
        if x["result"] == "WIN"])
    losses = len(t) - wins
    hours  = max(1, len(set(
        x["time"][:2] for x in t)))

    return {
        "total":   len(t),
        "wins":    wins,
        "losses":  losses,
        "wr":      round(
            wins/len(t)*100, 1),
        "net":     round(sum(nets), 4),
        "fees":    round(sum(fees), 4),
        "best":    round(max(nets), 4),
        "worst":   round(min(nets), 4),
        "per_hr":  round(
            sum(nets)/hours, 4),
        "capital": t[-1]["capital"],
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  EXCHANGE
#  Testnet ya Real - Auto decide
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def get_exchange():
    while True:
        try:
            if IS_TESTNET:
                # ✅ TESTNET
                ex = ccxt.binanceusdm({
                    "apiKey":  API_KEY,
                    "secret":  API_SECRET,
                    "enableRateLimit":
                        True,
                    "rateLimit": 100,
                    "options": {
                        "defaultType":
                            "future",
                        "sandboxMode":
                            True,
                    },
                })
                ex.set_sandbox_mode(True)
                print(
                    "[EXCHANGE] "
                    "Testnet ✅")
            else:
                # ✅ REAL
                ex = ccxt.binanceusdm({
                    "apiKey":  API_KEY,
                    "secret":  API_SECRET,
                    "enableRateLimit":
                        True,
                    "rateLimit": 50,
                    "options": {
                        "defaultType":
                            "future",
                    },
                })
                print(
                    "[EXCHANGE] "
                    "REAL Binance ✅")

            ex.load_markets()

            try:
                ex.set_leverage(
                    LEVERAGE, SYMBOL)
                print(
                    f"[LEVERAGE] "
                    f"{LEVERAGE}x set ✅")
            except Exception as e:
                print(
                    f"[LEVERAGE] {e}")

            return ex

        except Exception as e:
            print(
                f"[CONN ERR] {e}\n"
                f"15s mein retry...")
            time.sleep(15)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  BALANCE FETCH - FIXED!
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def get_balance(ex):
    """
    ✅ FIXED Balance Fetch

    Testnet aur Real dono ke liye
    Sahi balance fetch karega
    """
    try:
        bal = ex.fetch_balance()

        # Method 1: Normal way
        try:
            usdt = float(
                bal["USDT"]["free"] or 0)
            if usdt > 0:
                print(
                    f"[BAL M1] "
                    f"{usdt:.2f} USDT")
                return usdt
        except Exception:
            pass

        # Method 2: Total way
        try:
            usdt = float(
                bal["total"].get(
                    "USDT", 0) or 0)
            if usdt > 0:
                print(
                    f"[BAL M2] "
                    f"{usdt:.2f} USDT")
                return usdt
        except Exception:
            pass

        # Method 3: Info way
        try:
            info   = bal.get("info", {})
            assets = info.get(
                "assets", [])
            for a in assets:
                if a.get(
                        "asset") == "USDT":
                    usdt = float(
                        a.get(
                            "availableBalance",
                            0) or 0)
                    if usdt > 0:
                        print(
                            f"[BAL M3] "
                            f"{usdt:.2f} USDT")
                        return usdt
        except Exception:
            pass

        # Method 4: Free dict
        try:
            free = bal.get("free", {})
            usdt = float(
                free.get("USDT", 0) or 0)
            if usdt > 0:
                print(
                    f"[BAL M4] "
                    f"{usdt:.2f} USDT")
                return usdt
        except Exception:
            pass

        print("[BAL] Koi method kaam nahi kiya")
        return 0.0

    except Exception as e:
        print(f"[BAL ERR] {e}")
        return 0.0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  TELEGRAM
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
                                    f"🤖 ETH BOT\n"
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
#  SIGNAL
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

price_hist = deque(maxlen=20)

def get_signal(price):
    price_hist.append(price)
    if len(price_hist) < 6:
        return "WAIT"

    prices = list(price_hist)
    recent = prices[-3:]
    older  = prices[-6:-3]

    r_avg = sum(recent) / len(recent)
    o_avg = sum(older)  / len(older)

    change = (
        (r_avg - o_avg) /
        o_avg * 100)

    if change > 0.02:
        return "BUY"
    elif change < -0.02:
        return "SELL"
    else:
        return "WAIT"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  ORDERS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def open_trade(ex, side, price, qty):
    try:
        if side == "BUY":
            o = ex.create_market_buy_order(
                SYMBOL, qty)
        else:
            o = ex.create_market_sell_order(
                SYMBOL, qty)

        fill = float(
            o.get("average") or
            o.get("price") or price)
        fee  = fill * qty * TAKER_FEE

        return fill, fee

    except Exception as e:
        print(f"[OPEN] {e}")
        return None, 0


def close_trade(ex, side, qty):
    try:
        close = (
            "sell"
            if side == "BUY"
            else "buy")

        if close == "sell":
            o = ex.create_market_sell_order(
                SYMBOL, qty,
                {"reduceOnly": True})
        else:
            o = ex.create_market_buy_order(
                SYMBOL, qty,
                {"reduceOnly": True})

        fill = float(
            o.get("average") or
            o.get("price") or 0)
        fee  = fill * qty * TAKER_FEE

        return fill, fee

    except Exception as e:
        print(f"[CLOSE] {e}")
        return None, 0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  UPDATE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def run_update():
    time.sleep(60)
    while True:
        try:
            st    = get_state()
            today = get_today()
            now   = datetime.now()\
                .strftime(
                    "%Y-%m-%d %H:%M")

            cap   = st["capital"]
            scap  = st["start_cap"]
            net   = st["net"]
            tc    = st["trades"]
            wins  = st["wins"]
            losses= st["losses"]
            price = st["price"]
            pos   = st["position"]
            cyc   = st["cycles"]
            growth= round(cap-scap, 4)
            growp = round(
                growth /
                max(1, scap) * 100, 2)
            wr    = round(
                wins /
                max(1, wins+losses)
                * 100, 1)

            if pos:
                entry = st["entry"]
                pnl_now = (
                    (price - entry) *
                    st["qty"]
                    if pos == "BUY"
                    else
                    (entry - price) *
                    st["qty"])
                icon = (
                    "🟢" if pnl_now >= 0
                    else "🔴")
                pos_txt = (
                    f"{icon} {pos}\n"
                    f"Entry  : {entry:.2f}\n"
                    f"Now    : {price:.2f}\n"
                    f"TP     : {st['tp']:.2f}\n"
                    f"SL     : {st['sl']:.2f}\n"
                    f"PnL Now: "
                    f"{pnl_now:+.4f}\n")
            else:
                pos_txt = (
                    f"⏳ WAIT\n"
                    f"Price  : {price:.2f}\n")

            msg = (
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"  ETH BOT UPDATE\n"
                f"  {now}\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"{st['mode']}\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"POSITION\n"
                f"{pos_txt}"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"STATS\n"
                f"Cycles : {cyc}\n"
                f"Trades : {tc}\n"
                f"Wins   : {wins} ✅\n"
                f"Losses : {losses} ❌\n"
                f"WR     : {wr}%\n"
                f"Net    : {net:+.4f}\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"CAPITAL\n"
                f"Start  : {scap:.2f}\n"
                f"Now    : {cap:.4f}\n"
                f"Growth : {growth:+.4f}\n"
                f"ROI    : {growp:+.2f}%\n"
                f"━━━━━━━━━━━━━━━━━━━━━━")

            if today:
                ph = today["per_hr"]
                pd = round(ph*24, 2)
                pm = round(pd*30, 2)
                msg += (
                    f"\nTODAY\n"
                    f"Trades : {today['total']}\n"
                    f"WR     : {today['wr']}%\n"
                    f"Fees   : -{today['fees']}\n"
                    f"Net    : "
                    f"{today['net']:+.4f}\n"
                    f"Per Hr : +{ph:.4f}\n"
                    f"Per Day: +{pd:.2f}\n"
                    f"Monthly: +{pm:.2f}\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━")

            send_tg(msg)

        except Exception as e:
            print(f"[UPD] {e}")

        time.sleep(UPDATE_MIN * 60)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  DAILY
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def run_daily():
    while True:
        try:
            ist = timezone(timedelta(
                hours=5, minutes=30))
            now = datetime.now(ist)
            if (now.hour == 23 and
                    now.minute == 59):
                today = get_today()
                st    = get_state()
                date  = now.strftime(
                    "%d/%m/%Y")
                if today:
                    growth = round(
                        st["capital"] -
                        st["start_cap"],
                        4)
                    roi    = round(
                        growth /
                        max(1,
                            st["start_cap"])
                        * 100, 2)
                    pm = round(
                        today["net"]*30, 2)

                    msg = (
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"  DAILY REPORT\n"
                        f"  {date}\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"{st['mode']}\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"TRADES\n"
                        f"Total  : {today['total']}\n"
                        f"Wins   : {today['wins']}\n"
                        f"Losses : {today['losses']}\n"
                        f"WR     : {today['wr']}%\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"PNL\n"
                        f"Net    : "
                        f"{today['net']:+.4f}\n"
                        f"Best   : "
                        f"+{today['best']:.4f}\n"
                        f"Worst  : "
                        f"{today['worst']:.4f}\n"
                        f"Fees   : "
                        f"-{today['fees']:.4f}\n"
                        f"Monthly: +{pm:.2f}\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"CAPITAL\n"
                        f"Start  : "
                        f"{st['start_cap']:.2f}\n"
                        f"Now    : "
                        f"{st['capital']:.4f}\n"
                        f"Growth : {growth:+.4f}\n"
                        f"ROI    : {roi:+.2f}%\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━")
                else:
                    msg = (
                        f"DAILY {date}\n"
                        f"Koi trade nahi")
                send_tg(msg)
                time.sleep(70)
        except Exception as e:
            print(f"[DAY] {e}")
        time.sleep(30)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  MAIN ENGINE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def run_engine():

    ex = get_exchange()

    # ✅ FIXED: Balance fetch
    print("[BAL] Fetching balance...")
    balance = get_balance(ex)

    # Balance mile ya na mile
    # File se load karo
    saved = load_cap()

    if saved and saved > 0:
        # File mein saved capital hai
        capital = saved
        print(
            f"[CAP] File se: "
            f"{capital:.2f} USDT")
    elif balance and balance > 0:
        # Exchange se mila
        capital = balance
        print(
            f"[CAP] Exchange se: "
            f"{capital:.2f} USDT")
        save_cap(capital)
    else:
        # Default
        capital = 10000.0
        print(
            f"[CAP] Default: "
            f"{capital:.2f} USDT")
        save_cap(capital)

    start_cap   = capital
    position    = None
    entry_price = 0.0
    entry_time  = None
    qty         = 0.0
    tp_price    = 0.0
    sl_price    = 0.0
    cap_used    = 0.0
    entry_fee   = 0.0
    cd_end      = None
    trades      = 0
    wins        = 0
    losses      = 0
    net         = 0.0
    best        = 0.0
    worst       = 0.0
    cycles      = 0

    print(
        f"\n[START] ✅\n"
        f"Mode   : {MODE_NAME}\n"
        f"Capital: {capital:.2f} USDT\n"
        f"Symbol : {SYMBOL}\n"
        f"TP     : {TP_PCT}%\n"
        f"SL     : {SL_PCT}%\n")

    send_tg(
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"  ETH BOT STARTED\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{MODE_NAME}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Capital : {capital:.2f} USDT\n"
        f"Symbol  : {SYMBOL}\n"
        f"Leverage: {LEVERAGE}x\n"
        f"TP      : {TP_PCT}%\n"
        f"SL      : {SL_PCT}%\n"
        f"Scan    : {SCAN_SEC}s\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Bot shuru ho gaya!\n"
        f"Trades aana shuru honge!\n"
        f"━━━━━━━━━━━━━━━━━━━━━━"
    )

    while True:
        try:
            loop_st = time.time()
            cycles += 1

            # Price fetch
            try:
                ticker = ex.fetch_ticker(
                    SYMBOL)
                price  = float(
                    ticker["last"])
            except Exception:
                time.sleep(SCAN_SEC)
                continue

            # ━━━━━━━━━━━━━━━━━━━━━━━━━━
            # POSITION MONITOR
            # ━━━━━━━━━━━━━━━━━━━━━━━━━━
            if position is not None:
                held = round(
                    (datetime.now() -
                     entry_time
                     ).total_seconds(), 1)

                hit_tp = (
                    (position == "BUY"
                     and price >= tp_price)
                    or
                    (position == "SELL"
                     and price <= tp_price))

                hit_sl = (
                    (position == "BUY"
                     and price <= sl_price)
                    or
                    (position == "SELL"
                     and price >= sl_price))

                if hit_tp or hit_sl:
                    # Close karo
                    exit_px, exit_fee = (
                        close_trade(
                            ex,
                            position,
                            qty))

                    if not exit_px:
                        exit_px  = price
                        exit_fee = (
                            price * qty *
                            TAKER_FEE)

                    # PnL
                    if position == "BUY":
                        gross = (
                            (exit_px -
                             entry_price) *
                            qty)
                    else:
                        gross = (
                            (entry_price -
                             exit_px) *
                            qty)

                    total_fee = (
                        entry_fee +
                        exit_fee)
                    net_pnl = (
                        gross - total_fee)

                    capital += net_pnl
                    net     += net_pnl
                    trades  += 1

                    if hit_tp:
                        label = "TAKE PROFIT ✅"
                        icon  = "🟢"
                        wins += 1
                        cd_end = (
                            time.time() +
                            CD_WIN)
                    else:
                        label = "STOP LOSS ❌"
                        icon  = "🔴"
                        losses += 1
                        cd_end = (
                            time.time() +
                            CD_LOSS)

                    if net_pnl > best:
                        best = net_pnl
                    if (worst == 0 or
                            net_pnl < worst):
                        worst = net_pnl

                    wr = round(
                        wins /
                        max(1, wins+losses)
                        * 100, 1)

                    save_cap(capital)
                    save_trade(
                        position,
                        entry_price,
                        exit_px,
                        gross,
                        total_fee,
                        net_pnl,
                        capital,
                        f"{held}s",
                        label,
                        trades)

                    print(
                        f"[#{trades}] "
                        f"{label} | "
                        f"{position} | "
                        f"Net={net_pnl:+.4f} | "
                        f"Cap={capital:.2f} | "
                        f"WR={wr}%")

                    send_tg(
                        f"{icon} {label}\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"Trade # : {trades}\n"
                        f"Mode    : {MODE}\n"
                        f"Side    : {position}\n"
                        f"Entry   : "
                        f"{entry_price:.2f}\n"
                        f"Exit    : "
                        f"{exit_px:.2f}\n"
                        f"Time    : {held}s\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"Gross   : "
                        f"{gross:+.4f} USDT\n"
                        f"Fee     : "
                        f"-{total_fee:.4f} USDT\n"
                        f"NET PnL : "
                        f"{net_pnl:+.4f} USDT\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"Capital : "
                        f"{capital:.4f} USDT\n"
                        f"Win Rate: {wr}%\n"
                        f"Total   : {trades}\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━"
                    )

                    # Reset
                    position    = None
                    entry_price = 0.0
                    entry_time  = None
                    qty         = 0.0
                    tp_price    = 0.0
                    sl_price    = 0.0
                    cap_used    = 0.0
                    entry_fee   = 0.0

            # ━━━━━━━━━━━━━━━━━━━━━━━━━━
            # COOLDOWN
            # ━━━━━━━━━━━━━━━━━━━━━━━━━━
            if (cd_end and
                    time.time() < cd_end):
                set_state(
                    price=price,
                    cycles=cycles)
                elapsed = (
                    time.time() - loop_st)
                time.sleep(max(
                    0,
                    SCAN_SEC - elapsed))
                continue

            # ━━━━━━━━━━━━━━━━━━━━━━━━━━
            # NEW ENTRY
            # ━━━━━━━━━━━━━━━━━━━━━━━━━━
            if position is None:
                signal = get_signal(price)

                if signal in [
                        "BUY", "SELL"]:

                    cap_used = (
                        capital *
                        CAPITAL_USE / 100)
                    qty = round(
                        cap_used *
                        LEVERAGE / price,
                        3)
                    qty = max(0.001, qty)

                    fill_px, e_fee = (
                        open_trade(
                            ex,
                            signal,
                            price,
                            qty))

                    if fill_px:
                        entry_price = fill_px
                        entry_time  = (
                            datetime.now())
                        position    = signal
                        entry_fee   = e_fee

                        if signal == "BUY":
                            tp_price = round(
                                fill_px *
                                (1 +
                                 TP_PCT/100),
                                2)
                            sl_price = round(
                                fill_px *
                                (1 -
                                 SL_PCT/100),
                                2)
                        else:
                            tp_price = round(
                                fill_px *
                                (1 -
                                 TP_PCT/100),
                                2)
                            sl_price = round(
                                fill_px *
                                (1 +
                                 SL_PCT/100),
                                2)

                        exp_w = round(
                            cap_used *
                            LEVERAGE *
                            TP_PCT/100, 2)
                        exp_l = round(
                            cap_used *
                            LEVERAGE *
                            SL_PCT/100, 2)

                        print(
                            f"[ENTRY] "
                            f"{signal} | "
                            f"{qty}@"
                            f"{fill_px:.2f}")

                        send_tg(
                            f"🚀 ENTRY "
                            f"#{trades+1}\n"
                            f"━━━━━━━━━━━━━━━━━━━━━━\n"
                            f"Mode    : {MODE}\n"
                            f"Side    : {signal}\n"
                            f"Entry   : "
                            f"{fill_px:.2f}\n"
                            f"TP      : "
                            f"{tp_price:.2f}\n"
                            f"SL      : "
                            f"{sl_price:.2f}\n"
                            f"━━━━━━━━━━━━━━━━━━━━━━\n"
                            f"Capital : "
                            f"{cap_used:.2f}\n"
                            f"Qty     : {qty}\n"
                            f"Exp Win : +{exp_w}\n"
                            f"Exp Loss: -{exp_l}\n"
                            f"━━━━━━━━━━━━━━━━━━━━━━"
                        )

            # State update
            set_state(
                price=price,
                position=position,
                entry=entry_price,
                tp=tp_price,
                sl=sl_price,
                qty=qty,
                cap_used=cap_used,
                capital=capital,
                start_cap=start_cap,
                trades=trades,
                wins=wins,
                losses=losses,
                net=net,
                best=best,
                worst=worst,
                cycles=cycles,
            )

            if cycles % 30 == 0:
                wr = round(
                    wins /
                    max(1, wins+losses)
                    * 100, 1)
                print(
                    f"[C{cycles}] "
                    f"ETH={price:.2f} | "
                    f"Pos={position} | "
                    f"Net={net:+.4f} | "
                    f"T={trades} "
                    f"WR={wr}%")

            elapsed = (
                time.time() - loop_st)
            time.sleep(max(
                0, SCAN_SEC - elapsed))

        except Exception as e:
            err = str(e)
            print(f"[ERR] {err}")
            if "429" in err:
                time.sleep(10)
            elif ("connection" in
                  err.lower() or
                  "timeout" in
                  err.lower()):
                try:
                    ex = get_exchange()
                except Exception:
                    pass
                time.sleep(5)
            else:
                time.sleep(2)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  START
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

if __name__ == "__main__":

    print("=" * 45)
    print("  ETH TRADING BOT")
    print(f"  {MODE_NAME}")
    print("=" * 45)
    print(f"  Symbol  : {SYMBOL}")
    print(f"  Leverage: {LEVERAGE}x")
    print(f"  TP      : {TP_PCT}%")
    print(f"  SL      : {SL_PCT}%")
    print("=" * 45)

    has_key = (
        "YAHAN" not in API_KEY and
        len(API_KEY) > 10)

    if not has_key:
        print(
            "\n❌ API KEY DAALO!\n"
            "\nTestnet ke liye:\n"
            "TESTNET_API_KEY = "
            "'apni_testnet_key'\n"
            "TESTNET_API_SECRET = "
            "'apna_testnet_secret'\n")
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

        print("=" * 45)
        print(f"[✅] {MODE_NAME}")
        print("[✅] Bot Live!")
        print("=" * 45)

        while True:
            time.sleep(60)
