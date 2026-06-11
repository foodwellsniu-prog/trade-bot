"""
orders.py
─────────
Handles all order placement:
  - Maker limit entry (slightly inside spread)
  - Limit Take Profit  (maker rebate)
  - Market Stop Loss   (safety — always fills)
"""

import logging
import math
from binance.enums import (
    SIDE_BUY, SIDE_SELL,
    ORDER_TYPE_LIMIT,
    ORDER_TYPE_MARKET,
    FUTURE_ORDER_TYPE_STOP_MARKET,
    FUTURE_ORDER_TYPE_TAKE_PROFIT,
    TIME_IN_FORCE_GTX,   # Post-Only (ensures maker, rejects if would be taker)
    TIME_IN_FORCE_GTC,
)
from config import (
    SYMBOL, LEVERAGE, RISK_PCT,
    TP_PCT, SL_PCT, ENTRY_OFFSET,
    ORDER_TIMEOUT_SEC
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────
def _round_price(price: float, tick_size: float) -> float:
    """Round price to exchange tick size."""
    precision = int(round(-math.log10(tick_size)))
    return round(price, precision)


def _round_qty(qty: float, step_size: float) -> float:
    """Round quantity to exchange step size."""
    precision = int(round(-math.log10(step_size)))
    return round(qty, precision)


def get_symbol_filters(client) -> dict:
    """
    Returns tick_size and step_size for SYMBOL.
    Cached per session to avoid repeated API calls.
    """
    info = client.futures_exchange_info()
    for s in info["symbols"]:
        if s["symbol"] == SYMBOL:
            tick_size  = None
            step_size  = None
            for f in s["filters"]:
                if f["filterType"] == "PRICE_FILTER":
                    tick_size = float(f["tickSize"])
                if f["filterType"] == "LOT_SIZE":
                    step_size = float(f["stepSize"])
            return {"tick_size": tick_size, "step_size": step_size}
    raise ValueError(f"Symbol {SYMBOL} not found in exchange info")


def get_available_balance(client) -> float:
    """Return USDT available balance in futures wallet."""
    account = client.futures_account_balance()
    for asset in account:
        if asset["asset"] == "USDT":
            return float(asset["availableBalance"])
    return 0.0


def calculate_position_size(client, entry_price: float, filters: dict) -> float:
    """
    position_size = (balance * RISK_PCT * LEVERAGE) / entry_price
    Rounded to step_size.
    """
    balance  = get_available_balance(client)
    notional = balance * RISK_PCT * LEVERAGE
    qty      = notional / entry_price
    qty      = _round_qty(qty, filters["step_size"])
    logger.info(f"Balance={balance:.2f} USDT | Notional={notional:.2f} | Qty={qty}")
    return qty


# ─────────────────────────────────────────────
#  SET LEVERAGE
# ─────────────────────────────────────────────
def set_leverage(client):
    """Set leverage on Binance Futures for SYMBOL."""
    try:
        client.futures_change_leverage(symbol=SYMBOL, leverage=LEVERAGE)
        logger.info(f"Leverage set to {LEVERAGE}x for {SYMBOL}")
    except Exception as e:
        logger.error(f"Failed to set leverage: {e}")


# ─────────────────────────────────────────────
#  ENTRY ORDER (Maker Limit)
# ─────────────────────────────────────────────
def place_entry_order(client, direction: str, filters: dict) -> dict | None:
    """
    Place a POST-ONLY limit entry order slightly inside the spread.
    direction: 'LONG' or 'SHORT'

    Returns order dict or None on failure.
    """
    try:
        depth       = client.futures_order_book(symbol=SYMBOL, limit=5)
        best_bid    = float(depth["bids"][0][0])
        best_ask    = float(depth["asks"][0][0])
        tick_size   = filters["tick_size"]

        if direction == "LONG":
            # Buy slightly above best bid (still maker, but closer to fill)
            entry_price = _round_price(best_bid * (1 + ENTRY_OFFSET), tick_size)
            side        = SIDE_BUY
        else:
            # Sell slightly below best ask
            entry_price = _round_price(best_ask * (1 - ENTRY_OFFSET), tick_size)
            side        = SIDE_SELL

        qty = calculate_position_size(client, entry_price, filters)
        if qty <= 0:
            logger.warning("Calculated qty is 0 — skipping entry")
            return None

        order = client.futures_create_order(
            symbol        = SYMBOL,
            side          = side,
            type          = ORDER_TYPE_LIMIT,
            timeInForce   = TIME_IN_FORCE_GTX,   # Post-Only (GTX)
            quantity      = qty,
            price         = entry_price,
        )
        logger.info(f"ENTRY order placed | {direction} | Price={entry_price} | Qty={qty} | ID={order['orderId']}")
        return order

    except Exception as e:
        logger.error(f"Entry order failed: {e}")
        return None


# ─────────────────────────────────────────────
#  TAKE PROFIT ORDER (Limit — Maker)
# ─────────────────────────────────────────────
def place_take_profit_order(client, direction: str, entry_price: float,
                             qty: float, filters: dict) -> dict | None:
    """
    Place a limit take-profit order (earns maker rebate).
    direction: 'LONG' or 'SHORT'
    """
    try:
        tick_size = filters["tick_size"]

        if direction == "LONG":
            tp_price = _round_price(entry_price * (1 + TP_PCT), tick_size)
            side     = SIDE_SELL
        else:
            tp_price = _round_price(entry_price * (1 - TP_PCT), tick_size)
            side     = SIDE_BUY

        order = client.futures_create_order(
            symbol        = SYMBOL,
            side          = side,
            type          = FUTURE_ORDER_TYPE_TAKE_PROFIT,
            timeInForce   = TIME_IN_FORCE_GTC,
            quantity      = qty,
            price         = tp_price,
            stopPrice     = tp_price,
            reduceOnly    = True,
        )
        logger.info(f"TP order placed | Price={tp_price} | ID={order['orderId']}")
        return order

    except Exception as e:
        logger.error(f"TP order failed: {e}")
        return None


# ─────────────────────────────────────────────
#  STOP LOSS ORDER (Market — Safety)
# ─────────────────────────────────────────────
def place_stop_loss_order(client, direction: str, entry_price: float,
                           qty: float, filters: dict) -> dict | None:
    """
    Place a STOP_MARKET stop-loss order (always fills — safety first).
    direction: 'LONG' or 'SHORT'
    """
    try:
        tick_size = filters["tick_size"]

        if direction == "LONG":
            sl_price = _round_price(entry_price * (1 - SL_PCT), tick_size)
            side     = SIDE_SELL
        else:
            sl_price = _round_price(entry_price * (1 + SL_PCT), tick_size)
            side     = SIDE_BUY

        order = client.futures_create_order(
            symbol      = SYMBOL,
            side        = side,
            type        = FUTURE_ORDER_TYPE_STOP_MARKET,
            stopPrice   = sl_price,
            quantity    = qty,
            reduceOnly  = True,
        )
        logger.info(f"SL order placed | StopPrice={sl_price} | ID={order['orderId']}")
        return order

    except Exception as e:
        logger.error(f"SL order failed: {e}")
        return None


# ─────────────────────────────────────────────
#  CANCEL ORDER
# ─────────────────────────────────────────────
def cancel_order(client, order_id: int) -> bool:
    """Cancel a specific order by ID."""
    try:
        client.futures_cancel_order(symbol=SYMBOL, orderId=order_id)
        logger.info(f"Order {order_id} cancelled")
        return True
    except Exception as e:
        logger.error(f"Cancel failed for {order_id}: {e}")
        return False


# ─────────────────────────────────────────────
#  CHECK ORDER STATUS
# ─────────────────────────────────────────────
def get_order_status(client, order_id: int) -> str:
    """
    Returns order status string:
    NEW | PARTIALLY_FILLED | FILLED | CANCELED | EXPIRED | etc.
    """
    try:
        order = client.futures_get_order(symbol=SYMBOL, orderId=order_id)
        return order["status"]
    except Exception as e:
        logger.error(f"Get order status failed: {e}")
        return "UNKNOWN"


# ─────────────────────────────────────────────
#  CANCEL ALL OPEN ORDERS (emergency cleanup)
# ─────────────────────────────────────────────
def cancel_all_orders(client):
    """Cancel all open orders for SYMBOL. Used on shutdown or error."""
    try:
        client.futures_cancel_all_open_orders(symbol=SYMBOL)
        logger.info("All open orders cancelled")
    except Exception as e:
        logger.error(f"Cancel all orders failed: {e}")


# ─────────────────────────────────────────────
#  GET OPEN POSITION
# ─────────────────────────────────────────────
def get_open_position(client) -> dict | None:
    """
    Returns current open position for SYMBOL or None.
    dict keys: positionAmt (positive=long, negative=short), entryPrice, unrealizedProfit
    """
    try:
        positions = client.futures_position_information(symbol=SYMBOL)
        for pos in positions:
            amt = float(pos["positionAmt"])
            if amt != 0:
                return pos
        return None
    except Exception as e:
        logger.error(f"Get position failed: {e}")
        return None
