# Advanced URL Downloader/Uploader Telegram Bot

A production-ready Telegram bot that downloads files/videos from URLs (or
bulk `.txt` lists of URLs) and re-uploads them into the chat — one at a
time, in strict order, with a persistent SQLite-backed queue that survives
restarts and redeploys.

## Features

- Accepts a single URL as a text message, or a `.txt` file with hundreds of URLs.
- **Strictly sequential** per-chat queue: download → upload → delete temp file → next.
  Never downloads multiple files at once.
- **Persistent** — the queue lives in SQLite. If the bot crashes or is
  redeployed, it picks up right where it left off on the next startup.
- Live-updating status message (`📋 Queue Status`) with a progress bar,
  speed, and ETA while a file is downloading.
- Automatic error handling: a failed URL is skipped, logged, and the queue
  keeps going. At the end you get a summary and a `.txt` of every URL that failed.
- Downloads via `yt-dlp` first (YouTube and hundreds of other sites, plus
  native M3U8/HLS support), and falls back to plain HTTP streaming for
  direct file links (PDF, ZIP/RAR, docs, audio, video, etc).
- Duplicate-URL protection, URL validation, inline-button UI, admin stats.

## Project layout

```
telegram_url_bot/
├── main.py                  # entry point — builds the app, resumes the queue on startup
├── requirements.txt
├── .env.example
├── bot/
│   ├── config.py             # env-var driven configuration
│   ├── database.py           # SQLite persistence layer (aiosqlite)
│   ├── downloader.py         # yt-dlp + direct HTTP download engine
│   ├── queue_manager.py      # the sequential download→upload→cleanup pipeline
│   ├── keyboards.py          # inline keyboards
│   ├── utils.py              # URL validation/extraction, formatting helpers
│   └── handlers/
│       ├── start.py          # /start, /help
│       ├── stats.py          # /stats
│       ├── settings.py       # /settings
│       ├── queue.py          # /queue
│       ├── cancel.py         # /cancel
│       ├── messages.py       # plain URL messages + .txt uploads
│       └── callbacks.py      # inline button routing
```

## Setup

1. **Create a bot** with [@BotFather](https://t.me/BotFather) and grab the token.
2. Copy the env template and fill it in:
   ```bash
   cp .env.example .env
   ```
   At minimum set `BOT_TOKEN`. `API_ID`/`API_HASH` (from https://my.telegram.org)
   are included for future MTProto extensions but aren't required for the
   Bot-API-only flow in this codebase.
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Run it:
   ```bash
   python main.py
   ```

The bot uses long polling, so no public URL/webhook is required — it runs
fine on a VPS, a Raspberry Pi, or inside a container.

## A note on file size

The standard Telegram Bot API caps bot uploads at **50 MB**. To upload
larger files (up to 2 GB), run your own
[local Bot API server](https://github.com/tdlib/telegram-bot-api) (this is
what `API_ID`/`API_HASH` are for) and point `python-telegram-bot` at it via
`base_url` in `ApplicationBuilder`. Set `MAX_FILE_SIZE_MB` in `.env` to
match whichever mode you're running — the bot enforces this limit itself
and marks oversized files as failed rather than attempting an upload that
Telegram would reject.

## How the queue works

- Every chat gets its own independent, strictly sequential worker
  (`asyncio.Task`). Different chats can process in parallel; within a
  single chat, only one URL is ever downloading/uploading at a time.
- Adding URLs (single message or `.txt` upload) inserts rows into the
  `queue_items` SQLite table and (re)starts that chat's worker if it isn't
  already running.
- On startup, `main.py` resets any row stuck in `processing` (leftover
  from a crash) back to `pending`, then resumes a worker for every chat
  that still has pending items — so a redeploy never loses your queue.
- `/cancel` marks all *pending* items as cancelled; whatever is currently
  mid-download/upload is allowed to finish cleanly first.

## Deployment tips

- **systemd**: run `python main.py` as a service with `Restart=on-failure`
  — the persistent queue means a restart just resumes.
- **Docker**: mount a volume for `bot_data.db` and `downloads/` so the
  queue and temp files survive container restarts.
- Set `ADMIN_IDS` to your Telegram numeric user ID (find it via
  [@userinfobot](https://t.me/userinfobot)) to unlock the global-stats
  block in `/stats`.

## Extending

- Swap `send_document`/`send_video`/`send_audio` selection logic in
  `queue_manager.py` if you want different routing by MIME type instead of extension.
- Add per-user rate limiting or concurrency (multiple chats already run in
  parallel; true multi-worker-per-chat is deliberately not supported to
  respect "one URL at a time").
