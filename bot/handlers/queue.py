from telegram import Update
from telegram.ext import ContextTypes

from ..database import db
from ..keyboards import queue_view
from ..queue_manager import build_status_text


async def queue_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    stats = await db.get_queue_stats(chat_id)

    if stats["total"] == 0:
        await update.effective_message.reply_text(
            "📋 Queue is empty.\n\nSend me a URL or a .txt file of URLs to get started."
        )
        return

    current = await db.get_current_processing(chat_id)
    current_num = stats["completed"] + stats["failed"] + 1
    url = current["url"] if current else "—"

    text = build_status_text(stats, current_num, url, stage="downloading")
    has_pending = stats["pending"] > 0 or stats["processing"] > 0
    await update.effective_message.reply_text(text, reply_markup=queue_view(has_pending))
