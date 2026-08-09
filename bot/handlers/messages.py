"""
Handlers for the two primary inputs:
  - a plain text message containing a single URL
  - an uploaded .txt file containing many URLs
"""
import logging

from telegram import Update
from telegram.ext import ContextTypes

from ..database import db
from ..utils import is_valid_url, extract_urls
from ..config import DOWNLOAD_DIR

logger = logging.getLogger("url_bot.messages")

MAX_TXT_SIZE_BYTES = 5 * 1024 * 1024  # 5MB is plenty for a URL list


async def url_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.effective_message.text or "").strip()
    chat_id = update.effective_chat.id
    user = update.effective_user
    await db.upsert_user(user.id, user.username or "", user.first_name or "")

    urls = extract_urls(text)
    if not urls:
        if not is_valid_url(text):
            await update.effective_message.reply_text(
                "⚠️ That doesn't look like a valid http(s) URL. Send a direct "
                "link, or upload a .txt file with multiple URLs."
            )
            return
        urls = [text]

    qm = context.bot_data["queue_manager"]
    added, _ = await qm.enqueue(chat_id, user.id, urls)

    if added == 0:
        await update.effective_message.reply_text("ℹ️ That URL is already in the queue.")
        return

    stats = await db.get_queue_stats(chat_id)
    await update.effective_message.reply_text(
        f"✅ Added to queue.\n\n📋 Total in queue: {stats['total']} "
        f"(⏳ {stats['pending']} pending)"
    )


async def txt_file_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.effective_message.document
    chat_id = update.effective_chat.id
    user = update.effective_user
    await db.upsert_user(user.id, user.username or "", user.first_name or "")

    if not doc.file_name.lower().endswith(".txt"):
        await update.effective_message.reply_text("⚠️ Please upload a .txt file.")
        return

    if doc.file_size and doc.file_size > MAX_TXT_SIZE_BYTES:
        await update.effective_message.reply_text("⚠️ That .txt file is too large.")
        return

    tg_file = await doc.get_file()
    raw = await tg_file.download_as_bytearray()
    try:
        text = raw.decode("utf-8", errors="ignore")
    except Exception:
        await update.effective_message.reply_text("⚠️ Couldn't read that file as text.")
        return

    urls = extract_urls(text)
    if not urls:
        await update.effective_message.reply_text("⚠️ No valid URLs found in that file.")
        return

    qm = context.bot_data["queue_manager"]
    added, batch_id = await qm.enqueue(chat_id, user.id, urls)
    skipped = len(urls) - added

    stats = await db.get_queue_stats(chat_id)
    msg = (
        f"✅ Batch queued (#{batch_id})\n\n"
        f"📄 Found: {len(urls)} URL(s)\n"
        f"➕ Added: {added}\n"
    )
    if skipped:
        msg += f"⏭️ Skipped (already queued): {skipped}\n"
    msg += f"\n📋 Total in queue: {stats['total']} (⏳ {stats['pending']} pending)"
    await update.effective_message.reply_text(msg)
