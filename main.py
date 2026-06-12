"""
main.py
───────
HFT Bot v5.1 — ETH/USDT Perpetual Futures (Binance)

Changes in v5.1:
  - Har 30 min mein Telegram status update
  - Loose thresholds — signals zyada aayenge
  - Liquidation stream removed (testnet pe kaam nahi karta)
"""

import time
import logging
import threading
import signal as sys_signal
from http.server import HTTPServer, BaseHTTPRequestHandler

from binance.client import Client
from binance import ThreadedWebsocketManager

import config
import signals
import orders
import telegram_bot as tg

# ─────────────────────────────────────────────
#  LOGGING
# ─────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("main")


# ─────────────────────────────────────────────
#  KEEP-ALIVE SERVER  (for UptimeRobot / Render)
# ─────────────────────────────────────────────
class PingHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"HFT Bot is running")

    def log_message(self, format, *args):
        pass


def start_keep_alive():
    server = HTTPServer(("0.0.0.0", config.KEEP_ALIVE_PORT), PingHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logger.info(f"Keep-alive server running on port {config.KEEP_ALIVE_PORT}")


# ─────────────────────────────────────────────
#  BINANCE CLIENT SETUP
# ─────────────────────────────────────────────
def create_client() -> Client:
    client = Client(
        api_key    = config.BINANCE_API_KEY,
        api_secret = config.BINANCE_API_SECRET,
        testnet    = config.USE_TESTNET,
    )
    client.API_URL = config.BINANCE_BASE_URL + "/api"
    client.FUTURES_URL = config.BINANCE_BASE_URL + "/fapi"
    return client


# ─────────────────────────────────────────────
#  WEBSOCKET HANDLERS
# ─────────────────────────────────────────────
_latest_price: float = 0.0


def handle_mark_price(msg):
    global _latest_price
    if msg.get("e") == "markPriceUpdate":
        price = float(msg["p"])
        _latest_price = price
        signals.update_price_history(price)


# ─────────────────────────────────────────────
#  TRADE STATE
# ─────────────────────────────────────────────
class TradeState:
    def __init__(self):
        self.reset()
        self.total_trades  = 0
        self.total_wins    = 0
        self.total_losses  = 0
        self.total_pnl     = 0.0
        self.session_start = time.time()

    def reset(self):
        self.in_trade       = False
        self.direction      = None
        self.entry_price    = None
        self.qty            = None
        self.entry_order_id = None
        self.tp_order_id    = None
        self.sl_order_id    = None
        self.entry_time     = None

trade = TradeState()


# ─────────────────────────────────────────────
#  30 MIN STATUS UPDATE
# ─────────────────────────────────────────────
_last_status_time = time.time()
STATUS_INTERVAL   = 30 * 60  # 30 minutes


def send_status_update(client):
    """Har 30 min mein Telegram pe bot ki full status bhejo."""
    try:
        balance   = orders.get_available_balance(client)
        position  = orders.get_open_position(client)
        uptime_min = int((time.time() - trade.session_start) / 60)

        if position:
            pos_amt   = float(position["positionAmt"])
            direction = "LONG" if pos_amt > 0 else "SHORT"
            entry_px  = float(position["entryPrice"])
            unrealized = float(position["unrealizedProfit"])
            trade_status = (
                f"📊 Active Trade: {direction}\n"
                f"Entry: <code>{entry_px:.4f}</code>\n"
                f"Unrealized PnL: <code>{unrealized:+.4f} USDT</code>"
            )
        else:
            trade_status = "💤 No active trade"

        win_rate = (
            f"{(trade.total_wins / trade.total_trades * 100):.1f}%"
            if trade.total_trades > 0 else "N/A"
        )

        tg.send_message(
            f"📈 <b>Bot Status Update</b>\n"
            f"{'─' * 25}\n"
            f"⏱ Uptime: <code>{uptime_min} min</code>\n"
            f"💰 Balance: <code>{balance:.2f} USDT</code>\n"
            f"📉 ETH Price: <code>{_latest_price:.4f}</code>\n"
            f"{'─' * 25}\n"
            f"{trade_status}\n"
            f"{'─' * 25}\n"
            f"📊 Session Stats:\n"
            f"Total Trades: <code>{trade.total_trades}</code>\n"
            f"Wins: <code>{trade.total_wins}</code> | "
            f"Losses: <code>{trade.total_losses}</code>\n"
            f"Win Rate: <code>{win_rate}</code>\n"
            f"Total PnL: <code>{trade.total_pnl:+.4f} USDT</code>"
        )
        logger.info("30 min status update sent to Telegram")

    except Exception as e:
        logger.error(f"Status update failed: {e}")


# ─────────────────────────────────────────────
#  MAIN BOT LOGIC
# ─────────────────────────────────────────────
def check_and_manage_trade(client, filters):
    global trade, _last_status_time

    # ── 30 min status update check ──
    if time.time() - _last_status_time >= STATUS_INTERVAL:
        send_status_update(client)
        _last_status_time = time.time()

    # ── 1. Agar trade chal raha hai ──
    if trade.in_trade:
        position = orders.get_open_position(client)

        if position is None:
            tp_status = orders.get_order_status(client, trade.tp_order_id) if trade.tp_order_id else "UNKNOWN"
            sl_status = orders.get_order_status(client, trade.sl_order_id) if trade.sl_order_id else "UNKNOWN"

            if tp_status == "FILLED":
                tp_price = trade.entry_price * (1 + config.TP_PCT) if trade.direction == "LONG" \
                           else trade.entry_price * (1 - config.TP_PCT)
                pnl = abs(tp_price - trade.entry_price) * trade.qty
                trade.total_wins  += 1
                trade.total_pnl   += pnl
                tg.notify_take_profit(trade.direction, trade.entry_price, tp_price, pnl)
                logger.info(f"✅ TP hit | PnL ≈ +{pnl:.4f} USDT")

            elif sl_status == "FILLED":
                sl_price = trade.entry_price * (1 - config.SL_PCT) if trade.direction == "LONG" \
                           else trade.entry_price * (1 + config.SL_PCT)
                pnl = -abs(sl_price - trade.entry_price) * trade.qty
                trade.total_losses += 1
                trade.total_pnl    += pnl
                tg.notify_stop_loss(trade.direction, trade.entry_price, sl_price, pnl)
                logger.info(f"🛑 SL hit | PnL ≈ {pnl:.4f} USDT")
            else:
                logger.info("Position closed (unknown reason) — cleaning up")

            trade.total_trades += 1
            orders.cancel_all_orders(client)
            trade.reset()
        return

    # ── 2. Entry order pending ──
    if trade.entry_order_id:
        status = orders.get_order_status(client, trade.entry_order_id)

        if status == "FILLED":
            logger.info(f"Entry filled at ~{trade.entry_price}")
            trade.in_trade = True

            tp_order = orders.place_take_profit_order(
                client, trade.direction, trade.entry_price, trade.qty, filters
            )
            sl_order = orders.place_stop_loss_order(
                client, trade.direction, trade.entry_price, trade.qty, filters
            )

            trade.tp_order_id = tp_order["orderId"] if tp_order else None
            trade.sl_order_id = sl_order["orderId"] if sl_order else None

            tp_price = trade.entry_price * (1 + config.TP_PCT) if trade.direction == "LONG" \
                       else trade.entry_price * (1 - config.TP_PCT)
            sl_price = trade.entry_price * (1 - config.SL_PCT) if trade.direction == "LONG" \
                       else trade.entry_price * (1 + config.SL_PCT)

            tg.notify_entry(
                trade.direction, trade.entry_price, trade.qty,
                tp_price, sl_price, {}
            )

        elif time.time() - trade.entry_time > config.ORDER_TIMEOUT_SEC:
            orders.cancel_order(client, trade.entry_order_id)
            tg.notify_entry_timeout(trade.direction, trade.entry_order_id)
            logger.info(f"Entry order timed out — cancelled")
            trade.entry_order_id = None
            trade.direction      = None
            trade.entry_time     = None

        return

    # ── 3. Naya signal dhundo ──
    if _latest_price == 0:
        logger.debug("No price data yet — waiting")
        return

    direction = signals.get_trade_signal(client)

    if direction in ("LONG", "SHORT"):
        logger.info(f"Signal confirmed: {direction} @ {_latest_price}")
        entry_order = orders.place_entry_order(client, direction, filters)
        if entry_order:
            trade.entry_order_id = entry_order["orderId"]
            trade.direction      = direction
            trade.entry_price    = float(entry_order["price"])
            trade.qty            = float(entry_order["origQty"])
            trade.entry_time     = time.time()
            logger.info(f"Entry order placed: {trade.entry_order_id}")


# ─────────────────────────────────────────────
#  GRACEFUL SHUTDOWN
# ─────────────────────────────────────────────
_running = True


def handle_shutdown(signum, frame):
    global _running
    logger.info("Shutdown signal received...")
    _running = False


# ─────────────────────────────────────────────
#  MAIN ENTRY POINT
# ─────────────────────────────────────────────
def main():
    global _running

    logger.info("=" * 50)
    logger.info(f"HFT Bot v5.1 Starting — {'TESTNET' if config.USE_TESTNET else 'LIVE'}")
    logger.info(f"Symbol: {config.SYMBOL} | Leverage: {config.LEVERAGE}x")
    logger.info("=" * 50)

    sys_signal.signal(sys_signal.SIGTERM, handle_shutdown)
    sys_signal.signal(sys_signal.SIGINT,  handle_shutdown)

    start_keep_alive()

    client = create_client()
    orders.set_leverage(client)

    filters = orders.get_symbol_filters(client)
    logger.info(f"Filters: {filters}")

    tg.notify_bot_started()

    # WebSocket — sirf mark price (liquidation hataya)
    twm = ThreadedWebsocketManager(
        api_key    = config.BINANCE_API_KEY,
        api_secret = config.BINANCE_API_SECRET,
        testnet    = config.USE_TESTNET,
    )
    twm.start()

    twm.start_symbol_mark_price_socket(
        callback = handle_mark_price,
        symbol   = config.SYMBOL.lower(),
    )

    logger.info("WebSocket started — entering main loop")

    try:
        while _running:
            try:
                check_and_manage_trade(client, filters)
            except Exception as e:
                logger.error(f"Loop error: {e}")
                tg.notify_error(str(e))

            time.sleep(config.LOOP_INTERVAL_SEC)

    finally:
        logger.info("Shutting down...")
        twm.stop()
        orders.cancel_all_orders(client)
        tg.notify_bot_stopped()
        logger.info("Bot stopped cleanly ✅")


if __name__ == "__main__":
    main()
