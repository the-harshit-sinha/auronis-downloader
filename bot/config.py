"""
Central configuration loaded from environment variables (.env supported).
"""
import os
import logging
from dotenv import load_dotenv

load_dotenv()


def _get_int_list(env_val: str):
    result = []
    for part in env_val.split(","):
        part = part.strip()
        if part.isdigit():
            result.append(int(part))
    return result


BOT_TOKEN = os.getenv("BOT_TOKEN", "")
API_ID = os.getenv("API_ID", "")
API_HASH = os.getenv("API_HASH", "")
ADMIN_IDS = _get_int_list(os.getenv("ADMIN_IDS", ""))

DOWNLOAD_DIR = os.getenv("DOWNLOAD_DIR", "downloads")
DB_PATH = os.getenv("DB_PATH", "bot_data.db")

MAX_FILE_SIZE_MB = int(os.getenv("MAX_FILE_SIZE_MB", "2000"))
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024

DOWNLOAD_TIMEOUT = int(os.getenv("DOWNLOAD_TIMEOUT", "3600"))
CHUNK_SIZE = 1024 * 1024  # 1 MB streaming chunks

# Minimum seconds between edits of the same Telegram status message,
# to stay well clear of Telegram's flood limits.
STATUS_EDIT_INTERVAL = 4

os.makedirs(DOWNLOAD_DIR, exist_ok=True)


def setup_logging():
    logging.basicConfig(
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        level=logging.INFO,
    )
    # Quiet down noisy third-party loggers
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("yt_dlp").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)
    return logging.getLogger("url_bot")
