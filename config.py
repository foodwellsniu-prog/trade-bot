import os

# ─────────────────────────────────────────────
#  ENVIRONMENT TOGGLE
# ─────────────────────────────────────────────
USE_TESTNET = os.getenv("USE_TESTNET", "true").lower() == "true"

# ─────────────────────────────────────────────
#  BINANCE API CREDENTIALS (from Render env vars)
# ─────────────────────────────────────────────
BINANCE_API_KEY    = os.getenv("BINANCE_API_KEY", "")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "")

BINANCE_BASE_URL = (
    "https://testnet.binancefuture.com"
    if USE_TESTNET
    else "https://fapi.binance.com"
)

# ─────────────────────────────────────────────
#  TELEGRAM
# ─────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")

# ─────────────────────────────────────────────
#  TRADING PARAMETERS
# ─────────────────────────────────────────────
SYMBOL        = "ETHUSDT"
LEVERAGE      = 5
RISK_PCT      = 0.90          # 90% of available balance per trade (TESTNET ONLY)

# Take Profit & Stop Loss (as % move from entry)
TP_PCT        = 0.004         # 0.4%  — limit order (maker rebate)
SL_PCT        = 0.003         # 0.3%  — market order (safety)

# Limit order offset from best bid/ask (to ensure maker fill)
ENTRY_OFFSET  = 0.0001        # 0.01% inside spread

# ─────────────────────────────────────────────
#  SIGNAL THRESHOLDS
# ─────────────────────────────────────────────

# Order Book Imbalance  (bid_vol / (bid_vol + ask_vol))
OBI_LONG_THRESHOLD  = 0.60    # >60% bids  → bullish
OBI_SHORT_THRESHOLD = 0.40    # <40% bids  → bearish
OBI_DEPTH_LEVELS    = 10      # top N levels to consider

# Cumulative Volume Delta (CVD)
CVD_LOOKBACK        = 50      # last N trades
CVD_LONG_THRESHOLD  = 0.60    # buy volume > 60% → bullish
CVD_SHORT_THRESHOLD = 0.40

# Price Velocity  (% move over last N seconds)
VELOCITY_WINDOW_SEC = 10
VELOCITY_LONG_MIN   =  0.05   # +0.05% → bullish
VELOCITY_SHORT_MAX  = -0.05   # -0.05% → bearish

# Funding Rate  (hourly %)
FUNDING_LONG_MAX    = 0.01    # low/negative funding → ok to go long
FUNDING_SHORT_MIN   = -0.01   # high negative funding → ok to go short

# Liquidation Heatmap
LIQ_LOOKBACK_SEC    = 60      # scan last 60s of liquidation data
LIQ_LONG_THRESHOLD  = 0.60    # >60% liq volume was SHORTS → bullish pressure
LIQ_SHORT_THRESHOLD = 0.40

# ─────────────────────────────────────────────
#  SIGNAL CONFIRMATION MODEL
# ─────────────────────────────────────────────
SIGNALS_REQUIRED    = 3       # at least 3-of-5 signals must agree

# ─────────────────────────────────────────────
#  BOT LOOP SETTINGS
# ─────────────────────────────────────────────
LOOP_INTERVAL_SEC   = 5       # how often the bot checks signals
ORDER_TIMEOUT_SEC   = 30      # cancel unfilled limit entry after N seconds
MAX_OPEN_TRADES     = 1       # only 1 trade at a time

# ─────────────────────────────────────────────
#  KEEP-ALIVE  (for Render + UptimeRobot)
# ─────────────────────────────────────────────
KEEP_ALIVE_PORT     = int(os.getenv("PORT", 8080))
