"""Batch-bound editorial decisions and verifiable Telegram delivery evidence.

Only explicitly decided URLs change state. Receipt and duplicate checks run for
the entire batch before any article is updated; a bad decision rolls back all.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import sqlite3
from pathlib import Path
from project_paths import evidence_path, same_evidence_path

UTC = dt.timezone.utc


def ensure_review_schema(con):
    con.executescript("""
    CREATE TABLE IF NOT EXISTS delivery_history(
        id INTEGER PRIMARY KEY, url TEXT NOT NULL, receipt_file TEXT NOT NULL,
        message_sha256 TEXT NOT NULL, message_text TEXT NOT NULL,
        sent_at TEXT NOT NULL, telegram_message_ids TEXT NOT NULL,
        run_id TEXT NOT NULL, UNIQUE(url,message_sha256)
    );
    CREATE INDEX IF NOT EXISTS idx_delivery_history_url ON delivery_history(url,sent_at);
    CREATE TABLE IF NOT EXISTS decision_history(
        id INTEGER PRIMARY KEY, run_id TEXT NOT NULL, url TEXT NOT NULL,
        status TEXT NOT NULL, reason TEXT NOT NULL, duplicate_of TEXT,
        receipt_file TEXT, policy_version INTEGER NOT NULL, decided_at TEXT NOT NULL,
        UNIQUE(run_id,url)
    );
    """)


def read_json(path):
    with evidence_path(path).open(encoding="utf-8-sig") as source:
        value = json.load(source)
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object")
    return value


def timestamp(value, label):
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        raise ValueError(f"{label} must be an ISO timestamp") from None
    if parsed.tzinfo is None:
        raise ValueError(f"{label} must include a timezone")
    return parsed.astimezone(UTC)


def batch_candidates(batch, batch_path):
    """Use the complete immutable run snapshot when the current page links it."""
    pagination = batch.get("pagination") or {}
    snapshot_path = pagination.get("snapshot_path")
    if snapshot_path:
        path = evidence_path(snapshot_path, base=Path(batch_path).parent)
        snapshot = read_json(path)
        if snapshot.get("run_id") != batch.get("run_id"):
            raise ValueError("Run snapshot does not match the active batch")
        return snapshot.get("candidates", [])
    return batch.get("candidates", [])


def validate_receipt(path, url, canonicalize, generated_at):
    path = evidence_path(path)
    receipt = read_json(path)
    if receipt.get("status") != "complete":
        raise ValueError("Delivered decisions require a complete Telegram receipt")
    message = receipt.get("message_text")
    if not isinstance(message, str) or not message.strip():
        raise ValueError("Receipt must retain the actual delivered message text")
    digest = hashlib.sha256(message.encode("utf-8")).hexdigest()
    if receipt.get("message_sha256") != digest:
        raise ValueError("Receipt message hash does not match its text")
    article_urls = receipt.get("article_urls")
    if not isinstance(article_urls, list) or not all(isinstance(x, str) for x in article_urls):
        raise ValueError("Receipt must list its explicitly delivered article URLs")
    if url not in {canonicalize(x) for x in article_urls}:
        raise ValueError("Receipt does not cover this candidate URL")
    message_ids = receipt.get("telegram_message_ids")
    if not isinstance(message_ids, list) or not message_ids or not all(type(x) is int and x > 0 for x in message_ids):
        raise ValueError("Receipt must contain successful Telegram message IDs")
    sent_at = timestamp(receipt.get("sent_at"), "Receipt sent_at")
    if sent_at < generated_at:
        raise ValueError("Receipt predates this collection run")
    if sent_at > dt.datetime.now(UTC) + dt.timedelta(minutes=5):
        raise ValueError("Receipt sent_at is in the future")
    message_file = receipt.get("message_file")
    if message_file:
        # Preserve CRLF: sender hashes the exact original trimmed text.
        stored = evidence_path(message_file).read_bytes().decode("utf-8-sig").strip()
        # The sender's optional title is prepended with a blank line.
        if message != stored and not message.endswith("\n\n" + stored) and not message.endswith("\r\n\r\n" + stored):
            raise ValueError("Message file has changed since its Telegram receipt")
    return {
        "receipt_file": str(path), "message_sha256": digest,
        "message_text": message, "sent_at": sent_at.isoformat(timespec="seconds"),
        "telegram_message_ids": json.dumps(message_ids),
    }


def validate_legacy_direct_link_receipt(path, url, canonicalize):
    """Validate a historic receipt when its delivered text retains this URL.

    Some early sender runs saved a Google RSS URL in ``article_urls`` while
    the Telegram message itself linked the publisher URL.  The signed receipt
    plus that direct link is delivery evidence; the old row's delivered status
    alone is not.  This narrow recovery path deliberately cannot infer aliases
    from matching titles or snippets.
    """
    path = evidence_path(path)
    receipt = read_json(path)
    if receipt.get("status") != "complete":
        raise ValueError("Legacy recovery requires a complete Telegram receipt")
    message = receipt.get("message_text")
    if not isinstance(message, str) or not message.strip():
        raise ValueError("Legacy recovery receipt must retain delivered message text")
    digest = hashlib.sha256(message.encode("utf-8")).hexdigest()
    if receipt.get("message_sha256") != digest:
        raise ValueError("Legacy recovery receipt message hash does not match its text")
    message_ids = receipt.get("telegram_message_ids")
    if not isinstance(message_ids, list) or not message_ids or not all(type(x) is int and x > 0 for x in message_ids):
        raise ValueError("Legacy recovery receipt must contain successful Telegram message IDs")
    sent_at = timestamp(receipt.get("sent_at"), "Legacy receipt sent_at")
    if sent_at > dt.datetime.now(UTC) + dt.timedelta(minutes=5):
        raise ValueError("Legacy receipt sent_at is in the future")
    links = {
        canonicalize(value.rstrip(".,;:"))
        for value in re.findall(r"https?://[^\s<>()\[\]]+", message)
    }
    if canonicalize(url) not in links:
        raise ValueError("Legacy recovery requires the exact publisher URL in delivered message text")
    return {
        "receipt_file": str(path), "message_sha256": digest,
        "message_text": message, "sent_at": sent_at.isoformat(timespec="seconds"),
        "telegram_message_ids": json.dumps(message_ids),
    }


def recover_legacy_direct_link_deliveries(args, canonicalize, ensure_db):
    """Backfill only old delivered rows proven by an exact direct message link."""
    document = read_json(args.mapping_file)
    mappings = document.get("mappings")
    if not isinstance(mappings, list) or not mappings:
        raise ValueError("Legacy recovery mapping file requires a non-empty mappings array")
    con = sqlite3.connect(args.db,timeout=30)
    con.row_factory = sqlite3.Row
    try:
        ensure_db(con)
        ensure_review_schema(con)
        con.execute("BEGIN IMMEDIATE")
        validated = []
        seen = set()
        for mapping in mappings:
            if not isinstance(mapping, dict):
                raise ValueError("Each legacy recovery mapping must be an object")
            raw_url = mapping.get("url")
            receipt_path = mapping.get("receipt_file")
            if not isinstance(raw_url, str) or not raw_url.strip() or not isinstance(receipt_path, str) or not receipt_path:
                raise ValueError("Each legacy recovery mapping requires url and receipt_file")
            url = canonicalize(raw_url)
            if url in seen:
                raise ValueError("A legacy URL may appear only once per recovery")
            seen.add(url)
            row = con.execute("SELECT status FROM articles WHERE url=?", (url,)).fetchone()
            if row is None or row["status"] != "delivered":
                raise ValueError("Legacy recovery accepts only existing delivered rows")
            if con.execute("SELECT 1 FROM delivery_history WHERE url=?", (url,)).fetchone() is not None:
                raise ValueError("Legacy recovery URL already has receipt-backed delivery history")
            validated.append((url, validate_legacy_direct_link_receipt(receipt_path, url, canonicalize)))
        recovered = 0
        for url, receipt in validated:
            run_id = "legacy-direct-link-" + receipt["message_sha256"][:16]
            con.execute("INSERT INTO delivery_history(url,receipt_file,message_sha256,message_text,sent_at,telegram_message_ids,run_id) VALUES(?,?,?,?,?,?,?)", (url, receipt["receipt_file"], receipt["message_sha256"], receipt["message_text"], receipt["sent_at"], receipt["telegram_message_ids"], run_id))
            con.execute("UPDATE articles SET delivered_at=? WHERE url=?", (receipt["sent_at"], url))
            recovered += 1
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
    print(json.dumps({"recovered_direct_link_deliveries": recovered}, ensure_ascii=False))
    return 0


def decisions_document(args, batch, canonicalize):
    decision_path = getattr(args, "decision_file", None)
    legacy = {
        "delivered": getattr(args, "delivered_url", None) or [],
        "reviewed": getattr(args, "reviewed_url", None) or [],
        "brief": getattr(args, "brief_url", None) or [],
    }
    if decision_path:
        if any(legacy.values()):
            raise ValueError("Use a decision file or legacy URL lists, not both")
        doc = read_json(decision_path)
        if doc.get("run_id") != batch.get("run_id"):
            raise ValueError("Stale decision file: run_id does not match the active batch")
        return doc
    if legacy["delivered"]:
        raise ValueError("Legacy delivered URL acknowledgements are disabled; use receipt-backed decisions")
    # Compatibility is limited to explicit current-batch non-delivery decisions.
    return {"run_id": batch.get("run_id"), "decisions": [
        {"url": canonicalize(url), "status": status, "reason": f"legacy_explicit_{status}"}
        for status in ("reviewed", "brief") for url in legacy[status]
    ]}


def acknowledge(args, canonicalize, ensure_db):
    recover = bool(getattr(args, "recover_deliveries", False))
    batch = read_json(args.batch)
    if recover:
        snapshot_path = (batch.get("run_files") or {}).get("snapshot")
        if not snapshot_path or not same_evidence_path(snapshot_path, args.batch):
            raise ValueError("Recovery requires the immutable run snapshot as --batch")
    run_id = batch.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        raise ValueError("The active batch is missing its run_id")
    doc = decisions_document(args, batch, canonicalize)
    decisions = doc.get("decisions")
    if not isinstance(decisions, list):
        raise ValueError("Decision file must contain a decisions array")
    generated_at = timestamp(batch.get("generated_at_kst"), "Batch generated_at_kst")
    candidates = {canonicalize(x["url"]): x for x in batch_candidates(batch, args.batch)}
    cfg = read_json(args.config)
    policy_version = int(cfg.get("selection_policy_version", 1))
    batch_policy = int(batch.get("policy_version", policy_version))
    if batch_policy != policy_version and not recover:
        raise ValueError("The selection policy changed; collect a fresh batch")
    stamp = dt.datetime.now(UTC).isoformat(timespec="seconds")
    con = sqlite3.connect(args.db,timeout=30)
    con.row_factory = sqlite3.Row
    try:
        ensure_db(con)
        ensure_review_schema(con)
        con.execute("BEGIN IMMEDIATE")
        latest = con.execute("SELECT run_id FROM source_runs ORDER BY id DESC LIMIT 1").fetchone()
        if latest and latest["run_id"] != run_id and not recover:
            raise ValueError("Stale batch: a newer collection run is already active")
        validated = []
        seen = set()
        for decision in decisions:
            if not isinstance(decision, dict):
                raise ValueError("Each decision must be an object")
            raw_url = decision.get("url")
            if not isinstance(raw_url, str) or not raw_url.strip():
                raise ValueError("Every decision must identify a candidate URL")
            url = canonicalize(raw_url)
            if url not in candidates:
                raise ValueError("Decision URL is not a candidate in this collection run")
            if url in seen:
                raise ValueError("A candidate may have only one decision per run")
            seen.add(url)
            status = decision.get("status")
            if status not in {"delivered", "reviewed", "brief"}:
                raise ValueError("Decision status must be delivered, reviewed, or brief")
            if recover and status != "delivered":
                raise ValueError("Recovery accepts only receipt-backed delivered decisions")
            reason = decision.get("reason")
            if not isinstance(reason, str) or not reason.strip():
                raise ValueError("Every decision requires its specific editorial reason")
            reason = reason.strip()
            row = con.execute("SELECT * FROM articles WHERE url=?", (url,)).fetchone()
            if row is None:
                raise ValueError("Decision candidate is absent from the article database")
            if row["status"] == "delivered" and status != "delivered":
                raise ValueError("An editorial decision cannot undo a completed delivery")
            duplicate_of = decision.get("duplicate_of")
            is_duplicate = status == "reviewed" and ("duplicate" in reason.lower() or "중복" in reason or "이전 보도와 유사" in reason)
            if duplicate_of is not None:
                if status != "reviewed" or not isinstance(duplicate_of, str):
                    raise ValueError("duplicate_of is only valid on a reviewed decision")
                duplicate_of = canonicalize(duplicate_of)
                # A later revision may have reopened the source article; its
                # earlier receipt still proves what was actually delivered.
                proof = con.execute("SELECT 1 FROM delivery_history WHERE url=? LIMIT 1", (duplicate_of,)).fetchone()
                if proof is None:
                    raise ValueError("Duplicate rejection requires receipt-backed prior delivery")
            elif is_duplicate:
                raise ValueError("A duplicate rejection must identify duplicate_of")
            receipt = None
            if status == "delivered":
                receipt_path = decision.get("receipt_file")
                if not isinstance(receipt_path, str) or not receipt_path:
                    raise ValueError("Delivered decisions require a receipt_file")
                receipt = validate_receipt(receipt_path, url, canonicalize, generated_at)
            elif decision.get("receipt_file"):
                raise ValueError("receipt_file is only valid for delivered decisions")
            preserve_current = False
            if recover:
                candidate = candidates[url]
                if not all(isinstance(candidate.get(key), str) for key in ("title", "summary")):
                    raise ValueError("Recovery requires the original candidate title and summary")
                preserve_current = any(row[key] != candidate[key] for key in ("title", "summary"))
                prior_published = timestamp(candidate["published_at"], "Candidate published_at") if candidate.get("published_at") else None
                current_published = timestamp(row["published_at"], "Article published_at") if row["published_at"] else None
                preserve_current = preserve_current or prior_published != current_published
            existing = con.execute("SELECT status,reason,duplicate_of,receipt_file FROM decision_history WHERE run_id=? AND url=?", (run_id, url)).fetchone()
            record = (status, reason, duplicate_of, receipt["receipt_file"] if receipt else None)
            same_recovery = recover and existing and existing["status"] == "delivered" and same_evidence_path(existing["receipt_file"], record[3])
            same_record = existing and tuple(existing)[:3] == record[:3] and same_evidence_path(existing["receipt_file"], record[3])
            if existing and not same_record and not same_recovery:
                raise ValueError("This candidate already has a different decision in this run")
            validated.append((url, status, reason, duplicate_of, receipt, existing is not None, preserve_current))
        counts = {"reviewed": 0, "brief": 0, "delivered": 0, "already_recorded": 0, "recovered_history": 0, "current_revision_preserved": 0}
        for url, status, reason, duplicate_of, receipt, recorded, preserve_current in validated:
            if recorded:
                counts["already_recorded"] += 1
                continue
            if receipt:
                con.execute("INSERT OR IGNORE INTO delivery_history(url,receipt_file,message_sha256,message_text,sent_at,telegram_message_ids,run_id) VALUES(?,?,?,?,?,?,?)", (url, receipt["receipt_file"], receipt["message_sha256"], receipt["message_text"], receipt["sent_at"], receipt["telegram_message_ids"], run_id))
                if recover:
                    counts["recovered_history"] += 1
                if preserve_current:
                    counts["current_revision_preserved"] += 1
                else:
                    con.execute("UPDATE articles SET status='delivered',delivered_at=?,reviewed_at=?,decision_policy_version=?,decision_reason=? WHERE url=?", (receipt["sent_at"], stamp, batch_policy if recover else policy_version, reason, url))
            else:
                con.execute("UPDATE articles SET status=?,reviewed_at=?,decision_policy_version=?,decision_reason=? WHERE url=?", (status, stamp, policy_version, reason, url))
            con.execute("INSERT INTO decision_history(run_id,url,status,reason,duplicate_of,receipt_file,policy_version,decided_at) VALUES(?,?,?,?,?,?,?,?)", (run_id, url, status, reason, duplicate_of, receipt["receipt_file"] if receipt else None, batch_policy if recover else policy_version, stamp))
            if not preserve_current:
                counts[status] += 1
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
    print(json.dumps({"run_id": run_id, **counts}, ensure_ascii=False))
    return 0
