"""
ETH HFT Bot v6.0
Capital  : 10,000 USDT
Leverage : 10x
Hold     : 14 Minutes
Target   : 100-110 trades/day
"""

import os
import json
import time
import threading
from flask import Flask
from datetime import datetime, timezone, timedelta
from collections import deque

from config import *
from signals import SignalEngine
from orders import OrderManager
from telegram_bot import TelegramBot

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  FLASK
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

app = Flask(__name__)

@app.route('/')
def home():
    st = get_state()
    return json.dumps({
        "status"  : "running",
        "mode"    : MODE,
        "capital" : st["capital"],
        "trades"  : st["trades"],
        "wins"    : st["wins"],
        "losses"  : st["losses"],
        "net_pnl" : st["net_pnl"],
        "position": st["position"],
    })

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  STATE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_lock  = threading.Lock()
_state = {
    "capital"      : 0.0,
    "start_cap"    : 0.0,
    "position"     : None,
    "side"         : None,
    "entry_price"  : 0.0,
    "entry_time"   : None,
    "tp_price"     : 0.0,
    "sl_price"     : 0.0,
    "pos_size"     : 0.0,
    "last_price"   : 0.0,
    "ob_signal"    : "FLAT",
    "flow_signal"  : "FLAT",
    "vel_signal"   : "FLAT",
    "trades"       : 0,
    "wins"         : 0,
    "losses"       : 0,
    "net_pnl"      : 0.0,
    "best"         : 0.0,
    "worst"        : 0.0,
    "daily_trades" : 0,
    "daily_pnl"    : 0.0,
    "bot_active"   : True,
}

def get_state():
    with _lock:
        return dict(_state)

def set_state(**kw):
    with _lock:
        for k, v in kw.items():
            if k in _state:
                _state[k] = v

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  CAPITAL
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def load_capital():
    try:
        with open(CAP_FILE, "r") as f:
            cap = float(f.read().strip())
            if cap > 0:
                print(f"[CAP] Loaded: {cap:.4f}")
                return cap
    except Exception:
        pass
    return None

def save_capital(cap):
    try:
        with open(CAP_FILE, "w") as f:
            f.write(str(round(cap, 6)))
    except Exception as e:
        print(f"[CAP ERR] {e}")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  HISTORY
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_hist_lock = threading.Lock()

def save_trade(data):
    try:
        with _hist_lock:
            try:
                with open(
                    HIST_FILE, "r",
                    encoding="utf-8"
                ) as f:
                    h = json.load(f)
            except Exception:
                h = []
            h.append(data)
            if len(h) > 100000:
                h = h[-100000:]
            with open(
                HIST_FILE, "w",
                encoding="utf-8"
            ) as f:
                json.dump(h, f, indent=2)
    except Exception as e:
        print(f"[HIST ERR] {e}")

def get_daily_stats():
    try:
        with open(
            HIST_FILE, "r",
            encoding="utf-8"
        ) as f:
            h = json.load(f)
    except Exception:
        return None
    today  = datetime.now().strftime("%d/%m/%Y")
    trades = [t for t in h if t["date"] == today]
    if not trades:
        return None
    pnls   = [t["net_pnl"] for t in trades]
    wins   = len([
        t for t in trades
        if t["result"] == "WIN"
    ])
    losses = len(trades) - wins
    return {
        "total"   : len(trades),
        "wins"    : wins,
        "losses"  : losses,
        "win_rate": round(
            wins / len(trades) * 100, 1
        ),
        "pnl"     : round(sum(pnls), 4),
        "best"    : round(max(pnls), 4),
        "worst"   : round(min(pnls), 4),
        "capital" : trades[-1]["capital"],
    }

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  FINISH TRADE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def finish_trade(
    tg, side, entry, exit_p,
    qty, net_fee, reason,
    elapsed, capital, trade_num
):
    # Gross PnL
    if side == "BUY":
        gross = (exit_p - entry) * qty
    else:
        gross = (entry - exit_p) * qty

    net_pnl     = gross - net_fee
    new_capital = capital + net_pnl

    st      = get_state()
    trades  = st["trades"] + 1
    wins    = st["wins"]
    losses  = st["losses"]
    net     = st["net_pnl"] + net_pnl
    best    = st["best"]
    worst   = st["worst"]
    d_pnl   = st["daily_pnl"] + net_pnl
    d_trades = st["daily_trades"] + 1

    is_win = net_pnl > 0

    if is_win:
        wins  += 1
        icon   = "✅"
        label  = "WIN"
    else:
        losses += 1
        icon    = "❌"
        label   = "LOSS"

    if net_pnl > best:
        best = net_pnl
    if worst == 0 or net_pnl < worst:
        worst = net_pnl

    wr = round(
        wins / max(1, trades) * 100, 1
    )

    set_state(
        capital      = new_capital,
        trades       = trades,
        wins         = wins,
        losses       = losses,
        net_pnl      = net,
        best         = best,
        worst        = worst,
        daily_pnl    = d_pnl,
        daily_trades = d_trades,
        position     = None,
        side         = None,
        entry_price  = 0.0,
        tp_price     = 0.0,
        sl_price     = 0.0,
        pos_size     = 0.0,
        entry_time   = None,
    )

    save_capital(new_capital)

    mins = int(elapsed // 60)
    secs = int(elapsed % 60)
    dur  = f"{mins}m {secs}s"

    save_trade({
        "num"    : trade_num,
        "date"   : datetime.now().strftime(
            "%d/%m/%Y"
        ),
        "time"   : datetime.now().strftime(
            "%H:%M:%S"
        ),
        "mode"   : MODE,
        "side"   : side,
        "entry"  : round(entry, 2),
        "exit"   : round(exit_p, 2),
        "qty"    : qty,
        "gross"  : round(gross, 4),
        "fee"    : round(net_fee, 4),
        "net_pnl": round(net_pnl, 4),
        "capital": round(new_capital, 4),
        "dur"    : dur,
        "reason" : reason,
        "result" : label,
    })

    print(
        f"[#{trade_num}] {label} | "
        f"{side} | {reason} | "
        f"Net={net_pnl:+.4f} | "
        f"Cap={new_capital:.2f} | "
        f"WR={wr}%"
    )

    tg.send(
        f"{icon} {label} #{trade_num}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Side   : {side}\n"
        f"Reason : {reason}\n"
        f"Entry  : {entry:.2f}\n"
        f"Exit   : {exit_p:.2f}\n"
        f"Time   : {dur}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Gross  : {gross:+.4f} USDT\n"
        f"Fee    : {net_fee:+.4f} USDT\n"
        f"NET    : {net_pnl:+.4f} USDT\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Capital: {new_capital:.4f} USDT\n"
        f"WR     : {wr}%\n"
        f"Trades : {trades}\n"
        f"D/PnL  : {d_pnl:+.4f} USDT\n"
        f"━━━━━━━━━━━━━━━━━━━━━━"
    )

    return new_capital

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  POSITION MONITOR
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def monitor_position(
    tg, om, sig_engine,
    side, fill_price,
    tp_px, sl_px,
    tp_side, sl_side,
    tp_id, qty, capital
):
    start_time = time.time()
    st         = get_state()
    trade_num  = st["trades"] + 1

    while True:
        elapsed   = time.time() - start_time
        cur_price = sig_engine.get_price()

        # TP Check
        if tp_id:
            tp_status = om.get_order(tp_id)
            if (tp_status and
                    tp_status.get(
                        "status"
                    ) == "FILLED"):
                exit_px = float(
                    tp_status.get(
                        "avgPrice", tp_px
                    )
                )
                net_fee = om.calc_fees(
                    fill_price, exit_px,
                    qty, is_tp=True
                )
                return finish_trade(
                    tg, side,
                    fill_price, exit_px,
                    qty, net_fee,
                    "TP ✅", elapsed,
                    capital, trade_num
                )

        # SL Check
        sl_hit = (
            (side == "BUY" and
             cur_price > 0 and
             cur_price <= sl_px) or
            (side == "SELL" and
             cur_price > 0 and
             cur_price >= sl_px)
        )

        # 14 Min Force Exit
        time_hit = elapsed >= MAX_HOLD

        if sl_hit or time_hit:
            if sl_hit:
                reason = "SL ❌"
            else:
                # Check profit or loss
                if side == "BUY":
                    pnl_now = (
                        cur_price - fill_price
                    ) * qty
                else:
                    pnl_now = (
                        fill_price - cur_price
                    ) * qty

                if pnl_now >= 0:
                    reason = "14MIN ✅ Profit"
                else:
                    reason = "14MIN ❌ Loss"

            # Cancel TP
            if tp_id:
                om.cancel_order(tp_id)

            # Market exit
            _, exit_px = om.place_market_sl(
                sl_side, qty
            )

            if not exit_px or exit_px == 0:
                exit_px = cur_price

            net_fee = om.calc_fees(
                fill_price, exit_px,
                qty, is_tp=False
            )

            return finish_trade(
                tg, side,
                fill_price, exit_px,
                qty, net_fee,
                reason, elapsed,
                capital, trade_num
            )

        time.sleep(0.1)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  EXECUTE TRADE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def execute_trade(
    tg, om, sig_engine,
    signal, price, capital
):
    qty = om.calc_qty(capital, price)
    if qty <= 0:
        print("[EXEC] Qty = 0, skip")
        return capital

    # Entry price
    if signal == "BUY":
        entry_px = round(price - 0.01, 2)
        tp_px    = round(
            entry_px * (1 + TP_PCT / 100), 2
        )
        sl_px    = round(
            entry_px * (1 - SL_PCT / 100), 2
        )
        tp_side  = "SELL"
        sl_side  = "SELL"
    else:
        entry_px = round(price + 0.01, 2)
        tp_px    = round(
            entry_px * (1 - TP_PCT / 100), 2
        )
        sl_px    = round(
            entry_px * (1 + SL_PCT / 100), 2
        )
        tp_side  = "BUY"
        sl_side  = "BUY"

    # Limit entry
    entry_id = om.place_limit_entry(
        signal, entry_px, qty
    )
    if not entry_id:
        return capital

    set_state(position="PENDING")

    # 3 sec wait
    filled     = False
    fill_price = entry_px

    for _ in range(30):
        time.sleep(0.1)
        status = om.get_order(entry_id)
        if not status:
            continue
        if status.get("status") == "FILLED":
            fill_price = float(
                status.get("avgPrice", entry_px)
            )
            filled = True
            break
        elif status.get("status") in [
            "CANCELED", "EXPIRED", "REJECTED"
        ]:
            set_state(position=None)
            return capital

    if not filled:
        om.cancel_order(entry_id)
        set_state(position=None)
        print("[EXEC] Fill nahi hua - cancel")
        return capital

    print(
        f"[FILLED] {signal} "
        f"{qty}@{fill_price:.2f} ✅"
    )

    # Recalculate
    if signal == "BUY":
        tp_px = round(
            fill_price * (1 + TP_PCT / 100), 2
        )
        sl_px = round(
            fill_price * (1 - SL_PCT / 100), 2
        )
    else:
        tp_px = round(
            fill_price * (1 - TP_PCT / 100), 2
        )
        sl_px = round(
            fill_price * (1 + SL_PCT / 100), 2
        )

    # TP limit order
    tp_id = om.place_limit_tp(
        tp_side, tp_px, qty
    )

    set_state(
        position    = "OPEN",
        side        = signal,
        entry_price = fill_price,
        tp_price    = tp_px,
        sl_price    = sl_px,
        pos_size    = qty,
        entry_time  = time.time(),
    )

    st       = get_state()
    exp_win  = round(
        fill_price * qty * TP_PCT / 100, 2
    )
    exp_loss = round(
        fill_price * qty * SL_PCT / 100, 2
    )

    tg.send(
        f"🚀 ENTRY #{st['trades'] + 1}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Mode    : {MODE}\n"
        f"Side    : {signal}\n"
        f"Entry   : {fill_price:.2f}\n"
        f"TP      : {tp_px:.2f}\n"
        f"SL      : {sl_px:.2f}\n"
        f"Qty     : {qty}\n"
        f"Hold    : 14 min max\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Exp Win : +{exp_win} USDT\n"
        f"Exp Loss: -{exp_loss} USDT\n"
        f"Capital : {capital:.2f} USDT\n"
        f"━━━━━━━━━━━━━━━━━━━━━━"
    )

    new_cap = monitor_position(
        tg, om, sig_engine,
        signal, fill_price,
        tp_px, sl_px,
        tp_side, sl_side,
        tp_id, qty, capital
    )

    return new_cap

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  UPDATE WORKER
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def update_worker(tg):
    time.sleep(60)
    while True:
        try:
            st     = get_state()
            cap    = st["capital"]
            scap   = st["start_cap"]
            growth = round(cap - scap, 4)
            growp  = round(
                growth / max(1, scap) * 100, 2
            )
            wr  = round(
                st["wins"] /
                max(1, st["trades"]) * 100, 1
            )
            now = datetime.now().strftime(
                "%Y-%m-%d %H:%M"
            )

            pos_txt = ""
            if st["position"] == "OPEN":
                cp      = st["last_price"]
                elapsed = 0
                if st["entry_time"]:
                    elapsed = int(
                        time.time() -
                        st["entry_time"]
                    )
                mins = elapsed // 60
                secs = elapsed % 60
                pnl_now = (
                    (cp - st["entry_price"]) *
                    st["pos_size"]
                    if st["side"] == "BUY"
                    else
                    (st["entry_price"] - cp) *
                    st["pos_size"]
                )
                icon = (
                    "🟢" if pnl_now >= 0
                    else "🔴"
                )
                remaining = max(
                    0,
                    MAX_HOLD - elapsed
                )
                pos_txt = (
                    f"POSITION {icon}\n"
                    f"Side    : {st['side']}\n"
                    f"Entry   : "
                    f"{st['entry_price']:.2f}\n"
                    f"Now     : {cp:.2f}\n"
                    f"TP      : "
                    f"{st['tp_price']:.2f}\n"
                    f"SL      : "
                    f"{st['sl_price']:.2f}\n"
                    f"PnL     : {pnl_now:+.4f}\n"
                    f"Held    : {mins}m {secs}s\n"
                    f"Exit In : "
                    f"{remaining//60}m "
                    f"{remaining%60}s\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                )

            daily = get_daily_stats()

            msg = (
                f"📊 STATUS UPDATE\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"{now} | {MODE}\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"{pos_txt}"
                f"STATS\n"
                f"Trades : {st['trades']}\n"
                f"Wins   : {st['wins']} ✅\n"
                f"Losses : {st['losses']} ❌\n"
                f"WR     : {wr}%\n"
                f"Net    : "
                f"{st['net_pnl']:+.4f} USDT\n"
                f"Best   : "
                f"{st['best']:+.4f} USDT\n"
                f"Worst  : "
                f"{st['worst']:+.4f} USDT\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"CAPITAL\n"
                f"Start  : {scap:.2f}\n"
                f"Now    : {cap:.4f}\n"
                f"Growth : {growth:+.4f}\n"
                f"ROI    : {growp:+.2f}%\n"
                f"━━━━━━━━━━━━━━━━━━━━━━"
            )

            if daily:
                msg += (
                    f"\nTODAY\n"
                    f"Trades : {daily['total']}\n"
                    f"WR     : "
                    f"{daily['win_rate']}%\n"
                    f"PnL    : "
                    f"{daily['pnl']:+.4f} USDT\n"
                    f"Best   : "
                    f"+{daily['best']:.4f}\n"
                    f"Worst  : "
                    f"{daily['worst']:.4f}\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━"
                )

            tg.send(msg)

        except Exception as e:
            print(f"[UPD ERR] {e}")

        time.sleep(UPDATE_MIN * 60)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  DAILY WORKER
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def daily_worker(tg):
    while True:
        try:
            ist = timezone(
                timedelta(hours=5, minutes=30)
            )
            now = datetime.now(ist)

            if (now.hour == 23 and
                    now.minute == 59):

                daily = get_daily_stats()
                st    = get_state()
                today = now.strftime("%d/%m/%Y")

                set_state(
                    daily_pnl    = 0.0,
                    daily_trades = 0,
                )

                if daily:
                    growth = round(
                        st["capital"] -
                        st["start_cap"], 4
                    )
                    roi = round(
                        growth /
                        max(1, st["start_cap"])
                        * 100, 2
                    )
                    tg.send(
                        f"📅 DAILY REPORT\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"{today} | {MODE}\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"Trades : "
                        f"{daily['total']}\n"
                        f"Wins   : "
                        f"{daily['wins']} ✅\n"
                        f"Losses : "
                        f"{daily['losses']} ❌\n"
                        f"WR     : "
                        f"{daily['win_rate']}%\n"
                        f"PnL    : "
                        f"{daily['pnl']:+.4f}\n"
                        f"Best   : "
                        f"+{daily['best']:.4f}\n"
                        f"Worst  : "
                        f"{daily['worst']:.4f}\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"Capital: "
                        f"{st['capital']:.4f}\n"
                        f"Growth : {growth:+.4f}\n"
                        f"ROI    : {roi:+.2f}%\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━"
                    )
                else:
                    tg.send(
                        f"📅 DAILY REPORT\n"
                        f"{today}\n"
                        f"Aaj koi trade nahi hua"
                    )
                time.sleep(70)

        except Exception as e:
            print(f"[DAILY ERR] {e}")
        time.sleep(30)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  MAIN ENGINE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def run_engine(tg, om, sig_engine):
    print("=" * 45)
    print("  ETH HFT BOT v6.0")
    print(f"  MODE: {MODE}")
    print("=" * 45)

    # Balance fetch
    balance = om.get_balance()
    saved   = load_capital()

    if saved and saved > 0:
        capital = saved
    elif balance and balance > 0:
        capital = balance
        save_capital(capital)
    else:
        capital = CAPITAL
        save_capital(capital)

    set_state(
        capital   = capital,
        start_cap = capital,
        bot_active = True,
    )

    print(f"[CAP] {capital:.4f} USDT")
    print("[WS] Data aane ka wait 5s...")
    time.sleep(5)

    tg.send(
        f"🤖 ETH HFT BOT v6.0\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Mode    : {MODE}\n"
        f"Capital : {capital:.2f} USDT\n"
        f"Leverage: {LEVERAGE}x\n"
        f"TP      : {TP_PCT}%\n"
        f"SL      : {SL_PCT}%\n"
        f"Hold    : 14 Minutes\n"
        f"Target  : 100-110 trades/day\n"
        f"Entry   : Limit Order\n"
        f"TP      : Limit Order\n"
        f"SL      : Market Order\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Bot Live! Kabhi Nahi Rukega!\n"
        f"━━━━━━━━━━━━━━━━━━━━━━"
    )

    cooldown_end = 0.0

    while True:
        try:
            st = get_state()

            # Position open hai
            if st["position"] is not None:
                time.sleep(0.1)
                continue

            # Cooldown
            if time.time() < cooldown_end:
                remaining = int(
                    cooldown_end - time.time()
                )
                print(
                    f"[CD] {remaining}s baki..."
                )
                time.sleep(1)
                continue

            # Signal
            (signal, strength,
             ob, flow, vel) = (
                sig_engine.get_signal()
            )

            price = sig_engine.get_price()

            if price <= 0:
                time.sleep(0.1)
                continue

            set_state(last_price=price)

            if signal in ["BUY", "SELL"]:
                print(
                    f"[SIGNAL] {signal} | "
                    f"OB={ob} FL={flow} "
                    f"VL={vel} | "
                    f"P={price:.2f} | "
                    f"Str={strength}/3"
                )

                capital = st["capital"]
                new_cap = execute_trade(
                    tg, om, sig_engine,
                    signal, price, capital
                )

                # Cooldown
                if new_cap >= capital:
                    cooldown_end = (
                        time.time() +
                        COOLDOWN_WIN
                    )
                else:
                    cooldown_end = (
                        time.time() +
                        COOLDOWN_LOSS
                    )
            else:
                print(
                    f"[WAIT] "
                    f"OB={ob} FL={flow} "
                    f"VL={vel} | "
                    f"P={price:.2f}"
                )

            time.sleep(0.1)

        except Exception as e:
            err = str(e)
            print(f"[ENGINE ERR] {err}")
            if "429" in err:
                time.sleep(30)
            elif "connection" in err.lower():
                time.sleep(5)
            else:
                time.sleep(2)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  START
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

if __name__ == "__main__":

    if not API_KEY or not API_SECRET:
        print("❌ API_KEY aur API_SECRET daalo!")
        exit(1)

    # Objects banao
    tg         = TelegramBot(BOT_TOKEN, CHAT_ID)
    om         = OrderManager()
    sig_engine = SignalEngine()

    # Exchange setup
    om.setup_exchange()

    # WebSockets start
    sig_engine.start_websockets()

    # Threads
    threads = [
        threading.Thread(
            target=run_flask,
            name="Flask",
            daemon=True
        ),
        threading.Thread(
            target=tg.run,
            name="Telegram",
            daemon=True
        ),
        threading.Thread(
            target=update_worker,
            args=(tg,),
            name="Update",
            daemon=True
        ),
        threading.Thread(
            target=daily_worker,
            args=(tg,),
            name="Daily",
            daemon=True
        ),
        threading.Thread(
            target=run_engine,
            args=(tg, om, sig_engine),
            name="Engine",
            daemon=True
        ),
    ]

    for t in threads:
        t.start()
        print(f"[✅] {t.name} started")
        time.sleep(0.3)

    print("=" * 45)
    print(f"[✅] {MODE} Mode")
    print("[✅] Bot Live 24/7!")
    print("[✅] Kabhi Nahi Rukega!")
    print("=" * 45)

    while True:
        time.sleep(60)
