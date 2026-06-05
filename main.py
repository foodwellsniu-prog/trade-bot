"""
ETH Market Making HFT Bot v6.0
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Exchange  : MEXC Futures
Symbol    : ETH/USDT
Capital   : 10,000 USDT
Leverage  : 5x

IMPROVEMENTS v6.0:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. DYNAMIC SPREAD
   Market quiet  = Wide spread
   Market active = Tight spread
   Auto adjust every cycle

2. MULTI LEVEL ORDERS
   3 levels Bid side
   3 levels Ask side
   Zyada fills = Zyada profit

3. SMART INVENTORY SKEWING
   Inventory zyada = Ask side push
   Inventory kam   = Bid side push
   Auto balance

4. VOLATILITY DETECTOR
   High vol = Wide spread
   Low vol  = Tight spread

5. SMART HEDGE
   Partial hedge
   Best price pe hedge
   Minimum taker fee

Fee = 0.00% Maker (FREE!)
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
    return "ETH MM HFT Bot v6.0 ✅"

def run_server():
    port = int(
        os.environ.get("PORT", 10000))
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
CAPITAL_USE = 80        # 80%
LEVERAGE    = 5

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  DYNAMIC SPREAD CONFIG
#  Market condition ke hisab se
#  spread auto adjust hoga
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Base spread (normal market)
BASE_HALF_SPREAD  = 0.02   # 0.02 USDT

# Minimum spread (active market)
MIN_HALF_SPREAD   = 0.01   # 0.01 USDT

# Maximum spread (quiet market)
MAX_HALF_SPREAD   = 0.05   # 0.05 USDT

# Volatility thresholds
VOL_LOW    = 0.05   # 0.05% = low vol
VOL_HIGH   = 0.15   # 0.15% = high vol

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  MULTI LEVEL CONFIG
#  3 levels pe orders lagao
#  Level 1 = closest to mid
#  Level 3 = farthest from mid
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

LEVELS = 3   # 3 bid + 3 ask = 6 orders

# Har level ka spread multiplier
# Level 1 = 1x spread
# Level 2 = 2x spread
# Level 3 = 3x spread
LEVEL_MULTIPLIER = [1.0, 2.0, 3.0]

# Har level ka qty multiplier
# Level 1 = 50% qty
# Level 2 = 30% qty
# Level 3 = 20% qty
LEVEL_QTY = [0.50, 0.30, 0.20]

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  INVENTORY CONFIG
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

MAX_INV       = 3.0    # Max 3 ETH
HEDGE_INV     = 2.0    # Hedge at 2 ETH
TARGET_INV    = 0.0    # Target = flat
INV_STOP_LOSS = -80.0  # -80 USDT stop

# Skew factor
# Inventory zyada = price shift karo
SKEW_FACTOR = 0.01  # 0.01 USDT per ETH

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  FEE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

MAKER_FEE = 0.0000   # 0% FREE!
TAKER_FEE = 0.0001   # 0.01% hedge only

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  SPEED CONFIG
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

ORDER_REFRESH     = 0.3    # 300ms
MAX_MKT_SPREAD    = 0.20   # Skip if > 0.20
UPDATE_INTERVAL   = 1800   # 30 min
VOL_WINDOW        = 20     # 20 prices for vol

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  FILES
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

FILES = {
    "capital": "capital_v6.txt",
    "history": "history_v6.json",
    "stats":   "stats_v6.json",
}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  STATE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

state_lock = threading.Lock()

state = {
    # Market
    "mid":          0.0,
    "best_bid":     0.0,
    "best_ask":     0.0,
    "mkt_spread":   0.0,
    "volatility":   0.0,
    "dyn_spread":   BASE_HALF_SPREAD,

    # Orders
    "bid_orders":   [],
    "ask_orders":   [],
    "active_orders":0,

    # Inventory
    "inventory":    0.0,
    "avg_price":    0.0,
    "inv_pnl":      0.0,
    "skew":         0.0,

    # Capital
    "capital":      CAPITAL,

    # Stats
    "trade_count":  0,
    "buy_fills":    0,
    "sell_fills":   0,
    "gross_profit": 0.0,
    "hedge_cost":   0.0,
    "net_profit":   0.0,
    "best_trade":   0.0,
    "total_volume": 0.0,

    # Status
    "status":       "STARTING",
    "cycles":       0,
    "uptime_min":   0,
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
#  VOLATILITY CALCULATOR
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

price_buffer = deque(maxlen=VOL_WINDOW)
vol_lock     = threading.Lock()

def add_price(price):
    with vol_lock:
        price_buffer.append(price)

def get_volatility():
    """
    Price volatility calculate karo
    Last N prices ka std deviation

    Low vol  = Tight market = Wide spread
    High vol = Active market = Tight spread
    """
    with vol_lock:
        if len(price_buffer) < 3:
            return 0.0
        prices = list(price_buffer)

    if len(prices) < 2:
        return 0.0

    returns = []
    for i in range(1, len(prices)):
        if prices[i-1] > 0:
            r = abs(
                (prices[i] - prices[i-1]) /
                prices[i-1] * 100)
            returns.append(r)

    if not returns:
        return 0.0

    return float(np.mean(returns))


def calc_dynamic_spread(vol):
    """
    Volatility ke hisab se spread:

    Low vol  (< 0.05%) = MAX spread (0.05)
    Normal   (0.05-0.15%) = BASE (0.02)
    High vol (> 0.15%) = MIN spread (0.01)

    Logic:
    High vol = Zyada movement
             = Orders jaldi fill honge
             = Tight spread bhi chalega
             = Zyada fills milenge

    Low vol  = Kam movement
             = Wide spread rakho
             = Zyada profit per fill
    """
    if vol < VOL_LOW:
        # Low volatility - wide spread
        spread = MAX_HALF_SPREAD
        label  = "LOW VOL → WIDE"
    elif vol > VOL_HIGH:
        # High volatility - tight spread
        spread = MIN_HALF_SPREAD
        label  = "HIGH VOL → TIGHT"
    else:
        # Normal - interpolate
        ratio  = (
            (vol - VOL_LOW) /
            (VOL_HIGH - VOL_LOW))
        spread = (
            MAX_HALF_SPREAD -
            ratio * (
                MAX_HALF_SPREAD -
                MIN_HALF_SPREAD))
        label  = "NORMAL"

    spread = round(
        max(MIN_HALF_SPREAD,
            min(MAX_HALF_SPREAD, spread)),
        4)

    return spread, label


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  INVENTORY SKEWING
#  Inventory zyada ho to price shift karo
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def calc_skew(inventory):
    """
    Inventory skewing:

    Long  (+inv) = Bid raise karo
                   Ask lower karo
                   = Selling encourage

    Short (-inv) = Bid lower karo
                   Ask raise karo
                   = Buying encourage

    Skew = inventory × SKEW_FACTOR
    """
    skew = -inventory * SKEW_FACTOR
    return round(skew, 4)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  MULTI LEVEL PRICES
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def calc_level_prices(
        mid, half_spread, skew, total_qty):
    """
    3 levels pe prices calculate karo

    Skew adjusted mid:
    adj_mid = mid + skew

    Level 1: adj_mid ± (spread × 1)
    Level 2: adj_mid ± (spread × 2)
    Level 3: adj_mid ± (spread × 3)

    Qty per level:
    Level 1 = 50% of total
    Level 2 = 30% of total
    Level 3 = 20% of total
    """
    adj_mid   = mid + skew
    bid_levels = []
    ask_levels = []

    for i in range(LEVELS):
        mult     = LEVEL_MULTIPLIER[i]
        qty_pct  = LEVEL_QTY[i]
        qty      = round(
            total_qty * qty_pct, 4)
        qty      = max(0.001, qty)

        bid_px = round(
            adj_mid - half_spread * mult, 2)
        ask_px = round(
            adj_mid + half_spread * mult, 2)

        bid_levels.append({
            "level": i+1,
            "price": bid_px,
            "qty":   qty,
            "id":    None,
        })
        ask_levels.append({
            "level": i+1,
            "price": ask_px,
            "qty":   qty,
            "id":    None,
        })

    return bid_levels, ask_levels


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  CAPITAL
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def load_capital():
    try:
        with open(FILES["capital"], "r") as f:
            cap = float(f.read().strip())
            print(f"[CAP] {cap:.2f} USDT")
            return cap
    except Exception:
        save_capital(CAPITAL)
        return CAPITAL

def save_capital(cap):
    try:
        with open(FILES["capital"], "w") as f:
            f.write(str(round(cap, 6)))
    except Exception as e:
        print(f"[CAP ERR] {e}")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  TRADE HISTORY
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

history_lock = threading.Lock()

def save_trade(
        ttype, price, qty,
        profit, capital, num, note=""):
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


def get_stats():
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

    total   = len(trades)
    buys    = len([
        t for t in trades
        if t["type"] == "BUY_FILL"])
    sells   = len([
        t for t in trades
        if t["type"] == "SELL_FILL"])
    hedges  = len([
        t for t in trades
        if t["type"] == "HEDGE"])
    gross   = round(sum(
        t["profit"] for t in trades
        if t["type"] in [
            "BUY_FILL","SELL_FILL"]), 4)
    hcost   = round(sum(
        t["profit"] for t in trades
        if t["type"] == "HEDGE"), 4)
    net     = round(gross + hcost, 4)
    vol     = round(sum(
        t["price"] * t["qty"]
        for t in trades), 2)

    # Per hour
    hours = max(1, len(set(
        t["time"][:2]
        for t in trades)))
    p_hr  = round(net / hours, 4)
    p_day = round(p_hr * 24, 4)

    best  = round(max(
        (t["profit"] for t in trades),
        default=0), 4)

    return {
        "total":   total,
        "buys":    buys,
        "sells":   sells,
        "hedges":  hedges,
        "gross":   gross,
        "hcost":   hcost,
        "net":     net,
        "volume":  vol,
        "per_hr":  p_hr,
        "per_day": p_day,
        "best":    best,
        "capital": trades[-1]["capital"],
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  EXCHANGE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def get_exchange():
    while True:
        try:
            ex = ccxt.mexc({
                "apiKey":    API_KEY,
                "secret":    API_SECRET,
                "enableRateLimit": True,
                "rateLimit": 10,
                "options": {
                    "defaultType":
                        "swap",
                    "adjustForTimeDifference":
                        True,
                },
            })
            ex.load_markets()
            print("[MEXC] Connected ✅")
            return ex
        except Exception as e:
            print(
                f"[RECONNECT] {e}")
            time.sleep(15)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  ORDER FUNCTIONS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def place_limit(ex, side, price, qty):
    """
    Maker limit order
    postOnly = guaranteed maker
    Fee = 0%
    """
    try:
        o = ex.create_limit_order(
            symbol=SYMBOL,
            side=side,
            amount=qty,
            price=price,
            params={"postOnly": True})
        return o["id"], price, qty
    except Exception as e:
        err = str(e)
        if ("postOnly" not in err and
                "maker" not in
                err.lower()):
            print(
                f"[LIMIT ERR] "
                f"{side}@{price}: {e}")
        return None, 0, 0


def cancel_all_orders(ex, orders):
    """Saare orders cancel karo"""
    cancelled = 0
    for o in orders:
        oid = o.get("id")
        if oid:
            try:
                ex.cancel_order(
                    oid, SYMBOL)
                cancelled += 1
            except Exception as e:
                if ("not found" not in
                        str(e).lower()):
                    pass
    return cancelled


def check_fill(ex, order_id):
    """
    Order status check karo

    Returns:
    status, filled_qty, avg_price
    """
    try:
        if not order_id:
            return "none", 0.0, 0.0

        o      = ex.fetch_order(
            order_id, SYMBOL)
        status = o.get("status", "open")
        filled = float(
            o.get("filled", 0))
        price  = float(o.get(
            "average",
            o.get("price", 0)))

        if status == "closed":
            return "filled", filled, price
        elif filled > 0:
            return "partial", filled, price
        elif status == "canceled":
            return "cancelled", 0.0, 0.0
        else:
            return "open", 0.0, 0.0

    except Exception as e:
        print(f"[FILL CHK] {e}")
        return "error", 0.0, 0.0


def hedge_market(ex, side, qty):
    """
    Emergency hedge - market order
    Taker fee = 0.01%
    """
    try:
        o     = ex.create_market_order(
            SYMBOL, side, qty)
        price = float(o.get(
            "average",
            o.get("price", 0)))
        fee   = price * qty * TAKER_FEE
        print(
            f"[HEDGE] {side} "
            f"{qty:.4f}@{price:.2f} "
            f"fee={fee:.4f}")
        return price, fee
    except Exception as e:
        print(f"[HEDGE ERR] {e}")
        return 0.0, 0.0


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
                                    f"[v6.0]\n"
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
            stats = get_stats()
            now   = datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S")

            inv  = st["inventory"]
            mid  = st["mid"]
            cap  = st["capital"]
            net  = st["net_profit"]
            bf   = st["buy_fills"]
            sf   = st["sell_fills"]
            tc   = st["trade_count"]
            vol  = st["volatility"]
            ds   = st["dyn_spread"]
            skew = st["skew"]
            cyc  = st["cycles"]
            ipl  = st["inv_pnl"]

            inv_v = inv * mid

            msg = (
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"  MM BOT v6.0 UPDATE\n"
                f"  {now}\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"MARKET\n"
                f"Price    : {mid:.4f}\n"
                f"Vol      : {vol:.4f}%\n"
                f"Dyn Sprd : ±{ds:.4f}\n"
                f"Skew     : {skew:+.4f}\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"INVENTORY\n"
                f"ETH Held : {inv:.4f}\n"
                f"Value    : {inv_v:.2f} USDT\n"
                f"Inv PnL  : {ipl:+.4f} USDT\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"STATS\n"
                f"Cycles   : {cyc}\n"
                f"Trades   : {tc}\n"
                f"BuyFills : {bf}\n"
                f"SellFills: {sf}\n"
                f"Net PnL  : {net:+.4f} USDT\n"
                f"Capital  : {cap:.4f} USDT\n"
                f"━━━━━━━━━━━━━━━━━━━━━━")

            if stats:
                msg += (
                    f"\nTODAY\n"
                    f"Total    : {stats['total']}\n"
                    f"Buys     : {stats['buys']}\n"
                    f"Sells    : {stats['sells']}\n"
                    f"Hedges   : {stats['hedges']}\n"
                    f"Volume   : "
                    f"${stats['volume']:,.2f}\n"
                    f"Gross    : "
                    f"{stats['gross']:+.4f}\n"
                    f"Hedge    : "
                    f"{stats['hcost']:+.4f}\n"
                    f"NET PnL  : "
                    f"{stats['net']:+.4f} USDT\n"
                    f"Per Hour : "
                    f"+{stats['per_hr']:.4f}\n"
                    f"Per Day~ : "
                    f"+{stats['per_day']:.4f}\n"
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

                stats = get_stats()
                today = now.strftime(
                    "%d/%m/%Y")

                if stats:
                    pm = round(
                        stats["net"] * 30, 2)
                    roi = round(
                        stats["net"] /
                        CAPITAL * 100, 4)

                    msg = (
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"  DAILY REPORT v6.0\n"
                        f"  {today}\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"Exchange : MEXC\n"
                        f"Strategy : Market Making\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"TRADES\n"
                        f"Total    : {stats['total']}\n"
                        f"Buy Fill : {stats['buys']}\n"
                        f"Sell Fill: {stats['sells']}\n"
                        f"Hedges   : {stats['hedges']}\n"
                        f"Volume   : "
                        f"${stats['volume']:,.2f}\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"PNL\n"
                        f"Gross    : "
                        f"{stats['gross']:+.4f}\n"
                        f"Hedge    : "
                        f"{stats['hcost']:+.4f}\n"
                        f"NET PnL  : "
                        f"{stats['net']:+.4f} USDT\n"
                        f"Daily ROI: {roi}%\n"
                        f"Per Hour : "
                        f"+{stats['per_hr']:.4f}\n"
                        f"Monthly~ : "
                        f"+{pm:.2f} USDT\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"Best Fill: "
                        f"+{stats['best']:.4f}\n"
                        f"Capital  : "
                        f"{stats['capital']:.4f}\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"FEE\n"
                        f"Maker    : 0.00% FREE\n"
                        f"Hedge    : 0.01% only\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━")
                else:
                    msg = (
                        f"DAILY {today}\n"
                        f"No trades today")

                send_telegram(msg)
                time.sleep(70)

        except Exception as e:
            print(f"[DAY ERR] {e}")

        time.sleep(30)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  MAIN ENGINE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def run_engine():
    """
    Main Market Making Loop

    EVERY 300ms:
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    1. OB fetch karo
    2. Volatility calculate karo
    3. Dynamic spread set karo
    4. Inventory skew calculate karo
    5. 3 Level prices calculate karo
    6. Old orders cancel karo
    7. Fill check karo
    8. Naye orders lagao
    9. Inventory manage karo
    10. Repeat!
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
    total_volume = 0.0
    best_trade   = 0.0
    cycles       = 0

    # Active orders
    # [{level, price, qty, id, side}]
    bid_orders = []
    ask_orders = []

    start_time = time.time()

    print("[ENGINE v6.0] Started ✅")

    # Startup message
    cap_use = capital * CAPITAL_USE / 100
    exp     = cap_use * LEVERAGE

    send_telegram(
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"  MM HFT BOT v6.0\n"
        f"  MEXC FUTURES\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Capital  : {capital:.2f} USDT\n"
        f"Use(80%) : {cap_use:.2f} USDT\n"
        f"Leverage : {LEVERAGE}x\n"
        f"Exposure : {exp:.2f} USDT\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"IMPROVEMENTS v6.0:\n"
        f"✅ Dynamic Spread\n"
        f"✅ 3 Level Orders\n"
        f"✅ Inventory Skew\n"
        f"✅ Smart Hedge\n"
        f"✅ Volatility Based\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"LEVELS:\n"
        f"L1: ±{BASE_HALF_SPREAD} "
        f"(50% qty)\n"
        f"L2: ±{BASE_HALF_SPREAD*2} "
        f"(30% qty)\n"
        f"L3: ±{BASE_HALF_SPREAD*3} "
        f"(20% qty)\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"FEE: 0.00% (Maker FREE)\n"
        f"━━━━━━━━━━━━━━━━━━━━━━"
    )

    while True:
        try:
            loop_start = time.time()
            cycles    += 1

            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            # STEP 1: ORDER BOOK
            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            ob = ex.fetch_order_book(
                SYMBOL, limit=10)

            best_bid  = float(
                ob["bids"][0][0])
            best_ask  = float(
                ob["asks"][0][0])
            mid       = round(
                (best_bid + best_ask) / 2,
                2)
            mkt_sprd  = best_ask - best_bid

            # Skip wide spread
            if mkt_sprd > MAX_MKT_SPREAD:
                print(
                    f"[SKIP] "
                    f"Spread={mkt_sprd:.4f}")
                time.sleep(ORDER_REFRESH)
                continue

            # Price history update
            add_price(mid)

            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            # STEP 2: VOLATILITY
            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            vol      = get_volatility()
            dyn_sprd, vol_label = (
                calc_dynamic_spread(vol))

            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            # STEP 3: INVENTORY SKEW
            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            skew = calc_skew(inventory)

            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            # STEP 4: LEVEL PRICES
            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            cap_use  = (
                capital * CAPITAL_USE / 100)
            total_qty = round(
                cap_use * LEVERAGE / mid, 4)
            total_qty = max(0.003, total_qty)

            new_bids, new_asks = (
                calc_level_prices(
                    mid, dyn_sprd,
                    skew, total_qty))

            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            # STEP 5: CHECK FILLS
            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            filled_bids = []
            filled_asks = []

            # Check bid fills
            for bo in bid_orders:
                oid = bo.get("id")
                if not oid:
                    continue
                status, qty_f, px_f = (
                    check_fill(ex, oid))

                if status == "filled":
                    filled_bids.append({
                        "price": px_f,
                        "qty":   qty_f,
                        "level": bo["level"],
                    })
                    buy_fills   += 1
                    trade_count += 1
                    inventory   += qty_f
                    total_volume += (
                        px_f * qty_f)

                    # Update avg price
                    if avg_price == 0:
                        avg_price = px_f
                    else:
                        # VWAP update
                        avg_price = (
                            (avg_price *
                             (inventory-qty_f)
                             + px_f * qty_f) /
                            inventory
                            if inventory > 0
                            else px_f)

                    print(
                        f"[BUY L{bo['level']}]"
                        f" {qty_f:.4f}@"
                        f"{px_f:.2f} | "
                        f"Inv={inventory:.4f}")

                    send_telegram(
                        f"✅ BUY FILL L"
                        f"{bo['level']}\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"Price    : {px_f:.4f}\n"
                        f"Qty      : "
                        f"{qty_f:.4f} ETH\n"
                        f"Fee      : 0% FREE\n"
                        f"Inventory: "
                        f"{inventory:.4f} ETH\n"
                        f"Avg Price: "
                        f"{avg_price:.4f}\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━"
                    )

                    save_trade(
                        "BUY_FILL",
                        px_f, qty_f,
                        0.0, capital,
                        trade_count,
                        f"L{bo['level']}"
                        f"|Inv={inventory:.4f}")

            # Check ask fills
            for ao in ask_orders:
                oid = ao.get("id")
                if not oid:
                    continue
                status, qty_f, px_f = (
                    check_fill(ex, oid))

                if status == "filled":
                    filled_asks.append({
                        "price": px_f,
                        "qty":   qty_f,
                        "level": ao["level"],
                    })
                    sell_fills  += 1
                    trade_count += 1
                    total_volume += (
                        px_f * qty_f)

                    # Profit calculate
                    if avg_price > 0:
                        profit = (
                            (px_f - avg_price)
                            * qty_f)
                    else:
                        profit = (
                            dyn_sprd *
                            qty_f)

                    # Update capital
                    gross_profit += profit
                    net_profit   += profit
                    capital      += profit

                    # Update inventory
                    inventory -= qty_f
                    if inventory <= 0:
                        inventory = 0.0
                        avg_price = 0.0

                    if profit > best_trade:
                        best_trade = profit

                    save_capital(capital)
                    save_trade(
                        "SELL_FILL",
                        px_f, qty_f,
                        profit, capital,
                        trade_count,
                        f"L{ao['level']}"
                        f"|P={profit:.4f}")

                    print(
                        f"[SELL L{ao['level']}]"
                        f" {qty_f:.4f}@"
                        f"{px_f:.2f} | "
                        f"P={profit:+.4f} | "
                        f"Net={net_profit:+.4f}")

                    send_telegram(
                        f"💰 SELL FILL L"
                        f"{ao['level']}\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"Price    : {px_f:.4f}\n"
                        f"Qty      : "
                        f"{qty_f:.4f} ETH\n"
                        f"Profit   : "
                        f"{profit:+.4f} USDT\n"
                        f"Fee      : 0% FREE ✅\n"
                        f"Inventory: "
                        f"{inventory:.4f} ETH\n"
                        f"Capital  : "
                        f"{capital:.4f} USDT\n"
                        f"Net Total: "
                        f"{net_profit:+.4f} USDT\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━"
                    )

            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            # STEP 6: INVENTORY MANAGEMENT
            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            inv_pnl = (
                (mid - avg_price) *
                inventory
                if avg_price > 0
                else 0.0)

            # Stop loss check
            if inv_pnl < INV_STOP_LOSS:
                print(
                    f"[STOP] "
                    f"InvPnL={inv_pnl:.4f}")

                # Cancel all
                cancel_all_orders(
                    ex,
                    bid_orders + ask_orders)
                bid_orders = []
                ask_orders = []

                # Hedge all inventory
                if inventory > 0:
                    hp, hf = hedge_market(
                        ex, "sell",
                        inventory)
                    if hp > 0:
                        hloss = (
                            inv_pnl - hf)
                        capital    += hloss
                        hedge_cost += hloss
                        net_profit += hloss
                        save_capital(capital)
                        save_trade(
                            "HEDGE", hp,
                            inventory,
                            hloss, capital,
                            trade_count,
                            "STOP_LOSS")

                        send_telegram(
                            f"🚨 STOP LOSS\n"
                            f"━━━━━━━━━━━━━━━━━━━━━━\n"
                            f"Inv PnL  : "
                            f"{inv_pnl:.4f}\n"
                            f"Hedged   : "
                            f"{inventory:.4f} ETH\n"
                            f"At Price : {hp:.4f}\n"
                            f"Loss     : "
                            f"{hloss:.4f} USDT\n"
                            f"Capital  : "
                            f"{capital:.4f} USDT\n"
                            f"━━━━━━━━━━━━━━━━━━━━━━"
                        )

                        inventory = 0.0
                        avg_price = 0.0

                time.sleep(1)
                continue

            # Partial hedge check
            if abs(inventory) >= HEDGE_INV:
                # Hedge half
                h_qty = round(
                    abs(inventory) / 2, 4)
                h_side = (
                    "sell"
                    if inventory > 0
                    else "buy")

                cancel_all_orders(
                    ex, bid_orders)
                bid_orders = []

                hp, hf = hedge_market(
                    ex, h_side, h_qty)
                if hp > 0:
                    if inventory > 0:
                        hprofit = (
                            (hp - avg_price) *
                            h_qty - hf)
                        inventory -= h_qty
                    else:
                        hprofit = (
                            (avg_price - hp) *
                            h_qty - hf)
                        inventory += h_qty

                    capital    += hprofit
                    hedge_cost += -hf
                    net_profit += hprofit
                    save_capital(capital)
                    save_trade(
                        "HEDGE", hp,
                        h_qty, hprofit,
                        capital, trade_count,
                        f"PARTIAL|"
                        f"Inv={inventory:.4f}")

                    send_telegram(
                        f"🔄 PARTIAL HEDGE\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"Side     : {h_side}\n"
                        f"Qty      : "
                        f"{h_qty:.4f} ETH\n"
                        f"Price    : {hp:.4f}\n"
                        f"Profit   : "
                        f"{hprofit:+.4f} USDT\n"
                        f"Inv Left : "
                        f"{inventory:.4f} ETH\n"
                        f"Capital  : "
                        f"{capital:.4f} USDT\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━"
                    )

            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            # STEP 7: CANCEL OLD ORDERS
            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            cancel_all_orders(
                ex, bid_orders + ask_orders)
            bid_orders = []
            ask_orders = []

            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            # STEP 8: PLACE NEW ORDERS
            # 3 Bid + 3 Ask = 6 orders
            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            placed_bids = 0
            placed_asks = 0

            # Place BID orders
            # Inventory limit check
            for bl in new_bids:
                if inventory >= MAX_INV:
                    break
                oid, px, qty = place_limit(
                    ex, "buy",
                    bl["price"],
                    bl["qty"])
                if oid:
                    bid_orders.append({
                        "id":    oid,
                        "price": px,
                        "qty":   qty,
                        "level": bl["level"],
                        "side":  "buy",
                    })
                    placed_bids += 1

            # Place ASK orders
            for al in new_asks:
                if inventory <= -MAX_INV:
                    break
                oid, px, qty = place_limit(
                    ex, "sell",
                    al["price"],
                    al["qty"])
                if oid:
                    ask_orders.append({
                        "id":    oid,
                        "price": px,
                        "qty":   qty,
                        "level": al["level"],
                        "side":  "sell",
                    })
                    placed_asks += 1

            active = placed_bids + placed_asks

            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            # STATE UPDATE
            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            uptime = int(
                (time.time() - start_time)
                / 60)

            update_state(
                mid=mid,
                best_bid=best_bid,
                best_ask=best_ask,
                mkt_spread=mkt_sprd,
                volatility=vol,
                dyn_spread=dyn_sprd,
                bid_orders=bid_orders,
                ask_orders=ask_orders,
                active_orders=active,
                inventory=inventory,
                avg_price=avg_price,
                inv_pnl=inv_pnl,
                skew=skew,
                capital=capital,
                trade_count=trade_count,
                buy_fills=buy_fills,
                sell_fills=sell_fills,
                gross_profit=gross_profit,
                hedge_cost=hedge_cost,
                net_profit=net_profit,
                best_trade=best_trade,
                total_volume=total_volume,
                status="RUNNING",
                cycles=cycles,
                uptime_min=uptime,
            )

            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            # PRINT STATUS
            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            if cycles % 20 == 0:
                print(
                    f"[C{cycles}] "
                    f"Mid={mid:.2f} | "
                    f"Sprd=±{dyn_sprd:.3f}({vol_label[:4]}) | "
                    f"Inv={inventory:.3f} | "
                    f"Skew={skew:+.3f} | "
                    f"Orders={active} | "
                    f"Net={net_profit:+.4f} | "
                    f"BF={buy_fills} "
                    f"SF={sell_fills}")

            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            # SPEED
            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            elapsed = time.time() - loop_start
            sleep_t = max(
                0, ORDER_REFRESH - elapsed)
            if sleep_t > 0:
                time.sleep(sleep_t)

        except Exception as e:
            err = str(e)
            print(f"[ERR] {err}")

            if "429" in err:
                print("[429] Rate limit 10s")
                time.sleep(10)

            elif ("postOnly" in err or
                  "maker" in err.lower()):
                bid_orders = []
                ask_orders = []
                time.sleep(0.1)

            elif ("connection" in
                  err.lower() or
                  "timeout" in
                  err.lower()):
                print("[RECONNECT]...")
                try:
                    cancel_all_orders(
                        ex,
                        bid_orders + ask_orders)
                except Exception:
                    pass
                bid_orders = []
                ask_orders = []
                ex = get_exchange()
                time.sleep(5)

            else:
                time.sleep(0.5)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  START
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

if __name__ == "__main__":

    cap_use  = CAPITAL * CAPITAL_USE / 100
    exp      = cap_use * LEVERAGE
    cyc_day  = int(86400 / ORDER_REFRESH)
    fills_est = int(cyc_day * 0.4)
    profit_lo = round(
        fills_est * MIN_HALF_SPREAD * 2, 2)
    profit_hi = round(
        fills_est * MAX_HALF_SPREAD * 2, 2)

    print("=" * 60)
    print("  ETH MARKET MAKING HFT BOT v6.0")
    print("  MEXC FUTURES")
    print("=" * 60)
    print(f"  Capital     : {CAPITAL:,.2f} USDT")
    print(f"  Use (80%)   : {cap_use:,.2f} USDT")
    print(f"  Leverage    : {LEVERAGE}x")
    print(f"  Exposure    : {exp:,.2f} USDT")
    print("-" * 60)
    print(f"  DYNAMIC SPREAD:")
    print(f"  Min Spread  : ±{MIN_HALF_SPREAD}")
    print(f"  Base Spread : ±{BASE_HALF_SPREAD}")
    print(f"  Max Spread  : ±{MAX_HALF_SPREAD}")
    print("-" * 60)
    print(f"  MULTI LEVELS: {LEVELS} each side")
    print(f"  L1          : ±{BASE_HALF_SPREAD} "
          f"(50% qty)")
    print(f"  L2          : ±{BASE_HALF_SPREAD*2} "
          f"(30% qty)")
    print(f"  L3          : ±{BASE_HALF_SPREAD*3} "
          f"(20% qty)")
    print("-" * 60)
    print(f"  INVENTORY:")
    print(f"  Max Inv     : {MAX_INV} ETH")
    print(f"  Hedge At    : {HEDGE_INV} ETH")
    print(f"  Stop Loss   : {INV_STOP_LOSS} USDT")
    print(f"  Skew Factor : {SKEW_FACTOR}")
    print("-" * 60)
    print(f"  Refresh     : {ORDER_REFRESH}s")
    print(f"  Cycles/Day  : {cyc_day:,}")
    print(f"  Fills Est   : {fills_est:,}/day")
    print(f"  Profit Est  : "
          f"+{profit_lo:.0f} to "
          f"+{profit_hi:.0f} USDT/day")
    print(f"  Maker Fee   : 0.00% FREE!")
    print("=" * 60)

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
            target=run_engine,
            name="Engine",
            daemon=True),
    ]

    for t in threads:
        t.start()
        print(f"[START] {t.name} ✅")
        time.sleep(0.2)

    print("=" * 60)
    print(
        f"[INFO] {len(threads)} "
        f"threads running!")
    print("[INFO] Bot Live 24/7 ✅")
    print("=" * 60)

    while True:
        time.sleep(60)
