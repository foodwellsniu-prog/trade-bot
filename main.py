"""
main.py
───────
HFT Bot v5.0 — ETH/USDT Perpetual Futures (Binance)

Architecture:
  - WebSocket stream  → price updates + liquidation events (real-time)
  - Main loop         → signal check every LOOP_INTERVAL_SEC
  - Order manager     → Maker entry + Limit TP + Market SL
  - Telegram alerts   → every trade event
  - Keep-alive server → HTTP ping for UptimeRobot / Render
"""

import time
import logging
import asyncio
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
        pass  # Suppress HTTP access logs


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
    """Update latest mark price and feed price history for velocity signal."""
    global _latest_price
    if msg.get("e") == "markPriceUpdate":
        price = float(msg["p"])
        _latest_price = price
        signals.update_price_history(price)


def handle_liquidation(msg):
    """Feed liquidation events to the liquidation signal buffer."""
    if msg.get("e") == "forceOrder":
        order = msg.get("o", {})
        side  = order.get("S")   # 'BUY' = short was liquidated, 'SELL' = long was liquidated
        qty   = float(order.get("q", 0))
        if side and qty > 0:
            signals.add_liquidation(side, qty)
            logger.debug(f"Liquidation: {side} {qty} ETH")


# ─────────────────────────────────────────────
#  TRADE STATE
# ─────────────────────────────────────────────
class TradeState:
    def __init__(self):
        self.reset()

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
#  MAIN BOT LOGIC
# ─────────────────────────────────────────────
def check_and_manage_trade(client, filters):
    global trade

    # ── 1. If in a trade — check if TP or SL was hit ──
    if trade.in_trade:
        position = orders.get_open_position(client)

        if position is None:
            # Position closed — determine which order filled
            tp_status = orders.get_order_status(client, trade.tp_order_id) if trade.tp_order_id else "UNKNOWN"
            sl_status = orders.get_order_status(client, trade.sl_order_id) if trade.sl_order_id else "UNKNOWN"

            if tp_status == "FILLED":
                tp_price = trade.entry_price * (1 + config.TP_PCT) if trade.direction == "LONG" \
                           else trade.entry_price * (1 - config.TP_PCT)
                pnl      = abs(tp_price - trade.entry_price) * trade.qty
                tg.notify_take_profit(trade.direction, trade.entry_price, tp_price, pnl)
                logger.info(f"✅ TP hit | PnL ≈ +{pnl:.4f} USDT")
            elif sl_status == "FILLED":
                sl_price = trade.entry_price * (1 - config.SL_PCT) if trade.direction == "LONG" \
                           else trade.entry_price * (1 + config.SL_PCT)
                pnl      = -abs(sl_price - trade.entry_price) * trade.qty
                tg.notify_stop_loss(trade.direction, trade.entry_price, sl_price, pnl)
                logger.info(f"🛑 SL hit | PnL ≈ {pnl:.4f} USDT")
            else:
                logger.info("Position closed (unknown reason) — cleaning up")

            # Cancel any remaining orders and reset state
            orders.cancel_all_orders(client)
            trade.reset()
        return  # Don't look for new signals while in trade

    # ── 2. If entry order pending — check if filled or timeout ──
    if trade.entry_order_id:
        status = orders.get_order_status(client, trade.entry_order_id)

        if status == "FILLED":
            # Entry filled → place TP and SL
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

            # Notify Telegram
            tg.notify_entry(
                trade.direction, trade.entry_price, trade.qty,
                tp_price, sl_price,
                {}  # signals dict — pass if you want to log in notification
            )

        elif time.time() - trade.entry_time > config.ORDER_TIMEOUT_SEC:
            # Entry not filled in time → cancel
            orders.cancel_order(client, trade.entry_order_id)
            tg.notify_entry_timeout(trade.direction, trade.entry_order_id)
            logger.info(f"Entry order {trade.entry_order_id} timed out — cancelled")
            trade.entry_order_id = None
            trade.direction      = None
            trade.entry_time     = None

        return  # Wait for entry to resolve

    # ── 3. No active trade — look for new signal ──
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
            logger.info(f"Waiting for entry fill: {trade.entry_order_id}")


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
    logger.info(f"HFT Bot v5.0 Starting — {'TESTNET' if config.USE_TESTNET else 'LIVE'}")
    logger.info(f"Symbol: {config.SYMBOL} | Leverage: {config.LEVERAGE}x")
    logger.info("=" * 50)

    # Register graceful shutdown handlers
    sys_signal.signal(sys_signal.SIGTERM, handle_shutdown)
    sys_signal.signal(sys_signal.SIGINT,  handle_shutdown)

    # Start keep-alive HTTP server
    start_keep_alive()

    # Connect to Binance
    client = create_client()

    # Set leverage
    orders.set_leverage(client)

    # Get symbol filters (tick size, step size)
    filters = orders.get_symbol_filters(client)
    logger.info(f"Filters: {filters}")

    # Notify bot started
    tg.notify_bot_started()

    # Start WebSocket streams
    twm = ThreadedWebsocketManager(
        api_key    = config.BINANCE_API_KEY,
        api_secret = config.BINANCE_API_SECRET,
        testnet    = config.USE_TESTNET,
    )
    twm.start()

    # Mark price stream (real-time price + funding)
    twm.start_symbol_mark_price_socket(
        callback = handle_mark_price,
        symbol   = config.SYMBOL.lower(),
    )

    # Liquidation stream (all ETHUSDT liquidations)
    twm.start_symbol_futures_socket(
        callback = handle_liquidation,
        symbol   = config.SYMBOL.lower(),
    )

    logger.info("WebSocket streams started — entering main loop")

    # ── MAIN LOOP ──
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
