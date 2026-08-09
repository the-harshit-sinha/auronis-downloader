"""
Small stateless helpers: URL validation/extraction and human-friendly formatting.
"""
import re
from urllib.parse import urlparse

_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)


def is_valid_url(url: str) -> bool:
    url = url.strip()
    if not url:
        return False
    try:
        parsed = urlparse(url)
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except Exception:
        return False


def extract_urls(text: str) -> list[str]:
    """Pull every http(s) URL out of a blob of text, de-duplicated, order preserved."""
    found = _URL_RE.findall(text or "")
    seen = set()
    result = []
    for u in found:
        u = u.strip().rstrip(").,;\"'")
        if is_valid_url(u) and u not in seen:
            seen.add(u)
            result.append(u)
    return result


def format_bytes(num: float) -> str:
    if not num:
        return "0 B"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if num < 1024:
            return f"{num:.1f} {unit}"
        num /= 1024
    return f"{num:.1f} PB"


def format_eta(seconds) -> str:
    if not seconds or seconds < 0:
        return "--"
    seconds = int(seconds)
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}h{m:02d}m"
    if m:
        return f"{m}m{s:02d}s"
    return f"{s}s"


def progress_bar(done: int, total: int, width: int = 12) -> str:
    if not total:
        return "░" * width
    filled = int(width * min(done / total, 1.0))
    return "█" * filled + "░" * (width - filled)


def safe_filename(name: str, fallback: str = "file") -> str:
    name = (name or "").strip() or fallback
    name = re.sub(r'[\\/*?:"<>|]', "_", name)
    return name[:150]
