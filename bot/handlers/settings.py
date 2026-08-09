from telegram import Update
from telegram.ext import ContextTypes

from .. import config

SETTINGS_TEXT = """⚙️ Settings

Current configuration (set via environment variables):

• Max file size: {max_mb} MB
• Download timeout: {timeout}s
• Processing mode: Sequential (1 URL at a time)
• Queue storage: SQLite ({db_path}) — survives restarts

To change these, edit your .env file and restart the bot."""


async def settings_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        SETTINGS_TEXT.format(
            max_mb=config.MAX_FILE_SIZE_MB,
            timeout=config.DOWNLOAD_TIMEOUT,
            db_path=config.DB_PATH,
        )
    )
