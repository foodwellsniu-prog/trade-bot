"""

import ccxt
import requests
import threading
import time
import json
import os
from flask import Flask
from datetime import datetime, timezone, timedelta

app = Flask(_name_)

@app.route("/")
def home():
    return "ETH HF Scalping Bot v4.0 Running!"

def run_server():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  CONFIG
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SYMBOL = "ETH/USDT:USDT"

API_KEY    = os.environ.get("BINANCE_API_KEY", "H647cSQelN9Im9o22wTu3h3oz3ZTBgxSzV5McQzN7qJoWg94lPGmR6JaCawbmS5S")
API_SECRET = os.environ.get("BINANCE_API_SECRET", "O2Gz79sooHsYAzd2oyJQ2rmE8KwhhF5JCs9KlwHwFToTitszOaLMRDFYCobz6gSW")
BOT_TOKEN  = os.environ.get("TELEGRAM_BOT_TOKEN", "8161773850:AAFcWw3UnlSe2TrMooB2uvgZQZUqIW0zW2w")
CHAT_ID    = os.environ.get("TELEGRAM_CHAT_ID", "7102976298")

USE_TESTNET = True

CAPITAL     = 1052.0
CAPITAL_USE = 90
LEVERAGE    = 5

TP_PCT   = 0.05
SL_PCT   = 0.03
MAX_HOLD = 10

ENTRY_OFFSET_PCT    = 0.003
TP_LIMIT_OFFSET_PCT = 0.002

MAKER_REBATE_RATE = 0.0002
TAKER_FEE_RATE    = 0.0005

SCAN_INTERVAL        = 1
ORDER_CHECK_INTERVAL = 0.5

COOLDOWN_WIN   = 2
COOLDOWN_LOSS  = 5
COOLDOWN_2LOSS = 10

MAX_SPREAD   = 0.05
OB_LEVELS    = 10
OB_IMBALANCE = 1.5

UPDATE_INTERVAL = 1800

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
    "position":       None,
    "entry_price":    0.0,
    "entry_time":     None,
    "sl_price":       0.0,
    "tp_price":       0.0,
    "pos_size":       0.0,
    "capital_used":   0.0,
    "capital":        CAPITAL,
    "entry_order_id": None,
    "tp_order_id":    None,
    "entry_filled":   False,
    "tp_placed":      False,
    "last_price":     0.0,
    "last_signal":    "WAIT",
    "ob_signal":      "FLAT",
    "flow_signal":    "FLAT",
    "velocity":       0.0,
    "total_rebate":   0.0,
    "total_fee_paid": 0.0,
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
            print("[CAPITAL] Loaded: " + str(cap) + " USDT")
            return cap
    except Exception:
        save_capital(CAPITAL)
        return CAPITAL

def save_capital(capital):
    try:
        with open(FILES["capital"], "w") as f:
            f.write(str(round(capital, 6)))
    except Exception as e:
        print("[CAPITAL ERROR] " + str(e))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  COOLDOWN
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def save_cooldown(end_time):
    try:
        with open(FILES["cooldown"], "w") as f:
            f.write(str(end_time))
    except Exception as e:
        print("[COOLDOWN ERROR] " + str(e))

def load_cooldown():
    try:
        with open(FILES["cooldown"], "r") as f:
            val = float(f.read().strip())
            if val > time.time():
                print("[COOLDOWN] " + str(int(val - time.time())) + "s")
                return val
    except Exception:
        pass
    return None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  FEE CALCULATOR
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def calc_maker_rebate(exposure):
    return exposure * MAKER_REBATE_RATE

def calc_taker_fee(exposure):
    return exposure * TAKER_FEE_RATE

def calc_net_fee_winning_trade(exposure):
    return calc_maker_rebate(exposure) + calc_maker_rebate(exposure)

def calc_net_fee_losing_trade(exposure):
    return calc_maker_rebate(exposure) - calc_taker_fee(exposure)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  TRADE HISTORY
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def save_trade(side, entry, exit_p, pnl, fee, capital, duration, label):
    try:
        try:
            with open(FILES["history"], "r", encoding="utf-8") as f:
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

        with open(FILES["history"], "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2)

    except Exception as e:
        print("[HISTORY ERROR] " + str(e))


def get_daily_stats():
    try:
        with open(FILES["history"], "r", encoding="utf-8") as f:
            history = json.load(f)
    except Exception:
        return None

    today  = datetime.now().strftime("%d/%m/%Y")
    trades = [t for t in history if t["date"] == today]

    if not trades:
        return None

    total     = len(trades)
    wins      = len([t for t in trades if t["result"] == "WIN"])
    losses    = total - wins
    win_rate  = round((wins / total) * 100, 1)
    pnl       = round(sum(t["pnl"] for t in trades), 4)
    total_fee = round(sum(t.get("fee", 0) for t in trades), 4)
    net_pnl   = round(sum(t.get("net_pnl", t["pnl"]) for t in trades), 4)

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
                    },
                })
                print("[INFO] Binance TESTNET connected")
            else:
                ex = ccxt.binanceusdm({
                    "apiKey":          API_KEY,
                    "secret":          API_SECRET,
                    "enableRateLimit": True,
                    "rateLimit":       50,
                })
                print("[INFO] Binance LIVE connected")

            ex.load_markets()
            return ex

        except Exception as e:
            print("[RECONNECT] " + str(e) + " — 30s...")
            time.sleep(30)


def safe_fetch_ticker(ex):
    for i in range(3):
        try:
            t = ex.fetch_ticker(SYMBOL)
            return float(t["last"])
        except Exception as e:
            if "429" in str(e):
                time.sleep((i + 1) * 10)
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
                time.sleep((i + 1) * 10)
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
                time.sleep((i + 1) * 10)
            else:
                time.sleep(2)
    return None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  LIMIT ORDER FUNCTIONS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def place_limit_entry(ex, side, cur_price, pos_size):
    try:
        offset = cur_price * ENTRY_OFFSET_PCT / 100

        if side == "BUY":
            limit_price = round(cur_price - offset, 2)
            order = ex.create_limit_buy_order(
                SYMBOL,
                pos_size,
                limit_price,
                {"timeInForce": "GTC"},
            )
        else:
            limit_price = round(cur_price + offset, 2)
            order = ex.create_limit_sell_order(
                SYMBOL,
                pos_size,
                limit_price,
                {"timeInForce": "GTC"},
            )

        print(
            "[LIMIT ENTRY] " + side +
            " | Market=" + str(cur_price) +
            " | Limit=" + str(limit_price) +
            " | OrderID=" + str(order["id"])
        )
        return order["id"], limit_price

    except Exception as e:
        print("[LIMIT ENTRY ERROR] " + str(e))
        return None, None


def place_limit_tp(ex, side, tp_price, pos_size):
    try:
        offset = tp_price * TP_LIMIT_OFFSET_PCT / 100

        if side == "BUY":
            limit_price = round(tp_price + offset, 2)
            order = ex.create_limit_sell_order(
                SYMBOL,
                pos_size,
                limit_price,
                {"timeInForce": "GTC", "reduceOnly": True},
            )
        else:
            limit_price = round(tp_price - offset, 2)
            order = ex.create_limit_buy_order(
                SYMBOL,
                pos_size,
                limit_price,
                {"timeInForce": "GTC", "reduceOnly": True},
            )

        print(
            "[LIMIT TP] " + side +
            " | TP=" + str(tp_price) +
            " | Limit=" + str(limit_price) +
            " | OrderID=" + str(order["id"])
        )
        return order["id"], limit_price

    except Exception as e:
        print("[LIMIT TP ERROR] " + str(e))
        return None, None


def place_market_exit(ex, side, pos_size, reason):
    try:
        if side == "BUY":
            order = ex.create_market_sell_order(
                SYMBOL,
                pos_size,
                {"reduceOnly": True},
            )
        else:
            order = ex.create_market_buy_order(
                SYMBOL,
                pos_size,
                {"reduceOnly": True},
            )

        filled_price = float(
            order.get("average", 0) or
            order.get("price", 0)
        )

        print(
            "[MARKET EXIT] " + reason +
            " | Side=" + side +
            " | Price=" + str(filled_price)
        )
        return order["id"], filled_price

    except Exception as e:
        print("[MARKET EXIT ERROR] " + str(e))
        return None, None


def cancel_order(ex, order_id):
    try:
        if order_id:
            ex.cancel_order(order_id, SYMBOL)
            print("[CANCEL] Order " + str(order_id) + " cancelled")
    except Exception as e:
        print("[CANCEL ERROR] " + str(e))


def check_order_filled(ex, order_id):
    try:
        order  = ex.fetch_order(order_id, SYMBOL)
        status = order.get("status", "")
        if status == "closed":
            avg_price = float(
                order.get("average", 0) or
                order.get("price", 0)
            )
            return True, avg_price
        return False, 0.0
    except Exception as e:
        print("[ORDER CHECK ERROR] " + str(e))
        return False, 0.0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  TELEGRAM
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def send_telegram(message):
    if not BOT_TOKEN or not CHAT_ID:
        print("[TELEGRAM SKIP] Token/ChatID missing")
        return

    url = "https://api.telegram.org/bot" + BOT_TOKEN + "/sendMessage"
    for attempt in range(3):
        try:
            r = requests.post(
                url,
                data={"chat_id": CHAT_ID, "text": "[v4.0] " + message},
                timeout=15,
            )
            if r.status_code == 200:
                return
        except Exception as e:
            print("[TELEGRAM] " + str(attempt + 1) + "/3: " + str(e))
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
        spread   = ((best_ask - best_bid) / best_bid) * 100

        if spread > MAX_SPREAD:
            print("[OB] Spread HIGH " + str(round(spread, 4)) + "%")
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
            "[OB] " + signal +
            " | BidVol=" + str(round(bid_vol, 2)) +
            " | AskVol=" + str(round(ask_vol, 2)) +
            " | Ratio=" + str(round(ratio, 2)) +
            " | Spread=" + str(round(spread, 4)) + "%"
        )
        return signal, mid_price, spread, ratio

    except Exception as e:
        print("[OB ERROR] " + str(e))
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
            "[FLOW] " + signal +
            " | Buy=" + str(round(buy_vol, 2)) +
            " | Sell=" + str(round(sell_vol, 2)) +
            " | Ratio=" + str(round(ratio, 2))
        )
        return signal, buy_vol, sell_vol

    except Exception as e:
        print("[FLOW ERROR] " + str(e))
        return "FLAT", 0.0, 0.0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  PRICE VELOCITY
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

price_history = []
price_lock    = threading.Lock()

def update_price_history(price):
    with price_lock:
        price_history.append({"price": price, "time": time.time()})
        cutoff = time.time() - 30
        while price_history and price_history[0]["time"] < cutoff:
            price_history.pop(0)

def analyze_velocity():
    try:
        with price_lock:
            if len(price_history) < 3:
                return "FLAT", 0.0

            recent = price_history[-10:]
            if len(recent) < 2:
                return "FLAT", 0.0

            first     = recent[0]["price"]
            last      = recent[-1]["price"]
            t1        = recent[0]["time"]
            t2        = recent[-1]["time"]

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
                "[VEL] " + signal +
                " | Change=" + str(round(pct, 4)) + "%" +
                " | Vel=" + str(round(velocity, 4)) + "/s"
            )
            return signal, pct

    except Exception as e:
        print("[VEL ERROR] " + str(e))
        return "FLAT", 0.0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  COMBINED SIGNAL
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def get_combined_signal(ob_signal, flow_signal, vel_signal):
    signals    = [ob_signal, flow_signal, vel_signal]
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
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

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
            rebate   = st["total_rebate"]
            fee_paid = st["total_fee_paid"]
            daily    = get_daily_stats()

            if pos is not None and etime is not None and price > 0:
                pnl_now = calc_pnl(pos, entry, price, psize)
                dur     = str(datetime.now() - etime).split(".")[0]
                icon    = "🟢" if pnl_now >= 0 else "🔴"
                msg = (
                    "━━━━━━━━━━━━━━━━━━━━━━\n"
                    "  ETH BOT v4.0 UPDATE\n"
                    "  " + now + "\n"
                    "━━━━━━━━━━━━━━━━━━━━━━\n"
                    + icon + " " + pos + "\n"
                    "Entry  : " + str(round(entry, 4)) + "\n"
                    "Price  : " + str(round(price, 4)) + "\n"
                    "PnL    : " + str(round(pnl_now, 4)) + " USDT\n"
                    "OB     : " + ob_sig + "\n"
                    "Flow   : " + fl_sig + "\n"
                    "Capital: " + str(round(capital, 4)) + " USDT\n"
                    "Rebate : +" + str(round(rebate, 4)) + " USDT\n"
                    "Fee    : -" + str(round(fee_paid, 4)) + " USDT\n"
                )
            else:
                msg = (
                    "━━━━━━━━━━━━━━━━━━━━━━\n"
                    "  ETH BOT v4.0 UPDATE\n"
                    "  " + now + "\n"
                    "━━━━━━━━━━━━━━━━━━━━━━\n"
                    "⏳ WAITING\n"
                    "Price  : " + str(round(price, 4)) + "\n"
                    "OB     : " + ob_sig + "\n"
                    "Flow   : " + fl_sig + "\n"
                    "Capital: " + str(round(capital, 4)) + " USDT\n"
                    "Rebate : +" + str(round(rebate, 4)) + " USDT\n"
                    "Fee    : -" + str(round(fee_paid,
