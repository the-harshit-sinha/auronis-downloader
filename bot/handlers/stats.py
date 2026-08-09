from telegram import Update
from telegram.ext import ContextTypes

from ..database import db
from ..config import ADMIN_IDS


async def stats_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = update.effective_user
    s = await db.get_queue_stats(chat_id)

    text = (
        "📊 Your Stats\n\n"
        f"Total queued: {s['total']}\n"
        f"✅ Completed: {s['completed']}\n"
        f"❌ Failed: {s['failed']}\n"
        f"⏳ Pending: {s['pending']}\n"
        f"🔄 Processing: {s['processing']}\n"
    )

    if user.id in ADMIN_IDS:
        g = await db.global_stats()
        text += (
            "\n👑 Global (Admin)\n\n"
            f"Users: {g['users']}\n"
            f"Total items ever queued: {g['total']}\n"
            f"✅ Completed: {g['completed']}\n"
            f"❌ Failed: {g['failed']}\n"
            f"⏳ Pending: {g['pending']}\n"
            f"🔄 Processing: {g['processing']}\n"
        )

    await update.effective_message.reply_text(text)
