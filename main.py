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
    return "ETH HF Scalping Bot v3.1 (Capital: 10k | Fees Added | Optimized) Running!"

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

# ── Capital & Fees ───────────────────────
CAPITAL      = 10000.0          # ✅ 10k USDT as requested
CAPITAL_USE  = 90               # 90% capital use per trade
LEVERAGE     = 5
MXC_FEE_PCT  = 0.05             # MXC taker fee per side (0.05%)
TOTAL_FEE_PCT= MXC_FEE_PCT * 2  # Entry + Exit fees

# ── Trade Config ─────────────────────────
TP_PCT   = 0.05    # 0.05% target
SL_PCT   = 0.03    # 0.03% stop loss
MAX_HOLD = 10      # 10 seconds max

# ── Speed ─────────────────────────────────
SCAN_INTERVAL = 0.1  # ⚠️ 0.1s = 10x/sec. <0.05s will trigger rate limits

# ── Cooldown ──────────────────────────────
COOLDOWN_WIN   = 0.5   # Win ke baad 0.5s
COOLDOWN_LOSS  = 1.0   # Loss ke baad 1s
COOLDOWN_2LOSS = 2.0   # 2 loss ke baad 2s

# ── Spread ────────────────────────────────
MAX_SPREAD = 0.05

# ── Order Book Config ─────────────────────
OB_LEVELS      = 10
OB_IMBALANCE   = 1.5

# ── Update ────────────────────────────────
UPDATE_INTERVAL = 1800

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  FILES & STATE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FILES = {"capital": "capital_eth.txt", "cooldown": "cooldown_eth.txt", 
         "history": "history_eth.json", "log": "log_eth.json"}

state_lock = threading.Lock()
state = {"position": None, "entry_price": 0.0, "entry_time": None, "sl_price": 0.0,
         "tp_price": 0.0, "pos_size": 0.0, "capital_used": 0.0, "capital": CAPITAL,
         "last_price": 0.0, "last_signal": "WAIT", "ob_signal": "FLAT", 
         "flow_signal": "FLAT", "velocity": 0.0}

def update_state(**kwargs):
    with state_lock:
        for k, v in kwargs.items():
            if k in state: state[k] = v

def get_state(key):
    with state_lock: return state.get(key)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  CAPITAL & COOLDOWN HANDLERS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def load_capital():
    try:
        with open(FILES["capital"], "r") as f: return float(f.read().strip())
    except: 
        save_capital(CAPITAL)
        return CAPITAL

def save_capital(capital):
    try:
        with open(FILES["capital"], "w") as f: f.write(str(round(capital, 6)))
    except Exception as e: print(f"[CAPITAL ERROR] {e}")

def save_cooldown(end_time):
    try:
        with open(FILES["cooldown"], "w") as f: f.write(str(end_time))
    except Exception as e: print(f"[COOLDOWN ERROR] {e}")

def load_cooldown():
    try:
        with open(FILES["cooldown"], "r") as f:
            val = float(f.read().strip())
            return val if val > time.time() else None
    except: return None

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  TRADE HISTORY & STATS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def save_trade(side, entry, exit_p, pnl, capital, duration, label, fee_deducted):
    try:
        with open(FILES["history"], "r", encoding="utf-8") as f: history = json.load(f)
    except: history = []
    history.append({"date": datetime.now().strftime("%d/%m/%Y"), "time": datetime.now().strftime("%H:%M:%S"),
                    "symbol": "ETH", "side": side, "entry": round(entry, 4), "exit": round(exit_p, 4),
                    "pnl": round(pnl, 4), "capital": round(capital, 4), "duration": duration,
                    "result": "WIN" if pnl > 0 else "LOSS", "label": label, "fee_deducted": round(fee_deducted, 4)})
    with open(FILES["history"], "w", encoding="utf-8") as f: json.dump(history, f, indent=2)
    except Exception as e: print(f"[HISTORY ERROR] {e}")

def get_daily_stats():
    try:
        with open(FILES["history"], "r", encoding="utf-8") as f: history = json.load(f)
    except: return None
    today = datetime.now().strftime("%d/%m/%Y")
    trades = [t for t in history if t["date"] == today]
    if not trades: return None
    wins = len([t for t in trades if t["result"] == "WIN"])
    total = len(trades)
    return {"total": total, "wins": wins, "losses": total - wins, "win_rate": round((wins/total)*100, 1),
            "pnl": round(sum(t["pnl"] for t in trades), 4), "best": round(max(t["pnl"] for t in trades), 4),
            "worst": round(min(t["pnl"] for t in trades), 4), "capital": trades[-1]["capital"]}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  EXCHANGE & RATE LIMIT SAFE FETCH
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def get_exchange():
    while True:
        try:
            ex = ccxt.binanceusdm({"apiKey": API_KEY, "secret": API_SECRET, "enableRateLimit": True, "rateLimit": 50})
            ex.load_markets()
            print("[INFO] Exchange connected ✅")
            return ex
        except Exception as e:
            print(f"[RECONNECT] {e} — 30s...")
            time.sleep(30)

def safe_fetch_ticker(ex):
    try: return float(ex.fetch_ticker(SYMBOL)["last"])
    except: return None

def safe_fetch_orderbook(ex, limit=10):
    for i in range(2):
        try: return ex.fetch_order_book(SYMBOL, limit=limit)
        except: time.sleep(0.2)
    return None

def safe_fetch_trades(ex, limit=50):
    for i in range(2):
        try: return ex.fetch_trades(SYMBOL, limit=limit)
        except: time.sleep(0.2)
    return None

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  TELEGRAM
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def send_telegram(message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": CHAT_ID, "text": f"[SCALP] {message}"}, timeout=15)
    except: pass

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  💰 PnL CALCULATOR WITH FEES
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def calculate_pnl_with_fees(side, entry, exit_p, pos_size, fee_pct=MXC_FEE_PCT):
    trade_value = pos_size * entry
    fee_per_side = trade_value * (fee_pct / 100)
    total_fee = fee_per_side * 2  # Entry + Exit
    
    if side == "BUY":
        raw_pnl = (exit_p - entry) * pos_size
    else:
        raw_pnl = (entry - exit_p) * pos_size
        
    net_pnl = raw_pnl - total_fee
    return net_pnl, total_fee

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  SIGNALS (OB + FLOW + VELOCITY)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
price_history = []
price_lock    = threading.Lock()

def update_price_history(price):
    with price_lock:
        price_history.append({"price": price, "time": time.time()})
        cutoff = time.time() - 30
        while price_history and price_history[0]["time"] < cutoff: price_history.pop(0)

def analyze_orderbook(ex):
    try:
        ob = safe_fetch_orderbook(ex)
        if not ob or not ob["bids"] or not ob["asks"]: return "FLAT", 0.0, 0.0, 0.0
        best_bid, best_ask = float(ob["bids"][0][0]), float(ob["asks"][0][0])
        spread = ((best_ask - best_bid) / best_bid) * 100
        if spread > MAX_SPREAD: return "FLAT", 0.0, spread, 0.0
        
        bid_vol = sum(float(b[1]) for b in ob["bids"][:10])
        ask_vol = sum(float(a[1]) for a in ob["asks"][:10])
        if ask_vol == 0: return "FLAT", 0.0, spread, 0.0
        
        ratio = bid_vol / ask_vol
        signal = "BUY" if ratio >= OB_IMBALANCE else ("SELL" if ratio <= (1/OB_IMBALANCE) else "FLAT")
        return signal, (best_bid+best_ask)/2, spread, ratio
    except: return "FLAT", 0.0, 0.0, 0.0

def analyze_trade_flow(ex):
    try:
        trades = safe_fetch_trades(ex)
        if not trades: return "FLAT", 0.0, 0.0
        buy_vol = sum(float(t["amount"]) for t in trades if t.get("side")=="buy")
        sell_vol = sum(float(t["amount"]) for t in trades if t.get("side")=="sell")
        if sell_vol == 0: return "FLAT", 0.0, 0.0
        ratio = buy_vol / sell_vol
        signal = "BUY" if ratio >= 1.3 else ("SELL" if ratio <= 0.7 else "FLAT")
        return signal, buy_vol, sell_vol
    except: return "FLAT", 0.0, 0.0

def analyze_velocity():
    try:
        with price_lock:
            if len(price_history) < 3: return "FLAT", 0.0
            recent = price_history[-10:]
            first, last = recent[0]["price"], recent[-1]["price"]
            t1, t2 = recent[0]["time"], recent[-1]["time"]
            if t2 == t1: return "FLAT", 0.0
            pct = ((last - first) / first) * 100
            signal = "BUY" if pct > 0.01 else ("SELL" if pct < -0.01 else "FLAT")
            return signal, pct
    except: return "FLAT", 0.0

def get_combined_signal(ob, flow, vel):
    signals = [ob, flow, vel]
    buy = signals.count("BUY")
    sell = signals.count("SELL")
    return ("BUY", buy) if buy >= 2 else (("SELL", sell) if sell >= 2 else ("FLAT", 0))

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  BACKGROUND THREADS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def run_periodic_update():
    time.sleep(UPDATE_INTERVAL)
    while True:
        try:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with state_lock: st = dict(state)
            pos, price, capital, entry, ob_sig, fl_sig = st["position"], st["last_price"], st["capital"], st["entry_price"], st["ob_signal"], st["flow_signal"]
            daily = get_daily_stats()
            
            msg = f"━━━━━━━━━━━━━━━━━━━━━━\n  ETH BOT UPDATE\n  {now}\n━━━━━━━━━━━━━━━━━━━━━━\n"
            if pos:
                pnl = calculate_pnl_with_fees(pos, entry, price, st["pos_size"])[0]
                msg += f"{'🟢' if pnl>=0 else '🔴'} {pos} | PnL: {pnl:+.4f} USDT | Cap: {capital:.2f}\n"
            else: msg += f"⏳ WAITING | Price: {price:.4f}\n"
            if daily: msg += f"Today: {daily['total']} trades | WR: {daily['win_rate']}% | PnL: {daily['pnl']:+.4f}\n"
            send_telegram(msg)
        except: pass
        time.sleep(UPDATE_INTERVAL)

def run_daily_report():
    while True:
        try:
            ist = timezone(timedelta(hours=5,30))
            now = datetime.now(ist)
            if now.hour==23 and now.minute==59:
                daily = get_daily_stats()
                if daily:
                    msg = f"📊 DAILY REPORT\n{daily['total']} trades | WR: {daily['win_rate']}% | PnL: {daily['pnl']:+.4f} USDT"
                    send_telegram(msg)
                time.sleep(70)
        except: pass
        time.sleep(30)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  🚀 MAIN TRADING ENGINE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def run_trading_engine():
    ex = get_exchange()
    capital = load_capital()
    position = None; entry_price = 0.0; entry_time = None; pos_size = 0.0
    sl_price = 0.0; tp_price = 0.0; capital_used = 0.0; cooldown_end = load_cooldown()
    consecutive_losses = 0

    print("[ENGINE] Started ✅ | Capital: 10000 USDT | Fees Added")
    send_telegram(f"🟢 BOT STARTED\nCapital: 10000 USDT\nFees: {MXC_FEE_PCT}% per side\nScan: {SCAN_INTERVAL}s")

    while True:
        try:
            cur_price = safe_fetch_ticker(ex)
            if not cur_price: time.sleep(SCAN_INTERVAL); continue
            update_price_history(cur_price)

            ob_sig, mid, spread, ob_ratio = analyze_orderbook(ex)
            flow_sig, _, _ = analyze_trade_flow(ex)
            vel_sig, _ = analyze_velocity()
            final_sig, strength = get_combined_signal(ob_sig, flow_sig, vel_sig)

            update_state(last_price=cur_price, capital=capital, position=position, 
                         entry_price=entry_price, entry_time=entry_time, sl_price=sl_price, 
                         tp_price=tp_price, pos_size=pos_size, capital_used=capital_used, 
                         ob_signal=ob_sig, flow_signal=flow_sig, velocity=0.0, last_signal=final_sig)

            # ── POSITION MONITOR ────────────────────────────────
            if position:
                held = (datetime.now() - entry_time).total_seconds()
                net_pnl, fee_used = calculate_pnl_with_fees(position, entry_price, cur_price, pos_size)
                
                hit_tp = (position=="BUY" and cur_price>=tp_price) or (position=="SELL" and cur_price<=tp_price)
                hit_sl = (position=="BUY" and cur_price<=sl_price) or (position=="SELL" and cur_price>=sl_price)
                hit_max = held >= MAX_HOLD

                if hit_tp or hit_sl or hit_max:
                    label = "TP ✅" if hit_tp else ("SL ❌" if hit_sl else "MAX HOLD ⏰")
                    icon = "🟢" if net_pnl>=0 else "🔴"
                    capital += net_pnl
                    save_capital(capital)
                    save_trade(position, entry_price, cur_price, net_pnl, capital, f"{held:.1f}s", label, fee_used)

                    if net_pnl > 0: consecutive_losses = 0; cd = COOLDOWN_WIN
                    else: consecutive_losses += 1; cd = COOLDOWN_2LOSS if consecutive_losses>=2 else COOLDOWN_LOSS

                    print(f"[CLOSED] {label} | PnL={net_pnl:+.4f} | Fee={fee_used:.4f} | Cap={capital:.2f}")
                    send_telegram(f"{icon} {label}\nSide: {position} | Entry: {entry_price:.4f} | Exit: {cur_price:.4f}\nNet PnL: {net_pnl:+.4f} | Fee Deducted: {fee_used:.4f}\nCapital: {capital:.4f}")

                    position = None; entry_price = 0.0; entry_time = None; pos_size = 0.0
                    sl_price = 0.0; tp_price = 0.0; capital_used = 0.0
                    cooldown_end = time.time() + cd; save_cooldown(cooldown_end)
                    update_state(position=None, capital=capital, capital_used=0.0)
                    time.sleep(SCAN_INTERVAL); continue

            # ── COOLDOWN ───────────────────────────────────────
            if cooldown_end and time.time() < cooldown_end:
                time.sleep(SCAN_INTERVAL); continue

            # ── ENTRY ──────────────────────────────────────────
            if not position and final_sig in ["BUY", "SELL"]:
                if spread > MAX_SPREAD: time.sleep(SCAN_INTERVAL); continue
                
                capital_used = capital * (CAPITAL_USE / 100)
                pos_size = (capital_used * LEVERAGE) / cur_price
                entry_price = cur_price; entry_time = datetime.now()
                position = final_sig; cooldown_end = None

                tp_price = entry_price * (1 + TP_PCT/100) if position=="BUY" else entry_price * (1 - TP_PCT/100)
                sl_price = entry_price * (1 - SL_PCT/100) if position=="BUY" else entry_price * (1 + SL_PCT/100)

                net_win, fee_win = calculate_pnl_with_fees(position, entry_price, tp_price, pos_size)
                net_loss, fee_loss = calculate_pnl_with_fees(position, entry_price, sl_price, pos_size)

                print(f"[OPENED] {position} @ {entry_price:.4f} | TP:{tp_price:.4f} | SL:{sl_price:.4f}")
                send_telegram(f"🚀 ENTRY\nSide: {position}\nEntry: {entry_price:.4f} | TP: {tp_price:.4f} | SL: {sl_price:.4f}\nSize: {pos_size:.4f} ETH\nExp Net Win: {net_win:+.4f} | Exp Net Loss: {net_loss:+.4f}\nFee: {fee_win:.4f}")

        except Exception as e:
            print(f"[ENGINE ERROR] {e}")
            if "429" in str(e): time.sleep(5)
            elif "connection" in str(e).lower(): ex = get_exchange(); time.sleep(2)
            else: time.sleep(1)
        time.sleep(SCAN_INTERVAL)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  START
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
if __name__ == "__main__":
    cap_use = CAPITAL * CAPITAL_USE / 100
    exposure = cap_use * LEVERAGE
    print("="*50)
    print("  ETH HF SCALPING BOT v3.1")
    print("  Capital: 10000 USDT | MXC Fees Added")
    print(f"  Exposure: {exposure:.2f} USDT | Scan: {SCAN_INTERVAL}s")
    print("="*50)

    threads = [threading.Thread(target=run_server, daemon=True),
               threading.Thread(target=run_periodic_update, daemon=True),
               threading.Thread(target=run_daily_report, daemon=True),
               threading.Thread(target=run_trading_engine, name="Engine", daemon=True)]
    for t in threads: t.start(); time.sleep(0.2)
    print("[INFO] All threads started ✅")
    while True: time.sleep(60)
