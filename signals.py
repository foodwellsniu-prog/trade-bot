"""
signals.py
──────────
Calculates 5 trading signals and returns a final direction:
  LONG | SHORT | NEUTRAL

Signals:
  1. Order Book Imbalance  (OBI)
  2. Cumulative Volume Delta (CVD)
  3. Price Velocity
  4. Funding Rate
  5. Liquidation Heatmap
"""

import time
import logging
from config import (
    OBI_LONG_THRESHOLD, OBI_SHORT_THRESHOLD, OBI_DEPTH_LEVELS,
    CVD_LOOKBACK, CVD_LONG_THRESHOLD, CVD_SHORT_THRESHOLD,
    VELOCITY_WINDOW_SEC, VELOCITY_LONG_MIN, VELOCITY_SHORT_MAX,
    FUNDING_LONG_MAX, FUNDING_SHORT_MIN,
    LIQ_LOOKBACK_SEC, LIQ_LONG_THRESHOLD, LIQ_SHORT_THRESHOLD,
    SIGNALS_REQUIRED, SYMBOL
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
#  1. ORDER BOOK IMBALANCE
# ─────────────────────────────────────────────
def signal_obi(client) -> str:
    """
    Fetch top N bid/ask levels and compute:
      OBI = bid_vol / (bid_vol + ask_vol)
    Returns: 'LONG' | 'SHORT' | 'NEUTRAL'
    """
    try:
        depth = client.futures_order_book(symbol=SYMBOL, limit=OBI_DEPTH_LEVELS * 2)

        bid_vol = sum(float(b[1]) for b in depth["bids"][:OBI_DEPTH_LEVELS])
        ask_vol = sum(float(a[1]) for a in depth["asks"][:OBI_DEPTH_LEVELS])
        total   = bid_vol + ask_vol

        if total == 0:
            return "NEUTRAL"

        obi = bid_vol / total
        logger.debug(f"OBI = {obi:.4f}")

        if obi >= OBI_LONG_THRESHOLD:
            return "LONG"
        elif obi <= OBI_SHORT_THRESHOLD:
            return "SHORT"
        return "NEUTRAL"

    except Exception as e:
        logger.error(f"OBI signal error: {e}")
        return "NEUTRAL"


# ─────────────────────────────────────────────
#  2. CUMULATIVE VOLUME DELTA (CVD)
# ─────────────────────────────────────────────
def signal_cvd(client) -> str:
    """
    Fetch last N recent trades, compute:
      CVD = buy_vol / total_vol
    Returns: 'LONG' | 'SHORT' | 'NEUTRAL'
    """
    try:
        trades = client.futures_recent_trades(symbol=SYMBOL, limit=CVD_LOOKBACK)

        buy_vol   = sum(float(t["qty"]) for t in trades if not t["isBuyerMaker"])
        total_vol = sum(float(t["qty"]) for t in trades)

        if total_vol == 0:
            return "NEUTRAL"

        cvd_ratio = buy_vol / total_vol
        logger.debug(f"CVD = {cvd_ratio:.4f}")

        if cvd_ratio >= CVD_LONG_THRESHOLD:
            return "LONG"
        elif cvd_ratio <= CVD_SHORT_THRESHOLD:
            return "SHORT"
        return "NEUTRAL"

    except Exception as e:
        logger.error(f"CVD signal error: {e}")
        return "NEUTRAL"


# ─────────────────────────────────────────────
#  3. PRICE VELOCITY
# ─────────────────────────────────────────────
# We track a small price history in memory
_price_history: list[tuple[float, float]] = []  # [(timestamp, price), ...]

def update_price_history(price: float):
    """Call this every loop iteration to maintain price history."""
    global _price_history
    now = time.time()
    _price_history.append((now, price))
    # Keep only last VELOCITY_WINDOW_SEC * 2 seconds of data
    cutoff = now - (VELOCITY_WINDOW_SEC * 2)
    _price_history = [(t, p) for t, p in _price_history if t >= cutoff]


def signal_velocity() -> str:
    """
    Compare current price vs price N seconds ago.
    velocity = (current - old) / old * 100  (percentage)
    Returns: 'LONG' | 'SHORT' | 'NEUTRAL'
    """
    try:
        now    = time.time()
        cutoff = now - VELOCITY_WINDOW_SEC

        old_prices = [(t, p) for t, p in _price_history if t <= cutoff]
        if not old_prices or not _price_history:
            return "NEUTRAL"

        old_price     = old_prices[-1][1]
        current_price = _price_history[-1][1]
        velocity_pct  = (current_price - old_price) / old_price * 100

        logger.debug(f"Price Velocity = {velocity_pct:.4f}%")

        if velocity_pct >= VELOCITY_LONG_MIN:
            return "LONG"
        elif velocity_pct <= VELOCITY_SHORT_MAX:
            return "SHORT"
        return "NEUTRAL"

    except Exception as e:
        logger.error(f"Velocity signal error: {e}")
        return "NEUTRAL"


# ─────────────────────────────────────────────
#  4. FUNDING RATE
# ─────────────────────────────────────────────
def signal_funding(client) -> str:
    """
    Fetch current funding rate.
    Low/negative funding  → market is short-biased → LONG signal (squeeze coming)
    High positive funding → market is long-biased  → SHORT signal (squeeze coming)
    Returns: 'LONG' | 'SHORT' | 'NEUTRAL'
    """
    try:
        data = client.futures_funding_rate(symbol=SYMBOL, limit=1)
        if not data:
            return "NEUTRAL"

        funding_rate = float(data[0]["fundingRate"])
        logger.debug(f"Funding Rate = {funding_rate:.6f}")

        if funding_rate <= FUNDING_LONG_MAX:
            return "LONG"
        elif funding_rate >= FUNDING_SHORT_MIN:
            return "SHORT"
        return "NEUTRAL"

    except Exception as e:
        logger.error(f"Funding Rate signal error: {e}")
        return "NEUTRAL"


# ─────────────────────────────────────────────
#  5. LIQUIDATION HEATMAP
# ─────────────────────────────────────────────
# We collect liquidation events from the websocket stream
# main.py feeds this buffer via add_liquidation()
_liq_buffer: list[dict] = []  # [{"time": ts, "side": "BUY"/"SELL", "qty": float}]


def add_liquidation(side: str, qty: float):
    """
    Called by websocket handler in main.py when a liquidation event arrives.
    side = 'BUY'  → short position was liquidated → bullish signal
    side = 'SELL' → long  position was liquidated → bearish signal
    """
    _liq_buffer.append({"time": time.time(), "side": side, "qty": qty})


def signal_liquidation() -> str:
    """
    Analyse recent liquidations:
      short_liq_vol / total_liq_vol > threshold → LONG  (shorts being wiped)
      long_liq_vol  / total_liq_vol > threshold → SHORT (longs being wiped)
    Returns: 'LONG' | 'SHORT' | 'NEUTRAL'
    """
    try:
        now    = time.time()
        cutoff = now - LIQ_LOOKBACK_SEC

        recent = [l for l in _liq_buffer if l["time"] >= cutoff]

        # Clean up old entries
        _liq_buffer[:] = recent

        if not recent:
            return "NEUTRAL"

        # BUY-side liquidation = SHORT positions were liquidated → bullish
        short_liq_vol = sum(l["qty"] for l in recent if l["side"] == "BUY")
        long_liq_vol  = sum(l["qty"] for l in recent if l["side"] == "SELL")
        total_vol     = short_liq_vol + long_liq_vol

        if total_vol == 0:
            return "NEUTRAL"

        short_ratio = short_liq_vol / total_vol
        logger.debug(f"Liquidation short_ratio = {short_ratio:.4f}")

        if short_ratio >= LIQ_LONG_THRESHOLD:
            return "LONG"
        elif short_ratio <= LIQ_SHORT_THRESHOLD:
            return "SHORT"
        return "NEUTRAL"

    except Exception as e:
        logger.error(f"Liquidation signal error: {e}")
        return "NEUTRAL"


# ─────────────────────────────────────────────
#  SIGNAL AGGREGATOR  (4 signals, 2-of-4 model)
# ─────────────────────────────────────────────
def get_trade_signal(client) -> str:
    """
    Run 4 signals and apply 2-of-4 confirmation model.
    Liquidation removed — testnet pe reliable data nahi aata.
    Returns: 'LONG' | 'SHORT' | 'NEUTRAL'
    """
    results = {
        "OBI":      signal_obi(client),
        "CVD":      signal_cvd(client),
        "VELOCITY": signal_velocity(),
        "FUNDING":  signal_funding(client),
    }

    long_count  = sum(1 for v in results.values() if v == "LONG")
    short_count = sum(1 for v in results.values() if v == "SHORT")

    logger.info(f"Signals → {results} | LONG={long_count} SHORT={short_count}")

    if long_count >= SIGNALS_REQUIRED:
        return "LONG"
    elif short_count >= SIGNALS_REQUIRED:
        return "SHORT"
    return "NEUTRAL"
