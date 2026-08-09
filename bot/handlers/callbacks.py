"""
Inline button callbacks — routes menu:*, queue:*, cancel:* callback_data.
"""
from telegram import Update
from telegram.ext import ContextTypes

from ..database import db
from ..keyboards import queue_view, main_menu
from ..queue_manager import build_status_text
from .start import WELCOME_TEMPLATE, HELP_TEXT
from .settings import SETTINGS_TEXT
from .. import config


async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data or ""
    chat_id = update.effective_chat.id
    await query.answer()

    if data == "menu:download":
        await query.message.reply_text("📥 Just send me a URL, or upload a .txt file with many URLs.")

    elif data == "menu:help":
        await query.message.reply_text(HELP_TEXT)

    elif data == "menu:settings":
        await query.message.reply_text(
            SETTINGS_TEXT.format(
                max_mb=config.MAX_FILE_SIZE_MB,
                timeout=config.DOWNLOAD_TIMEOUT,
                db_path=config.DB_PATH,
            )
        )

    elif data in ("menu:stats",):
        from .stats import stats_handler
        await stats_handler(update, context)

    elif data in ("menu:queue", "queue:refresh"):
        stats = await db.get_queue_stats(chat_id)
        if stats["total"] == 0:
            await query.message.reply_text("📋 Queue is empty.")
            return
        current = await db.get_current_processing(chat_id)
        current_num = stats["completed"] + stats["failed"] + 1
        url = current["url"] if current else "—"
        text = build_status_text(stats, current_num, url, stage="downloading")
        has_pending = stats["pending"] > 0 or stats["processing"] > 0
        try:
            await query.edit_message_text(text, reply_markup=queue_view(has_pending))
        except Exception:
            await query.message.reply_text(text, reply_markup=queue_view(has_pending))

    elif data == "queue:cancel":
        from ..keyboards import confirm_cancel
        stats = await db.get_queue_stats(chat_id)
        if stats["pending"] == 0:
            await query.message.reply_text("Nothing to cancel.")
            return
        await query.message.reply_text(
            f"🛑 Cancel {stats['pending']} pending item(s)?",
            reply_markup=confirm_cancel(),
        )

    elif data == "cancel:confirm":
        qm = context.bot_data["queue_manager"]
        n = await qm.cancel(chat_id)
        await query.message.reply_text(f"🛑 Cancelled {n} pending item(s).")

    elif data == "cancel:abort":
        await query.message.reply_text("👍 Kept the queue running.")
