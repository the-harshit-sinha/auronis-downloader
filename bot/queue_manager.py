"""
The heart of the bot: a strictly sequential, per-chat download → upload →
cleanup pipeline, backed by the SQLite queue in database.py.

Only one URL is ever "in flight" per chat at a time. Multiple chats can run
independently (each has its own asyncio.Task), but a single chat's 500 URLs
are always processed one after another, never in parallel.
"""
import os
import time
import uuid
import logging
import asyncio

from telegram import InputFile
from telegram.error import TelegramError

from . import config
from .database import db
from .downloader import download_url, DownloadError
from .utils import format_bytes, format_eta, progress_bar
from .keyboards import queue_view

logger = logging.getLogger("url_bot.queue")

VIDEO_EXT = (".mp4", ".mkv", ".webm", ".mov", ".avi", ".flv", ".m3u8", ".ts")
AUDIO_EXT = (".mp3", ".m4a", ".wav", ".flac", ".ogg", ".aac")


class QueueManager:
    def __init__(self, bot):
        self.bot = bot
        self._tasks: dict[int, asyncio.Task] = {}
        self._cancel_flags: dict[int, bool] = {}
        self._msg_cache: dict[int, dict] = {}  # chat_id -> {"text": str, "ts": float}

    # ------------------------------------------------------------- public
    def is_running(self, chat_id: int) -> bool:
        t = self._tasks.get(chat_id)
        return t is not None and not t.done()

    async def enqueue(self, chat_id: int, user_id: int, urls: list[str]) -> tuple[int, str]:
        """Add URLs to a chat's persistent queue and (re)start its worker if idle."""
        batch_id = uuid.uuid4().hex[:12]
        # skip exact duplicates already pending/processing in this chat
        fresh = []
        for u in urls:
            if not await db.url_already_queued(chat_id, u):
                fresh.append(u)
        if fresh:
            await db.add_urls(chat_id, user_id, fresh, batch_id)
        self.ensure_running(chat_id)
        return len(fresh), batch_id

    def ensure_running(self, chat_id: int):
        if not self.is_running(chat_id):
            self._cancel_flags[chat_id] = False
            self._tasks[chat_id] = asyncio.create_task(self._process_chat(chat_id))

    async def cancel(self, chat_id: int) -> int:
        n = await db.cancel_pending(chat_id)
        self._cancel_flags[chat_id] = True
        return n

    # ------------------------------------------------------------ workers
    async def _process_chat(self, chat_id: int):
        session_start = time.time()
        processed_any = False
        try:
            while True:
                item = await db.get_next_pending(chat_id)
                if item is None:
                    break
                processed_any = True
                await self._process_one(chat_id, item)
        except Exception:
            logger.exception("Unhandled error in queue loop for chat %s", chat_id)
        finally:
            if processed_any:
                await self._send_final_summary(chat_id, session_start)
            self._cancel_flags[chat_id] = False

    async def _process_one(self, chat_id: int, item):
        item_id = item["id"]
        url = item["url"]
        await db.mark_processing(item_id)
        stats = await db.get_queue_stats(chat_id)
        current_num = stats["completed"] + stats["failed"] + 1

        await self._update_status(
            chat_id,
            stats=stats,
            current_num=current_num,
            url=url,
            stage="downloading",
        )

        outdir = os.path.join(config.DOWNLOAD_DIR, str(chat_id))
        os.makedirs(outdir, exist_ok=True)
        progress = {"stage": "starting", "downloaded": 0, "total": 0, "speed": 0, "eta": None, "filename": None}

        ticker_task = asyncio.create_task(
            self._progress_ticker(chat_id, stats, current_num, url, progress)
        )

        filepath = None
        try:
            filepath, progress = await download_url(url, outdir, progress)

            size = os.path.getsize(filepath)
            if size > config.MAX_FILE_SIZE_BYTES:
                raise DownloadError(
                    f"File too large ({format_bytes(size)} > {config.MAX_FILE_SIZE_MB}MB limit)"
                )

            await self._update_status(
                chat_id, stats=stats, current_num=current_num, url=url,
                stage="uploading", filename=os.path.basename(filepath),
            )
            await self._upload(chat_id, filepath)
            await db.mark_completed(item_id, os.path.basename(filepath))

        except Exception as e:
            err = str(e) or e.__class__.__name__
            logger.warning("Item #%s failed (%s): %s", item_id, url, err)
            await db.mark_failed(item_id, err)
            await self._send_transient(
                chat_id,
                f"❌ #{current_num} Failed\n"
                f"🔗 {url}\n"
                f"⚠️ {err[:200]}\n\n"
                f"➡️ Skipping to #{current_num + 1}...",
            )
        finally:
            ticker_task.cancel()
            if filepath and os.path.exists(filepath):
                try:
                    os.remove(filepath)
                except OSError:
                    pass

    async def _progress_ticker(self, chat_id, stats, current_num, url, progress: dict):
        try:
            while True:
                await asyncio.sleep(config.STATUS_EDIT_INTERVAL)
                if progress.get("stage") in ("done", "error"):
                    return
                await self._update_status(
                    chat_id, stats=stats, current_num=current_num, url=url,
                    stage="downloading", progress=progress,
                )
        except asyncio.CancelledError:
            return

    # -------------------------------------------------------------- I/O
    async def _upload(self, chat_id: int, filepath: str):
        name = os.path.basename(filepath)
        ext = os.path.splitext(name)[1].lower()
        caption = f"📁 {name}"

        with open(filepath, "rb") as f:
            input_file = InputFile(f, filename=name)
            try:
                if ext in VIDEO_EXT:
                    await self.bot.send_video(
                        chat_id, video=input_file, caption=caption,
                        supports_streaming=True, write_timeout=config.DOWNLOAD_TIMEOUT,
                        read_timeout=config.DOWNLOAD_TIMEOUT,
                    )
                elif ext in AUDIO_EXT:
                    await self.bot.send_audio(
                        chat_id, audio=input_file, caption=caption,
                        write_timeout=config.DOWNLOAD_TIMEOUT, read_timeout=config.DOWNLOAD_TIMEOUT,
                    )
                else:
                    await self.bot.send_document(
                        chat_id, document=input_file, caption=caption,
                        write_timeout=config.DOWNLOAD_TIMEOUT, read_timeout=config.DOWNLOAD_TIMEOUT,
                    )
            except TelegramError as e:
                raise DownloadError(f"Telegram upload error: {e}")

    async def _send_transient(self, chat_id: int, text: str):
        try:
            await self.bot.send_message(chat_id, text)
        except TelegramError:
            logger.exception("Failed to send transient message to %s", chat_id)

    async def _send_final_summary(self, chat_id: int, session_start: float):
        # items completed/failed *in this run*
        session = await db.get_session_stats(chat_id, session_start)
        total = session["completed"] + session["failed"]
        if total == 0:
            return

        text = (
            "✅ Queue Completed\n\n"
            f"📊 Total: {total}\n"
            f"✅ Successful: {session['completed']}\n"
            f"❌ Failed: {session['failed']}"
        )
        await self._send_transient(chat_id, text)

        if session["failed"] > 0:
            failed_urls = await db.get_session_failed_urls(chat_id, session_start)
            fname = os.path.join(config.DOWNLOAD_DIR, f"failed_{chat_id}_{int(time.time())}.txt")
            with open(fname, "w", encoding="utf-8") as f:
                f.write("\n".join(failed_urls))
            try:
                with open(fname, "rb") as f:
                    await self.bot.send_document(
                        chat_id, document=InputFile(f, filename="failed_urls.txt"),
                        caption="⚠️ URLs that failed to download",
                    )
            except TelegramError:
                logger.exception("Failed to send failed-urls file to %s", chat_id)
            finally:
                if os.path.exists(fname):
                    os.remove(fname)

    # ---------------------------------------------------------- status UI
    async def _update_status(self, chat_id, stats, current_num, url, stage="downloading",
                              progress: dict = None, filename: str = None):
        text = build_status_text(stats, current_num, url, stage=stage, progress=progress, filename=filename)
        await self._edit_or_send_status(chat_id, text)

    async def _edit_or_send_status(self, chat_id: int, text: str):
        cache = self._msg_cache.get(chat_id, {})
        if cache.get("text") == text and time.time() - cache.get("ts", 0) < 60:
            return  # nothing changed, avoid useless API call
        self._msg_cache[chat_id] = {"text": text, "ts": time.time()}

        msg_id = await db.get_status_message(chat_id)
        try:
            if msg_id:
                await self.bot.edit_message_text(
                    chat_id=chat_id, message_id=msg_id, text=text,
                    reply_markup=queue_view(True),
                )
                return
        except TelegramError as e:
            if "not modified" in str(e).lower():
                return
            # message deleted / too old — fall through and send a new one
        try:
            msg = await self.bot.send_message(chat_id, text, reply_markup=queue_view(True))
            await db.set_status_message(chat_id, msg.message_id)
        except TelegramError:
            logger.exception("Could not send status message to %s", chat_id)


def build_status_text(stats, current_num, url, stage="downloading", progress: dict = None,
                       filename: str = None) -> str:
    lines = [
        "📋 Queue Status",
        "",
        f"Total: {stats['total']}",
        f"Completed: {stats['completed']}",
        f"Failed: {stats['failed']}",
        f"Remaining: {stats['pending'] + (1 if stats['processing'] else 0)}",
        "",
    ]
    if stage == "uploading":
        lines.append(f"📤 Uploading: #{current_num}")
        if filename:
            lines.append(f"📁 {filename}")
    else:
        lines.append(f"📥 Processing: #{current_num}")

    lines.append(f"🔗 URL: {url[:70]}{'…' if len(url) > 70 else ''}")

    if progress and progress.get("total"):
        done, total = progress["downloaded"], progress["total"]
        pct = (done / total * 100) if total else 0
        lines += [
            "",
            f"{progress_bar(done, total)} {pct:.1f}%",
            f"{format_bytes(done)} / {format_bytes(total)}"
            f"  •  {format_bytes(progress.get('speed') or 0)}/s"
            f"  •  ETA {format_eta(progress.get('eta'))}",
        ]
    return "\n".join(lines)
