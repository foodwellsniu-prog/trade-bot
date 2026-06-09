import os
from dotenv import load_dotenv

load_dotenv()

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  MODE
#  TESTNET = Demo trading (safe)
#  REAL    = Real money trading
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MODE    = os.getenv("MODE", "TESTNET")
IS_TEST = MODE == "TESTNET"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  API KEYS
#  Render Environment Variables se aayega
#  Yahan kuch mat likho
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
API_KEY    = os.getenv("API_KEY", "H647cSQelN9Im9o22wTu3h3oz3ZTBgxSzV5McQzN7qJoWg94lPGmR6JaCawbmS5S")
API_SECRET = os.getenv("API_SECRET", "O2Gz79sooHsYAzd2oyJQ2rmE8KwhhF5JCs9KlwHwFToTitszOaLMRDFYCobz6gSW")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  TELEGRAM
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BOT_TOKEN = os.getenv("BOT_TOKEN", "8161773850:AAFcWw3UnlSe2TrMooB2uvgZQZUqIW0zW2w")
CHAT_ID   = os.getenv("CHAT_ID", "7102976298")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  TRADING SETTINGS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SYMBOL       = "ETH/USDT"
SYMBOL_WS    = "ethusdt"
LEVERAGE     = 5
CAPITAL_PCT  = 90       # 90% per trade
TP_PCT       = 0.05     # 0.05% Take Profit
SL_PCT       = 0.03     # 0.03% Stop Loss
MAX_HOLD_SEC = 10       # Max 10 second hold
ENTRY_WAIT   = 3        # 3 sec limit order wait

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  FEE SETTINGS
#  Binance Futures:
#  Maker = -0.02% (rebate milta hai)
#  Taker = +0.05% (fee deni padti hai)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MAKER_FEE = -0.0002   # -0.02% rebate
TAKER_FEE =  0.0005   # +0.05% cost

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  SIGNAL THRESHOLDS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Order Book Imbalance
# Bid/Ask ratio kitna hona chahiye
OB_THRESHOLD  = 1.5     # 1.5x imbalance

# Trade Flow
# Kitne % buy ya sell pressure chahiye
FLOW_PCT      = 60      # 60% pressure

# Price Velocity
# Kitni tezi se price move kare
VEL_THRESHOLD = 0.003   # 0.003% per 2 sec

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  RISK MANAGEMENT
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Daily loss limit (% of capital)
MAX_DAILY_LOSS_PCT = 5    # 5% daily loss max

# Consecutive losses
MAX_CONSEC_LOSS    = 5    # 5 loss in a row

# Daily trade limit
MAX_DAILY_TRADES   = 500  # Max 500 trades/day

# Drawdown limit
DRAWDOWN_PAUSE     = 10   # 10% drawdown = pause

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  BINANCE URLs
#  Auto set hoga MODE ke hisab se
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
if IS_TEST:
    # Testnet URLs
    BASE_URL = "https://testnet.binancefuture.com"
    WS_BASE  = "wss://stream.binancefuture.com/ws"
    print("=" * 40)
    print("  MODE: TESTNET (DEMO)")
    print("  Fake money - Safe!")
    print("=" * 40)
else:
    # Real Binance URLs
    BASE_URL = "https://fapi.binance.com"
    WS_BASE  = "wss://fstream.binance.com/ws"
    print("=" * 40)
    print("  MODE: REAL TRADING")
    print("  REAL MONEY!")
    print("=" * 40)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  FILES
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CAP_FILE  = "capital.txt"
HIST_FILE = "history.json"
LOG_FILE  = "bot.log"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  UPDATE INTERVAL
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
UPDATE_MIN = 30   # Har 30 min status update
