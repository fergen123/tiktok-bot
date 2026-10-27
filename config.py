import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.environ["BOT_TOKEN"]
ADMIN_IDS = [int(x.strip()) for x in os.environ.get("ADMIN_IDS", "").split(",") if x.strip()]
DB_URL = os.getenv("DB_URL", "sqlite+aiosqlite:///data/bot.db")
POLL_INTERVAL_SEC = int(os.getenv("POLL_INTERVAL_SEC", "600"))