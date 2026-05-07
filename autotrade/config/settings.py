import os
from dotenv import load_dotenv

load_dotenv()

# 운용 모드
DRY_RUN = os.getenv("DRY_RUN", "True").lower() == "true"
MAX_POSITION_RATIO = float(os.getenv("MAX_POSITION_RATIO", "0.5"))
DAILY_LOSS_LIMIT = float(os.getenv("DAILY_LOSS_LIMIT", "-0.03"))
MAX_SLOTS = int(os.getenv("MAX_SLOTS", "5"))

# 증권사 API
KIS_APP_KEY = os.getenv("KIS_APP_KEY", "")
KIS_APP_SECRET = os.getenv("KIS_APP_SECRET", "")
KIS_ACCOUNT_NO = os.getenv("KIS_ACCOUNT_NO", "")
KIS_MODE = os.getenv("KIS_MODE", "paper")

# 데이터 API
DART_API_KEY = os.getenv("DART_API_KEY", "")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")

# AI
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
AI_ANALYSIS_MODEL = os.getenv("AI_ANALYSIS_MODEL", "claude-haiku-4-5-20251001")
AI_MONTHLY_MODEL = os.getenv("AI_MONTHLY_MODEL", "claude-sonnet-4-6")

# 텔레그램
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# DB
DB_PATH = os.getenv("DB_PATH", "./data/trading.db")
