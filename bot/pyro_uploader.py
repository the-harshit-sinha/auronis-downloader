"""
Pyrogram/MTProto-based uploader.

The standard Bot HTTP API caps uploads at 50MB no matter what. Telegram's
underlying MTProto protocol has no such limit for bots — up to 2GB per file
(4GB for chats owned by Premium accounts) — which is how most "big file"
bots actually work, without needing a self-hosted local Bot API server.

This module runs a second, parallel connection to Telegram using the same
BOT_TOKEN but talking MTProto directly via Pyrogram. It is entirely optional:
if API_ID/API_HASH are not configured, `is_available()` returns False and
queue_manager falls back to the normal 50MB-limited HTTP path.
"""
import logging
import time

from . import config

logger = logging.getLogger("url_bot.pyro")

_client = None  # lazily created pyrogram.Client
_start_lock = None


def is_configured() -> bool:
    return bool(config.API_ID and config.API_HASH and str(config.API_ID).isdigit())


def is_available() -> bool:
    return _client is not None and getattr(_client, "is_connected", False)


async def start():
    """Create and connect the Pyrogram client. Safe to call once at startup."""
    global _client
    if not is_configured():
        logger.info("API_ID/API_HASH not set — large file (>50MB) uploads via "
                     "MTProto are disabled; falling back to the 50MB HTTP limit.")
        return

    try:
        from pyrogram import Client
    except ImportError:
        logger.warning("pyrogram is not installed — run `pip install pyrogram tgcrypto` "
                        "to enable >50MB uploads. Falling back to the 50MB HTTP limit.")
        return

    if _client is not None:
        return

    _client = Client(
        name="url_bot_uploader",
        api_id=int(config.API_ID),
        api_hash=config.API_HASH,
        bot_token=config.BOT_TOKEN,
        workdir=config.DOWNLOAD_DIR,
        in_memory=True,  # don't leave a .session file lying around
    )
    try:
        await _client.start()
        logger.info("Pyrogram MTProto client connected — large file (>50MB) uploads enabled.")
    except Exception:
        logger.exception("Failed to start Pyrogram client — falling back to the 50MB HTTP limit.")
        _client = None


async def stop():
    global _client
    if _client is not None:
        try:
            await _client.stop()
        except Exception:
            logger.exception("Error stopping Pyrogram client")
        _client = None


class _ProgressThrottle:
    """Wraps Pyrogram's (current, total) progress callback and forwards it into
    the same `progress` dict the yt-dlp downloader uses, throttled so we don't
    spam edits faster than STATUS_EDIT_INTERVAL."""

    def __init__(self, progress: dict, filename: str):
        self.progress = progress
        self.filename = filename
        self._last = 0.0
        self._last_bytes = 0
        self._t0 = time.time()

    def __call__(self, current: int, total: int):
        now = time.time()
        elapsed = now - self._last
        if elapsed < config.STATUS_EDIT_INTERVAL and current != total:
            return
        dt = now - (self._last or self._t0)
        speed = (current - self._last_bytes) / dt if dt > 0 else 0
        eta = (total - current) / speed if speed > 0 else None

        self.progress.update({
            "stage": "uploading",
            "downloaded": current,
            "total": total,
            "speed": speed,
            "eta": eta,
            "filename": self.filename,
        })
        self._last = now
        self._last_bytes = current


async def upload(chat_id: int, filepath: str, filename: str, caption: str,
                  kind: str, progress: dict = None):
    """
    Upload a file via MTProto. `kind` is one of "video", "audio", "document".
    Raises RuntimeError if the Pyrogram client isn't available — caller should
    have checked is_available() first.
    """
    if not is_available():
        raise RuntimeError("Pyrogram client is not available")

    cb = _ProgressThrottle(progress, filename) if progress is not None else None

    kwargs = dict(
        chat_id=chat_id,
        caption=caption,
        file_name=filename,
        progress=cb,
    )

    if kind == "video":
        await _client.send_video(video=filepath, supports_streaming=True, **kwargs)
    elif kind == "audio":
        await _client.send_audio(audio=filepath, **kwargs)
    else:
        await _client.send_document(document=filepath, **kwargs)
