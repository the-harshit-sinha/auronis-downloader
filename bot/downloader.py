"""
Download engine.

Strategy for every URL:
  1. Try yt-dlp first (covers YouTube and hundreds of other sites, plus
     native M3U8/HLS handling).
  2. If yt-dlp says the URL is unsupported (generic extractor / extraction
     error), fall back to a plain streaming HTTP download with aiohttp.

Both paths report progress into a shared mutable dict so the caller can
poll it from an async ticker without needing thread-safe callbacks.
"""
import os
import time
import asyncio
import logging
import mimetypes
from urllib.parse import urlparse, unquote

import aiohttp
import aiofiles
import yt_dlp

from . import config
from .utils import safe_filename

logger = logging.getLogger("url_bot.downloader")


class DownloadError(Exception):
    pass


def _new_progress() -> dict:
    return {
        "stage": "starting",       # starting / downloading / done / error
        "downloaded": 0,
        "total": 0,
        "speed": 0,
        "eta": None,
        "filename": None,
    }


async def _download_with_ytdlp(url: str, outdir: str, progress: dict) -> str:
    loop = asyncio.get_event_loop()

    def hook(d):
        progress["stage"] = "downloading" if d.get("status") == "downloading" else d.get("status", "downloading")
        progress["downloaded"] = d.get("downloaded_bytes", 0) or 0
        progress["total"] = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
        progress["speed"] = d.get("speed") or 0
        progress["eta"] = d.get("eta")
        fn = d.get("filename")
        if fn:
            progress["filename"] = os.path.basename(fn)

    ydl_opts = {
        "outtmpl": os.path.join(outdir, "%(title).100s-%(id)s.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "progress_hooks": [hook],
        "merge_output_format": "mp4",
        "socket_timeout": 30,
        "retries": 3,
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
    }

    def run():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if info is None:
                raise DownloadError("yt-dlp returned no info")
            # playlists shouldn't happen (noplaylist=True) but guard anyway
            if "entries" in info:
                info = info["entries"][0]
            path = ydl.prepare_filename(info)
            # merge_output_format may change the extension after postprocessing
            if not os.path.exists(path):
                base, _ = os.path.splitext(path)
                for ext in (".mp4", ".mkv", ".webm"):
                    if os.path.exists(base + ext):
                        path = base + ext
                        break
            return path

    path = await loop.run_in_executor(None, run)
    if not path or not os.path.exists(path):
        raise DownloadError("yt-dlp finished but output file is missing")
    progress["stage"] = "done"
    progress["filename"] = os.path.basename(path)
    return path


def _filename_from_response(url: str, resp: aiohttp.ClientResponse) -> str:
    cd = resp.headers.get("Content-Disposition", "")
    if "filename=" in cd:
        name = cd.split("filename=")[-1].strip().strip('"').strip("'")
        if name:
            return safe_filename(unquote(name))

    path = urlparse(url).path
    name = os.path.basename(path)
    if name:
        return safe_filename(unquote(name))

    ext = mimetypes.guess_extension(resp.headers.get("Content-Type", "").split(";")[0].strip()) or ""
    return safe_filename(f"file_{int(time.time())}{ext}")


async def _download_direct(url: str, outdir: str, progress: dict) -> str:
    timeout = aiohttp.ClientTimeout(total=config.DOWNLOAD_TIMEOUT, sock_connect=30)
    headers = {"User-Agent": "Mozilla/5.0 (compatible; URLDownloaderBot/1.0)"}

    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        async with session.get(url, allow_redirects=True) as resp:
            if resp.status >= 400:
                raise DownloadError(f"HTTP {resp.status}")

            total = int(resp.headers.get("Content-Length", 0) or 0)
            filename = _filename_from_response(url, resp)
            filepath = os.path.join(outdir, filename)

            progress["stage"] = "downloading"
            progress["total"] = total
            progress["filename"] = filename

            downloaded = 0
            last_tick = time.time()
            last_downloaded = 0

            async with aiofiles.open(filepath, "wb") as f:
                async for chunk in resp.content.iter_chunked(config.CHUNK_SIZE):
                    await f.write(chunk)
                    downloaded += len(chunk)
                    progress["downloaded"] = downloaded

                    now = time.time()
                    if now - last_tick >= 1:
                        progress["speed"] = (downloaded - last_downloaded) / (now - last_tick)
                        last_tick = now
                        last_downloaded = downloaded

            progress["stage"] = "done"
            return filepath


def _looks_like_direct_file(url: str) -> bool:
    """Quick heuristic to skip yt-dlp entirely for obvious direct-file links."""
    path = urlparse(url).path.lower()
    direct_exts = (
        ".pdf", ".zip", ".rar", ".7z", ".doc", ".docx", ".xls", ".xlsx",
        ".ppt", ".pptx", ".mp3", ".wav", ".flac", ".txt", ".apk", ".exe",
        ".iso", ".epub", ".mobi", ".csv", ".json", ".png", ".jpg", ".jpeg",
        ".gif", ".webp",
    )
    return path.endswith(direct_exts)


async def download_url(url: str, outdir: str, progress: dict = None) -> tuple[str, dict]:
    """
    Download `url` into `outdir`. Returns (filepath, progress_dict).
    Raises DownloadError on failure.
    """
    progress = progress if progress is not None else _new_progress()
    os.makedirs(outdir, exist_ok=True)

    if _looks_like_direct_file(url):
        try:
            path = await _download_direct(url, outdir, progress)
            return path, progress
        except Exception as e:
            logger.warning("Direct download failed for %s: %s", url, e)
            raise DownloadError(str(e))

    # Try yt-dlp first (handles YouTube, m3u8/HLS, and hundreds of sites)
    try:
        path = await _download_with_ytdlp(url, outdir, progress)
        return path, progress
    except Exception as e:
        msg = str(e).lower()
        unsupported = "unsupported url" in msg or "no video formats" in msg or "unable to extract" in msg
        if not unsupported:
            logger.info("yt-dlp failed for %s (%s) — falling back to direct download", url, e)
        try:
            path = await _download_direct(url, outdir, progress)
            return path, progress
        except Exception as e2:
            progress["stage"] = "error"
            raise DownloadError(f"yt-dlp: {e} | direct: {e2}")
