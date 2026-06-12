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
TP_PCT        = 0.002         # 0.2%  — limit order (maker rebate) — 5 min mein easily milta hai
SL_PCT        = 0.0015        # 0.15% — market order (safety)

# Limit order offset from best bid/ask (to ensure maker fill)
ENTRY_OFFSET  = 0.0001        # 0.01% inside spread

# ─────────────────────────────────────────────
#  SIGNAL THRESHOLDS
# ─────────────────────────────────────────────

# Order Book Imbalance  (bid_vol / (bid_vol + ask_vol))
OBI_LONG_THRESHOLD  = 0.52    # >55% bids  → bullish (loosened from 60%)
OBI_SHORT_THRESHOLD = 0.48    # <45% bids  → bearish
OBI_DEPTH_LEVELS    = 10      # top N levels to consider

# Cumulative Volume Delta (CVD)
CVD_LOOKBACK        = 50      # last N trades
CVD_LONG_THRESHOLD  = 0.52    # buy volume > 55% → bullish (loosened from 60%)
CVD_SHORT_THRESHOLD = 0.48

# Price Velocity  (% move over last N seconds)
VELOCITY_WINDOW_SEC = 10
VELOCITY_LONG_MIN   =  0.01   # +0.02% → bullish (loosened from 0.05%)
VELOCITY_SHORT_MAX  = -0.01   # -0.02% → bearish

# Funding Rate  (hourly %)
FUNDING_LONG_MAX    = 0.01    # low/negative funding → ok to go long
FUNDING_SHORT_MIN   = -0.01   # high negative funding → ok to go short

# NOTE: Liquidation signal REMOVED — testnet pe kaam nahi karta
# Sirf 4 signals use ho rahe hain ab: OBI, CVD, Velocity, Funding

# ─────────────────────────────────────────────
#  SIGNAL CONFIRMATION MODEL
# ─────────────────────────────────────────────
SIGNALS_REQUIRED    = 2       # 2-of-4 signals agree → trade lo

# ─────────────────────────────────────────────
#  BOT LOOP SETTINGS
# ─────────────────────────────────────────────
LOOP_INTERVAL_SEC   = 3       # har 3 seconds check karo
ORDER_TIMEOUT_SEC   = 120     # limit entry ko 2 min do fill hone ke liye
MAX_OPEN_TRADES     = 1       # ek waqt mein sirf 1 trade

# ─────────────────────────────────────────────
#  KEEP-ALIVE  (for Render + UptimeRobot)
# ─────────────────────────────────────────────
KEEP_ALIVE_PORT     = int(os.getenv("PORT", 8080))
