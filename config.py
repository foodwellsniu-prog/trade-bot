import os

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  MODE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MODE    = os.environ.get("MODE", "TESTNET")
IS_TEST = MODE == "TESTNET"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  API KEYS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
API_KEY    = os.environ.get("API_KEY", "")
API_SECRET = os.environ.get("API_SECRET", "")
BOT_TOKEN  = os.environ.get("BOT_TOKEN", "")
CHAT_ID    = os.environ.get("CHAT_ID", "")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  URLs
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
if IS_TEST:
    BASE_URL = "https://testnet.binancefuture.com"
    WS_BASE  = "wss://stream.binancefuture.com/ws"
else:
    BASE_URL = "https://fapi.binance.com"
    WS_BASE  = "wss://fstream.binance.com/ws"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  TRADING
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SYMBOL      = "ETHUSDT"
SYMBOL_WS   = "ethusdt"
CAPITAL     = 10000.0
CAPITAL_PCT = 90
LEVERAGE    = 10
TP_PCT      = 0.12
SL_PCT      = 0.08
MAX_HOLD    = 840      # 14 min = 840 sec

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  FEES
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MAKER_FEE = 0.0002
TAKER_FEE = 0.0005

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  SIGNALS - LOOSE (Zyada trades)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OB_LEVELS     = 10
OB_IMBALANCE  = 1.2   # Loose
FLOW_PCT      = 55    # Loose
VEL_THRESHOLD = 0.005 # Loose
MAX_SPREAD    = 0.10  # Loose

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  COOLDOWN
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
COOLDOWN_WIN  = 5
COOLDOWN_LOSS = 10

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  UPDATE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
UPDATE_MIN = 30

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  FILES
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CAP_FILE  = "capital_eth.txt"
HIST_FILE = "history_eth.json"
