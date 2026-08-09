from telegram import Update
from telegram.ext import ContextTypes

from ..keyboards import main_menu
from ..database import db

WELCOME_TEMPLATE = """🎉 Welcome to Advanced URL Downloader 🎉
Hello {name}! 👋

📱 How to use:
1. Send me any video/file URL
2. Or upload a .txt file containing multiple URLs
3. I'll process them automatically
4. Files will be uploaded to Telegram

🚀 Bulk Queue Supported
Send 500+ URLs and I'll process them one by one."""

HELP_TEXT = """🆘 Help

• Send any http(s) link and I'll download + upload it.
• Upload a .txt file with one URL per line (or URLs anywhere in the text) \
to queue a bulk batch — they're processed strictly one at a time, in order.
• The queue is saved to disk: if the bot restarts, it automatically \
resumes where it left off.
• If a URL fails, I skip it and keep going — you'll get a list of failed \
URLs as a .txt file at the end.

Commands:
/start – show the welcome screen
/help – this message
/stats – your usage stats (admins see global stats too)
/settings – bot settings
/queue – live queue status
/cancel – cancel all pending items in your queue"""


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await db.upsert_user(user.id, user.username or "", user.first_name or "")
    name = user.first_name or user.username or "there"
    await update.effective_message.reply_text(
        WELCOME_TEMPLATE.format(name=name),
        reply_markup=main_menu(),
    )


async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(HELP_TEXT)
