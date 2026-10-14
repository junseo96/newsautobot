"""Source-specific list decoration, not an editorial content filter."""
from __future__ import annotations

import re
from urllib.parse import parse_qs, urlsplit


_KPX_LISTING_TAIL = re.compile(
    r"\s+작성일\s*[:：]?\s*(?P<date>\d{4}[./-]\d{1,2}[./-]\d{1,2})"
    r"\s+조회수\s*[:：]?\s*\d[\d,]*\s*$"
)


def is_kpx_notice_url(url):
    """Limit cleanup to KPX's actual gallery notice view route."""
    try:
        parsed = urlsplit(url or "")
        host = (parsed.hostname or "").lower()
        query = parse_qs(parsed.query)
        return bool(
            (host == "kpx.or.kr" or host.endswith(".kpx.or.kr"))
            and parsed.path.rstrip("/") == "/gallery.es"
            and query.get("act") == ["view"]
            and len(query.get("list_no", [])) == 1
            and query["list_no"][0].isdigit()
        )
    except (TypeError, ValueError):
        return False


def kpx_listing_title(url, title):
    """Return (real title, listed date) only for the observed KPX card shape.

    Keep publication date outside the headline so a changing view counter or
    disappearing new badge cannot manufacture an article revision. Requiring
    the complete trailing field pair avoids deleting those words in a story.
    """
    if not isinstance(title, str) or not is_kpx_notice_url(url):
        return title, None
    match = _KPX_LISTING_TAIL.search(title)
    if not match:
        return title, None
    headline = re.sub(r"^새글\s+", "", title[:match.start()].strip())
    if not headline:
        return title, None
    return headline, match.group("date")


def article_title(url, title):
    return kpx_listing_title(url, title)[0]
