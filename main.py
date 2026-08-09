"""
Entry point. Wires up the Telegram Application, registers all handlers,
and — critically — resumes any queue items left pending from before a
restart/redeploy.

Run with:  python main.py
"""
import asyncio
import logging

from telegram import BotCommand
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

from bot import config
from bot.database import db
from bot.queue_manager import QueueManager
from bot.handlers.start import start_handler, help_handler
from bot.handlers.stats import stats_handler
from bot.handlers.settings import settings_handler
from bot.handlers.queue import queue_handler
from bot.handlers.cancel import cancel_handler
from bot.handlers.messages import url_message_handler, txt_file_handler
from bot.handlers.callbacks import callback_router

logger = config.setup_logging()


async def _post_init(app: Application):
    await db.connect()

    # Anything stuck 'processing' from a previous crash goes back to pending.
    reset = await db.reset_stuck_processing()
    if reset:
        logger.info("Reset %s stuck 'processing' item(s) back to pending", reset)

    qm = QueueManager(app.bot)
    app.bot_data["queue_manager"] = qm

    # Resume every chat that still has pending work.
    chats = await db.chats_with_pending()
    for chat_id in chats:
        logger.info("Resuming queue for chat %s", chat_id)
        qm.ensure_running(chat_id)

    await app.bot.set_my_commands(
        [
            BotCommand("start", "Welcome & main menu"),
            BotCommand("help", "How to use this bot"),
            BotCommand("stats", "Your usage stats"),
            BotCommand("settings", "Bot settings"),
            BotCommand("queue", "Live queue status"),
            BotCommand("cancel", "Cancel pending queue items"),
        ]
    )
    logger.info("Bot initialized and ready.")


async def _post_shutdown(app: Application):
    await db.close()


def build_app() -> Application:
    if not config.BOT_TOKEN:
        raise SystemExit(
            "BOT_TOKEN is not set. Copy .env.example to .env and fill it in."
        )

    app = (
        ApplicationBuilder()
        .token(config.BOT_TOKEN)
        .post_init(_post_init)
        .post_shutdown(_post_shutdown)
        .build()
    )

    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("help", help_handler))
    app.add_handler(CommandHandler("stats", stats_handler))
    app.add_handler(CommandHandler("settings", settings_handler))
    app.add_handler(CommandHandler("queue", queue_handler))
    app.add_handler(CommandHandler("cancel", cancel_handler))

    app.add_handler(MessageHandler(filters.Document.FileExtension("txt"), txt_file_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, url_message_handler))
    app.add_handler(CallbackQueryHandler(callback_router))

    return app


def main():
    app = build_app()
    logger.info("Starting polling...")
    app.run_polling(allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    main()
