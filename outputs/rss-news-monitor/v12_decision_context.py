"""Bounded discovery context, with no cutoff on the final delivery guard.

Shortlisting applies only to the analyst's first-pass discovery hints. Every
send still has to compare its complete draft with the full delivery history.
This module is pure: it does not read files, alter state or call a model.
"""
from __future__ import annotations

from delivery_guard import canonical, headline, quantities, similarity, story_keys


def shortlist_related(candidates, history, receipt_urls, limit_per_candidate=3):
    """Keep exact source matches plus a few relevant discovery excerpts.

    Exact URL and syndicated-story identities are never truncated by the cap.
    Remaining scores rank discovery hints only, never establish a duplicate.
    Return the same receipt excerpt shape consumed by the existing worker.
    """
    if type(limit_per_candidate) is not int or limit_per_candidate < 0:
        raise ValueError("limit_per_candidate must be a nonnegative integer")
    records = list(history.values() if isinstance(history, dict) else history)
    records = [row for row in records if row.get("evidence_type") == "telegram_receipt"]
    selected = set()
    for candidate in candidates:
        url = canonical(candidate["url"])
        stories = story_keys([url])
        title = candidate.get("title") or ""
        text = title + " " + (candidate.get("summary") or "")
        figures = quantities(text)
        ranked = []
        for row in records:
            urls = {canonical(value) for value in row.get("urls", [])}
            if url in urls or stories & story_keys(urls):
                selected.add(row["id"])
                continue
            body = row["message_text"]
            score = similarity(text, body)
            title_score = similarity(title, headline(body)) if title.strip() else 0
            if score >= .22 or title_score >= .52:
                ranked.append((bool(figures & quantities(body)), max(score, title_score), row["id"]))
        ranked.sort(reverse=True)
        selected.update(item[2] for item in ranked[:limit_per_candidate])
    rows = []
    for record in records:
        if record["id"] not in selected:
            continue
        body = record["message_text"]
        rows.append({
            "id": record["id"], "evidence_type": "telegram_receipt",
            "delivery_history_urls": sorted(receipt_urls.get(record["id"], [])),
            "message_excerpt": body[:480], "excerpt_truncated": len(body) > 480,
        })
    return rows


def compact_novelty_payload(rendered, report):
    """Remove repeated draft metadata and local paths, retaining all full bodies.

    The compact document is model input only. The original report remains the
    authority used by validate_novelty and the last-moment publication guard.
    """
    match_keys = ("id", "evidence_type", "message_text", "urls", "shared_urls",
                  "shared_story_keys", "shared_quantities", "same_content")
    return {
        "draft": {"message_text": rendered["message_text"],
                  "new_facts": list(rendered["novelty"]["new_facts"])},
        "guard": {"message_sha256": report["message_sha256"],
                  "history_count": report.get("history_count", 0),
                  "matches": [{key: row[key] for key in match_keys if key in row}
                              for row in report.get("matches", [])]},
    }
