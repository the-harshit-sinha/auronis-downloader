"""
Minimal Flask web server that keeps the bot's Render/Replit-style host
service alive: it binds to $PORT and answers health checks, while the
actual Telegram polling loop runs in the main thread untouched.

Render (and similar hosts) expect a web service to bind a port; without
this, a "web" service type gets marked unhealthy/killed even though the
bot itself is working fine via long polling.
"""
import os
import logging
from threading import Thread

from flask import Flask

logger = logging.getLogger("url_bot.keepalive")
app = Flask("keep_alive")


@app.route("/")
def home():
    return "✅ Telegram URL Downloader Bot is alive and running!"


@app.route("/health")
def health():
    return {"status": "ok"}, 200


def _run():
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port)


def keep_alive():
    """Start the Flask server in a background thread. Call once at startup."""
    t = Thread(target=_run, daemon=True)
    t.start()
    logger.info("Keep-alive web server started on port %s", os.getenv("PORT", 8080))
