from telegram import Update
from telegram.ext import ContextTypes

from ..database import db
from ..keyboards import confirm_cancel


async def cancel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    stats = await db.get_queue_stats(chat_id)
    if stats["pending"] == 0:
        await update.effective_message.reply_text("Nothing to cancel — no pending items in your queue.")
        return
    await update.effective_message.reply_text(
        f"🛑 Cancel {stats['pending']} pending item(s)? The item currently "
        f"downloading/uploading will still finish.",
        reply_markup=confirm_cancel(),
    )
