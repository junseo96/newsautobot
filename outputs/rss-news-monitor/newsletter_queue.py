"""Validate connector-extracted newsletters and journal successful ingestion.

This module performs no mailbox access or transport. Message IDs become processed
only in the same database transaction that has already inserted every article.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

OFFICIAL_DOMAINS = frozenset({"eia.gov", "energy.gov", "ferc.gov"})


def checked_url(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a nonempty HTTP(S) URL")
    value = value.strip()
    try:
        parts = urlsplit(value)
        if parts.scheme not in {"https", "http"} or not parts.hostname or parts.username or parts.password:
            raise ValueError
        if re.search(r"[\s\x00-\x1f]", value):
            raise ValueError
        _ = parts.port
    except ValueError:
        raise ValueError(f"{label} must be a public HTTP(S) URL without credentials") from None
    host = parts.hostname.lower().rstrip(".")
    if host in {"localhost", "127.0.0.1", "::1"} or "." not in host:
        raise ValueError(f"{label} must name a public news source")
    return value


def official_url(value):
    host = (urlsplit(value).hostname or "").lower().rstrip(".")
    return any(host == domain or host.endswith("." + domain) for domain in OFFICIAL_DOMAINS)


def load_newsletter_results(path, item_factory, parse_date, received_after_epoch=None):
    """Return fetch-style results, or raise before returning any partial batch."""
    with Path(path).open(encoding="utf-8-sig") as source_file:
        payload = json.load(source_file)
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ValueError("Newsletter input requires schema_version 1")
    messages = payload.get("messages")
    if not isinstance(messages, list):
        raise ValueError("Newsletter input requires a messages array")
    stamp = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    results, message_ids = [], set()
    for message in messages:
        if not isinstance(message, dict):
            raise ValueError("Each newsletter message must be an object")
        if received_after_epoch is not None:
            received_text = message.get("received_at")
            received = parse_date(received_text) if isinstance(received_text, str) else None
            if received is not None and received.tzinfo is None:
                raise ValueError("v9 received_at requires an explicit timezone")
            if received is None or received.timestamp() < received_after_epoch:
                raise ValueError("v9 requires actual Gmail received_at at or after its start boundary")
        message_id = message.get("message_id")
        if not isinstance(message_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", message_id):
            raise ValueError("Newsletter message_id is missing or invalid")
        if message_id in message_ids:
            raise ValueError("Newsletter input repeats a message_id")
        message_ids.add(message_id)
        name = message.get("source")
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 200:
            raise ValueError("Every newsletter message requires its source name")
        source_url = checked_url(message.get("source_url"), "Newsletter source_url")
        for flag in ("primary", "must_review"):
            if flag in message and type(message[flag]) is not bool:
                raise ValueError(f"Newsletter {flag} must be a boolean")
        articles = message.get("articles")
        classification_reason = message.get("non_article_reason")
        if not isinstance(articles, list):
            raise ValueError("A newsletter message requires an articles array")
        if not articles and (not isinstance(classification_reason, str) or not classification_reason.strip()):
            raise ValueError("Empty extraction requires non_article_reason after full message review")
        if classification_reason is not None:
            if not isinstance(classification_reason, str) or not classification_reason.strip() or articles:
                raise ValueError("non_article_reason is valid only for an explicitly reviewed non-news message")
            classification_reason = classification_reason.strip()
        prepared = []
        for article in articles:
            if not isinstance(article, dict):
                raise ValueError("Each newsletter article must be an object")
            url = checked_url(article.get("url"), "Newsletter article URL")
            title, summary = article.get("title"), article.get("summary", "")
            if not isinstance(title, str) or not title.strip():
                raise ValueError("Every newsletter article requires a title")
            if not isinstance(summary, str):
                raise ValueError("Newsletter article summary must be text")
            published = article.get("published_at")
            if published is not None and not isinstance(published, str):
                raise ValueError("Newsletter article published_at must be text or null")
            parsed = parse_date(published) if published else None
            if published and parsed is None:
                raise ValueError("Newsletter article published_at is invalid")
            prepared.append((url, title.strip(), summary.strip(), parsed))
        # Source names and user-supplied primary flags cannot impersonate an
        # agency: both source and every article must be on an allowed domain.
        is_primary = official_url(source_url) and all(official_url(x[0]) for x in prepared)
        src = {"name": "Gmail:" + name.strip(), "url": source_url, "kind": "newsletter",
               "group": "newsletter", "priority": 1 if is_primary else 2,
               "primary": is_primary, "must_review": is_primary or bool(message.get("must_review", False))}
        items = [item_factory(src, *article) for article in prepared]
        urls = [x["url"] for x in items]
        if len(set(urls)) != len(urls):
            raise ValueError("A newsletter message repeats an article URL")
        normalized = {"message_id": message_id, "source": src["name"], "source_url": source_url,
                      "primary": is_primary, "must_review": src["must_review"],
                      "articles": sorted([{"url": x["url"], "title": x["title"], "summary": x["summary"],
                                           "published_at": x["published_at"].isoformat() if x.get("published_at") else None}
                                          for x in items], key=lambda x: x["url"])}
        if classification_reason is not None:
            normalized["non_article_reason"] = classification_reason
        digest = hashlib.sha256(json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        results.append({"source": src, "ok": True, "items": items, "error": None,
                        "started_at": stamp, "finished_at": stamp,
                        "newsletter_message": {"message_id": message_id, "source": src["name"], "source_url": source_url,
                                               "received_at": received.isoformat() if received_after_epoch is not None else message.get("received_at"),
                                               "content_sha256": digest, "article_urls": urls,
                                               "classification_reason": classification_reason}})
    return results


load_results = load_newsletter_results


def ensure_newsletter_schema(con):
    # Do not executescript/commit here: the journal shares the caller's article
    # ingestion transaction, so crashes cannot process mail without its articles.
    con.execute("""CREATE TABLE IF NOT EXISTS newsletter_messages(
        message_id TEXT PRIMARY KEY,source TEXT NOT NULL,source_url TEXT NOT NULL,
        content_sha256 TEXT NOT NULL,article_count INTEGER NOT NULL,
        imported_at TEXT NOT NULL,run_id TEXT NOT NULL,classification_reason TEXT,
        received_at TEXT)""")
    columns = {row[1] for row in con.execute("PRAGMA table_info(newsletter_messages)")}
    if "classification_reason" not in columns:
        con.execute("ALTER TABLE newsletter_messages ADD COLUMN classification_reason TEXT")
    if "received_at" not in columns:
        con.execute("ALTER TABLE newsletter_messages ADD COLUMN received_at TEXT")
    con.execute("""CREATE TABLE IF NOT EXISTS newsletter_message_articles(
        message_id TEXT NOT NULL,article_url TEXT NOT NULL,
        PRIMARY KEY(message_id,article_url))""")


def unimported_newsletter_results(con, results):
    """Do not replay an old monthly release over newer facts on the same URL."""
    ensure_newsletter_schema(con)
    fresh = []
    for result in results:
        meta = result.get("newsletter_message")
        if meta is None or result.get("ok") is not True:
            raise ValueError("Expected validated newsletter extraction results")
        previous = con.execute("SELECT content_sha256 FROM newsletter_messages WHERE message_id=?", (meta["message_id"],)).fetchone()
        if previous and previous[0] != meta["content_sha256"]:
            raise ValueError("Previously imported immutable Gmail message changed; preserve its real ID and require explicit journal correction")
        if not previous:
            fresh.append(result)
    return fresh


def journal_newsletter_results(con, results, run_id):
    """Journal only fully ingested messages; caller must commit or roll back."""
    ensure_newsletter_schema(con)
    staged, seen = [], set()
    for result in results:
        meta = result.get("newsletter_message")
        if meta is None:
            continue
        if result.get("ok") is not True:
            raise ValueError("Failed newsletter extraction cannot be marked processed")
        message_id = meta["message_id"]
        if message_id in seen:
            raise ValueError("Newsletter journal repeats a message_id")
        seen.add(message_id)
        urls = meta["article_urls"]
        if not urls and not meta.get("classification_reason"):
            raise ValueError("Newsletter journal requires successfully imported article URLs")
        for url in urls:
            if con.execute("SELECT 1 FROM articles WHERE url=?", (url,)).fetchone() is None:
                raise ValueError("Newsletter article is absent from the database; message remains unprocessed")
        previous = con.execute("SELECT content_sha256 FROM newsletter_messages WHERE message_id=?", (message_id,)).fetchone()
        if previous and previous[0] != meta["content_sha256"]:
            raise ValueError("Previously imported immutable Gmail message changed; preserve its real ID and require explicit journal correction")
        staged.append((meta, previous is not None))
    stamp = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    counts = {"imported_messages": 0, "already_imported_messages": 0, "article_count": 0, "confirmed_message_ids": [], "article_urls": []}
    for meta, exists in staged:
        message_id, urls = meta["message_id"], meta["article_urls"]
        if not exists:
            con.execute("INSERT INTO newsletter_messages(message_id,source,source_url,content_sha256,article_count,imported_at,run_id,classification_reason,received_at) VALUES(?,?,?,?,?,?,?,?,?)",
                        (message_id, meta["source"], meta["source_url"], meta["content_sha256"], len(urls), stamp, run_id, meta.get("classification_reason"), meta.get("received_at")))
            con.executemany("INSERT INTO newsletter_message_articles(message_id,article_url) VALUES(?,?)", [(message_id, url) for url in urls])
        counts["already_imported_messages" if exists else "imported_messages"] += 1
        counts["article_count"] += len(urls)
        counts["confirmed_message_ids"].append(message_id)
        counts["article_urls"].extend(urls)
    counts["article_urls"] = sorted(set(counts["article_urls"]))
    return counts
