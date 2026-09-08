"""Small helpers for shaping Moodle web-service payloads into plain values.

Moodle returns rich HTML for message bodies / summaries / feedback and raw epoch
seconds for every timestamp. These turn both into the human strings the CLI has
always emitted.
"""

import html as _html
import re
import time

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"[ \t\f\v]+")
_BLANKS = re.compile(r"\n\s*\n\s*\n+")
_DROP = re.compile(r"(?is)<(script|style)\b[^>]*>.*?</\1>")
_BR = re.compile(r"(?i)<\s*br\s*/?\s*>")
_BLOCK_END = re.compile(r"(?i)</\s*(p|div|li|tr|h[1-6])\s*>")
_WIB = 7 * 3600  # SCELE reports epochs in UTC; Fasilkom is UTC+7


def clean_html(text: str | None, max_len: int | None = None) -> str:
    """Block tags become newlines, inline tags vanish, entities resolve."""
    if not text:
        return ""
    text = _DROP.sub(" ", text)
    text = _BR.sub("\n", text)
    text = _BLOCK_END.sub("\n", text)
    text = _TAG.sub("", text)
    text = _html.unescape(text)
    text = _WS.sub(" ", text)
    text = _BLANKS.sub("\n\n", text)
    text = "\n".join(line.strip() for line in text.splitlines()).strip()
    return text[:max_len] if max_len else text


def wib(epoch: int | float | None) -> str:
    """Epoch seconds -> 'YYYY-MM-DD HH:MM WIB', or '' when unset."""
    if not epoch:
        return ""
    return time.strftime("%Y-%m-%d %H:%M", time.gmtime(int(epoch) + _WIB)) + " WIB"


def duration(seconds: int | float | None) -> str:
    """Seconds → a short human string, e.g. '40 mins', '1h 30m'. '' when 0/unset."""
    if not seconds:
        return ""
    s = int(seconds)
    if s % 3600 == 0:
        return f"{s // 3600}h"
    if s >= 3600:
        return f"{s // 3600}h {(s % 3600) // 60}m"
    return f"{s // 60} mins" if s % 60 == 0 else f"{s // 60}m {s % 60}s"


def until(epoch: int | float | None) -> str:
    """Human countdown from now to epoch, e.g. 'in 2d 3h' / 'overdue 5h 1m'."""
    if not epoch:
        return ""
    delta = int(epoch) - time.time()
    sign = "overdue" if delta < 0 else "in"
    a = abs(int(delta))
    if a >= 86400:
        return f"{sign} {a // 86400}d {(a % 86400) // 3600}h"
    if a >= 3600:
        return f"{sign} {a // 3600}h {(a % 3600) // 60}m"
    return f"{sign} {a // 60}m"
