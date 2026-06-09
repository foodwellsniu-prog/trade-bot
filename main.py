"""
ETH High Frequency Scalping Bot v4.0
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Strategy : Order Book + Trade Flow
           + Price Velocity
           Next few seconds predict karo
           Us side LIMIT entry lo
           Maker rebate kamao
Symbol   : ETH/USDT
Capital  : 1052 USDT
Leverage : 5x
TP       : Limit Order (Maker Rebate)
SL       : Bot Monitor → Market Order
Max Hold : 10 seconds

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FEE STRUCTURE (Binance Futures)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Maker (Limit) : -0.02% (exchange deta hai)
Taker (Market): +0.05% (tum dete ho)

Entry  = Limit Order → Maker Rebate MILEGA
TP     = Limit Order → Maker Rebate MILEGA
SL     = Market Order → Fee lagegi (safety)

Net Fee per winning trade = +rebate +rebate
Net Fee per losing trade  = +rebate -fee
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

app = Flask(_name_)

@app.route('/')
def home():
    return "ETH HF Scalping Bot v4.0 Running! Maker Order Edition"

def run_server():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  CONFIG
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SYMBOL     = "ETH/USDT:USDT"

# ── API Keys (Environment Variables se lo) ─
# Render par Environment Variables mein set karo:
# BINANCE_API_KEY    = tumhari testnet api key
# BINANCE_API_SECRET = tumhara testnet api secret
API_KEY    = os.environ.get("H647cSQelN9Im9o22wTu3h3oz3ZTBgxSzV5McQzN7qJoWg94lPGmR6JaCawbmS5S")
API_SECRET = os.environ.get("O2Gz79sooHsYAzd2oyJQ2rmE8KwhhF5JCs9KlwHwFToTitszOaLMRDFYCobz6gSW")

# ── Telegram (Environment Variables se lo) ─
# Render par set karo:
# TELEGRAM_BOT_TOKEN = naya token BotFather se
# TELEGRAM_CHAT_ID   = tumhara chat id
BOT_TOKEN  = os.environ.get("8161773850:AAFcWw3UnlSe2TrMooB2uvgZQZUqIW0zW2w")
CHAT_ID    = os.environ.get("7102976298")

# ── Testnet Toggle ────────────────────────
# True  = Binance Testnet (safe testing)
# False = Live Binance (real money)
USE_TESTNET = True

# ── Capital ───────────────────────────────
CAPITAL     = 1052.0
CAPITAL_USE = 90      # 90% capital use karo
LEVERAGE    = 5

# ── Trade Config ──────────────────────────
TP_PCT   = 0.05   # 0.05% target
SL_PCT   = 0.03   # 0.03% stop loss
MAX_HOLD = 10     # 10 seconds max

# ── Limit Order Config ────────────────────
# Entry ke liye price kitna better rakho
# BUY  entry: current_price - ENTRY_OFFSET  (thoda neeche)
# SELL entry: current_price + ENTRY_OFFSET  (thoda upar)
ENTRY_OFFSET_PCT = 0.003   # 0.003% = ~0.05 cents on $1600

# TP limit order ka offset
# BUY  TP: tp_price - TP_LIMIT_OFFSET  (thoda neeche se pakdo)
# SELL TP: tp_price + TP_LIMIT_OFFSET  (thoda upar se pakdo)
TP_LIMIT_OFFSET_PCT = 0.002  # 0.002%

# ── Maker Fee Rate ────────────────────────
MAKER_REBATE_RATE = 0.0002   # 0.02% rebate milta hai
TAKER_FEE_RATE    = 0.0005   # 0.05% fee lagti hai

# ── Speed ─────────────────────────────────
SCAN_INTERVAL        = 1   # Har 1 second scan
ORDER_CHECK_INTERVAL = 0.5 # Har 0.5 sec order check

# ── Cooldown ──────────────────────────────
COOLDOWN_WIN   = 2    # Win ke baad 2s
COOLDOWN_LOSS  = 5    # Loss ke baad 5s
COOLDOWN_2LOSS = 10   # 2 loss ke baad 10s

# ── Spread ────────────────────────────────
MAX_SPREAD = 0.05

# ── Order Book Config ─────────────────────
OB_LEVELS    = 10   # Top 10 levels
OB_IMBALANCE = 1.5  # 1.5x imbalance

# ── Periodic Update ───────────────────────
UPDATE_INTERVAL = 1800


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  FILES
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

FILES = {
    "capital":  "capital_eth.txt",
    "cooldown": "cooldown_eth.txt",
    "history":  "history_eth.json",
}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  STATE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

state_lock = threading.Lock()

state = {
    # Position
    "position":        None,
    "entry_price":     0.0,
    "entry_time":      None,
    "sl_price":        0.0,
    "tp_price":        0.0,
    "pos_size":        0.0,
    "capital_used":    0.0,
    "capital":         CAPITAL,

    # Order IDs
    "entry_order_id":  None,
    "tp_order_id":     None,
    "entry_filled":    False,
    "tp_placed":       False,

    # Market
    "last_price":      0.0,
    "last_signal":     "WAIT",
    "ob_signal":       "FLAT",
    "flow_signal":     "FLAT",
    "velocity":        0.0,

    # Fee tracking
    "total_rebate":    0.0,
    "total_fee_paid":  0.0,
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
                print(f"[COOLDOWN] {int(val - time.time())}s")
                return val
    except Exception:
        pass
    return None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  FEE CALCULATOR
#  Maker rebate ya taker fee calculate karo
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def calc_maker_rebate(exposure):
    """
    Limit order fill hone par exchange
    tumhe yeh rebate deta hai
    Positive = tumhe milta hai
    """
    return exposure * MAKER_REBATE_RATE

def calc_taker_fee(exposure):
    """
    Market order par yeh fee lagti hai
    Negative = tum dete ho
    """
    return exposure * TAKER_FEE_RATE

def calc_net_fee_winning_trade(exposure):
    """
    Winning trade mein:
    Entry  = Limit (rebate milega)
    TP     = Limit (rebate milega)
    Total  = +rebate +rebate
    """
    entry_rebate = calc_maker_rebate(exposure)
    tp_rebate    = calc_maker_rebate(exposure)
    net          = entry_rebate + tp_rebate
    return net  # Positive = profit

def calc_net_fee_losing_trade(exposure):
    """
    Losing trade mein:
    Entry  = Limit (rebate milega)
    SL     = Market (fee lagegi)
    Total  = +rebate -fee
    """
    entry_rebate = calc_maker_rebate(exposure)
    sl_fee       = calc_taker_fee(exposure)
    net          = entry_rebate - sl_fee
    return net  # Negative = cost


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  TRADE HISTORY
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def save_trade(side, entry, exit_p,
               pnl, fee, capital, duration, label):
    try:
        try:
            with open(FILES["history"], "r",
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
            "fee":      round(fee, 4),
            "net_pnl":  round(pnl + fee, 4),
            "capital":  round(capital, 4),
            "duration": duration,
            "result":   "WIN" if (pnl + fee) > 0 else "LOSS",
            "label":    label,
        })

        with open(FILES["history"], "w",
                  encoding="utf-8") as f:
            json.dump(history, f, indent=2)

    except Exception as e:
        print(f"[HISTORY ERROR] {e}")


def get_daily_stats():
    try:
        with open(FILES["history"], "r",
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
    total_fee = round(sum(t.get("fee", 0) for t in trades), 4)
    net_pnl  = round(sum(t.get("net_pnl", t["pnl"]) for t in trades), 4)

    return {
        "total":     total,
        "wins":      wins,
        "losses":    losses,
        "win_rate":  win_rate,
        "pnl":       pnl,
        "total_fee": total_fee,
        "net_pnl":   net_pnl,
        "best":      round(max(t["pnl"] for t in trades), 4),
        "worst":     round(min(t["pnl"] for t in trades), 4),
        "capital":   trades[-1]["capital"],
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  EXCHANGE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def get_exchange():
    while True:
        try:
            if USE_TESTNET:
                # ── Testnet ──────────────────
                ex = ccxt.binanceusdm({
                    "apiKey":          API_KEY,
                    "secret":          API_SECRET,
                    "enableRateLimit": True,
                    "rateLimit":       50,
                    "urls": {
                        "api": {
                            "public":  "https://testnet.binancefuture.com",
                            "private": "https://testnet.binancefuture.com",
                        }
                    }
                })
                print("[INFO] Binance TESTNET connected ✅")
            else:
                # ── Live ─────────────────────
                ex = ccxt.binanceusdm({
                    "apiKey":          API_KEY,
                    "secret":          API_SECRET,
                    "enableRateLimit": True,
                    "rateLimit":       50,
                })
                print("[INFO] Binance LIVE connected ✅")

            ex.load_markets()
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


def safe_fetch_orderbook(ex, limit=10):
    for i in range(3):
        try:
            ob = ex.fetch_order_book(SYMBOL, limit=limit)
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
            trades = ex.fetch_trades(SYMBOL, limit=limit)
            return trades
        except Exception as e:
            if "429" in str(e):
                time.sleep((i+1) * 10)
            else:
                time.sleep(2)
    return None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  LIMIT ORDER FUNCTIONS
#  Entry aur TP ke liye maker orders
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def place_limit_entry(ex, side, cur_price, pos_size):
    """
    Limit entry order lagao

    BUY  side: thoda neeche se entry lo
               cur_price - offset
               (market neeche aane par fill)

    SELL side: thoda upar se entry lo
               cur_price + offset
               (market upar jaane par fill)

    Yeh Maker order hai = Rebate milega
    """
    try:
        offset = cur_price * ENTRY_OFFSET_PCT / 100

        if side == "BUY":
            limit_price = round(cur_price - offset, 2)
            order = ex.create_limit_buy_order(
                SYMBOL,
                pos_size,
                limit_price,
                params={"timeInForce": "GTC"}
            )
        else:  # SELL
            limit_price = round(cur_price + offset, 2)
            order = ex.create_limit_sell_order(
                SYMBOL,
                pos_size,
                limit_price,
                params={"timeInForce": "GTC"}
            )

        print(
            f"[LIMIT ENTRY] {side} | "
            f"Market={cur_price:.4f} | "
            f"Limit={limit_price:.4f} | "
            f"Size={pos_size:.4f} | "
            f"OrderID={order['id']}")

        return order['id'], limit_price

    except Exception as e:
        print(f"[LIMIT ENTRY ERROR] {e}")
        return None, None


def place_limit_tp(ex, side, tp_price, pos_size):
    """
    Limit TP order lagao

    BUY  side: sell karna hai TP par
               tp_price + offset (thoda upar)
               (better price milegi)

    SELL side: buy karna hai TP par
               tp_price - offset (thoda neeche)
               (better price milegi)

    Yeh bhi Maker order = Rebate milega
    """
    try:
        offset = tp_price * TP_LIMIT_OFFSET_PCT / 100

        if side == "BUY":
            # Position close karna hai SELL se
            limit_price = round(tp_price + offset, 2)
            order = ex.create_limit_sell_order(
                SYMBOL,
                pos_size,
                limit_price,
                params={
                    "timeInForce":  "GTC",
                    "reduceOnly":   True,
                }
            )
        else:  # SELL position close karna hai BUY se
            limit_price = round(tp_price - offset, 2)
            order = ex.create_limit_buy_order(
                SYMBOL,
                pos_size,
                limit_price,
                params={
                    "timeInForce":  "GTC",
                    "reduceOnly":   True,
                }
            )

        print(
            f"[LIMIT TP] {side} close | "
            f"TP price={tp_price:.4f} | "
            f"Limit={limit_price:.4f} | "
            f"OrderID={order['id']}")

        return order['id'], limit_price

    except Exception as e:
        print(f"[LIMIT TP ERROR] {e}")
        return None, None


def place_market_exit(ex, side, pos_size, reason):
    """
    Market order se exit karo (SL ya emergency)

    Yeh Taker order hai = Fee lagegi
    Lekin SAFETY ke liye zaroori hai

    SL par limit order KABHI MAT LAGAO!
    Market gap hone par fill nahi hoga
    Aur loss bahut bada ho sakta hai
    """
    try:
        if side == "BUY":
            # BUY position close = SELL
            order = ex.create_market_sell_order(
                SYMBOL,
                pos_size,
                params={"reduceOnly": True}
            )
        else:
            # SELL position close = BUY
            order = ex.create_market_buy_order(
                SYMBOL,
                pos_size,
                params={"reduceOnly": True}
            )

        filled_price = float(
            order.get('average', 0) or
            order.get('price', 0))

        print(
            f"[MARKET EXIT] {reason} | "
            f"Side={side} | "
            f"Price={filled_price:.4f} | "
            f"OrderID={order['id']}")

        return order['id'], filled_price

    except Exception as e:
        print(f"[MARKET EXIT ERROR] {e}")
        return None, None


def cancel_order(ex, order_id):
    """Pending order cancel karo"""
    try:
        if order_id:
            ex.cancel_order(order_id, SYMBOL)
            print(f"[CANCEL] Order {order_id} cancelled")
    except Exception as e:
        print(f"[CANCEL ERROR] {e}")


def check_order_filled(ex, order_id):
    """
    Order fill hua ya nahi check karo
    Returns: (filled, avg_price)
    """
    try:
        order = ex.fetch_order(order_id, SYMBOL)
        status = order.get('status', '')

        if status == 'closed':
            avg_price = float(
                order.get('average', 0) or
                order.get('price', 0))
            return True, avg_price

        return False, 0.0

    except Exception as e:
        print(f"[ORDER CHECK ERROR] {e}")
        return False, 0.0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  TELEGRAM
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def send_telegram(message):
    if not BOT_TOKEN or not CHAT_ID:
        print(f"[TELEGRAM SKIP] Token/ChatID missing")
        return

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    for attempt in range(3):
        try:
            r = requests.post(
                url,
                data={
                    "chat_id": CHAT_ID,
                    "text":    f"[v4.0] {message}",
                },
                timeout=15)
            if r.status_code == 200:
                return
        except Exception as e:
            print(f"[TELEGRAM] {attempt+1}/3: {e}")
            time.sleep(3)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  PnL CALCULATOR
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def calc_pnl(side, entry, exit_p, pos_size):
    if side == "BUY":
        return (exit_p - entry) * pos_size
    else:
        return (entry - exit_p) * pos_size


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  ORDER BOOK ANALYSIS
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

        spread = ((best_ask - best_bid) / best_bid) * 100

        if spread > MAX_SPREAD:
            print(f"[OB] Spread HIGH {spread:.4f}% ❌")
            return "FLAT", 0.0, spread, 0.0

        bid_vol = sum(float(b[1]) for b in bids[:10])
        ask_vol = sum(float(a[1]) for a in asks[:10])

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
        trades = safe_fetch_trades(ex, limit=50)
        if not trades:
            return "FLAT", 0.0, 0.0

        buy_vol  = 0.0
        sell_vol = 0.0

        for t in trades:
            side = t.get("side", "")
            amt  = float(t.get("amount", 0))
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
