"""Read-only, paged model view of one immutable collector snapshot.

No score/freshness filtering, fetching, DB writes, or review claims occur here.
Indices refer to the snapshot's original candidate order.  Full fields and URLs
remain available through ``detail``; only summaries in ``screen`` are bounded.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path


DEFAULT_PAGE_SIZE = 100
DEFAULT_SUMMARY_CHARS = 240


def compact_json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def nonnegative(value):
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return number


def positive(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return number


class RunPacket:
    def __init__(self, snapshot, snapshot_sha256=None, snapshot_bytes=None):
        if not isinstance(snapshot, dict) or not isinstance(snapshot.get("candidates"), list):
            raise ValueError("snapshot must contain the complete candidates list")
        if not isinstance(snapshot.get("run_id"), str) or not snapshot["run_id"]:
            raise ValueError("snapshot must contain run_id")
        if any(not isinstance(row, dict) for row in snapshot["candidates"]):
            raise ValueError("every candidate must be an object")
        # A collector's paged export is not the immutable full snapshot.
        pagination = snapshot.get("pagination", {})
        if "snapshot_path" in snapshot or (pagination and (
            pagination.get("has_more") or pagination.get("offset", 0) != 0
            or pagination.get("total_candidates", pagination.get("total", len(snapshot["candidates"])))
            != len(snapshot["candidates"])
        )):
            raise ValueError("use run_files.snapshot, not a paged export or screening index")
        self.snapshot = snapshot
        self.candidates = snapshot["candidates"]
        raw = compact_json(snapshot).encode("utf-8") if snapshot_sha256 is None else None
        self.sha256 = snapshot_sha256 or hashlib.sha256(raw).hexdigest()
        self.snapshot_bytes = snapshot_bytes if snapshot_bytes is not None else len(raw)

    @classmethod
    def load(cls, path):
        raw = Path(path).read_bytes()
        return cls(json.loads(raw.decode("utf-8-sig")), hashlib.sha256(raw).hexdigest(), len(raw))

    def identity(self):
        return {"run_id": self.snapshot["run_id"], "snapshot_sha256": self.sha256}

    def summary(self, page_size=DEFAULT_PAGE_SIZE):
        if page_size < 1:
            raise ValueError("page_size must be greater than zero")
        data = self.snapshot
        total = len(self.candidates)
        scope = data.get("operational_scope", {})
        historical = scope.get("historical_reference_only_count")
        if historical is None:
            historical = len(scope.get("historical_reference_only", []))
        urls = Counter(row.get("url") for row in self.candidates if row.get("url"))
        newsletter = data.get("newsletter_workflow", {})
        return {
            **self.identity(),
            "lane": data.get("lane"),
            "generated_at_kst": data.get("generated_at_kst"),
            "snapshot_bytes": self.snapshot_bytes,
            "active_candidates": total,
            "historical_reference_only_count": historical,
            "same_url_extra_rows": sum(count - 1 for count in urls.values()),
            "coverage": {key: data.get(key) for key in (
                "successful_sources", "total_sources", "critical_gap", "coverage_ok",
                "coverage_ratio", "coverage_by_group", "failed_sources")},
            "gmail": {key: newsletter.get(key) for key in (
                "ingested_messages", "retired_historical_messages", "workflow_complete_messages",
                "workflow_incomplete_messages", "unresolved_article_count", "workflow_complete")},
            "page_plan": [{"offset": offset, "limit": min(page_size, total - offset)}
                          for offset in range(0, total, page_size)],
            "index_base": 0,
            "reading_pages_does_not_mark_reviewed": True,
            "omitted_history_is_preserved_in_snapshot": True,
        }

    def screen(self, offset=0, limit=DEFAULT_PAGE_SIZE, summary_chars=DEFAULT_SUMMARY_CHARS,
               include_urls=False):
        if offset < 0 or offset > len(self.candidates):
            raise ValueError("offset is outside the candidate range")
        if limit < 1 or summary_chars < 1:
            raise ValueError("limit and summary_chars must be greater than zero")
        end = min(offset + limit, len(self.candidates))
        rows = []
        for index in range(offset, end):
            original = self.candidates[index]
            full_summary = " ".join(str(original.get("summary") or "").split())
            row = {
                "index": index,
                "title": original.get("title", ""),
                "summary": full_summary[:summary_chars],
                "source": original.get("source", ""),
                "published_at": original.get("published_at"),
            }
            if len(full_summary) > summary_chars:
                row["summary_truncated"] = True
                row["full_summary_chars"] = len(full_summary)
            for flag in ("must_review", "outside_lookback", "policy_revalidation"):
                if original.get(flag):
                    row[flag] = original[flag]
            if original.get("content_updated_at"):
                row["content_updated_at"] = original["content_updated_at"]
            if include_urls:
                row["url"] = original.get("url")
            rows.append(row)
        return {
            **self.identity(),
            "total_candidates": len(self.candidates),
            "page": {"offset": offset, "end_exclusive": end, "returned": end - offset,
                     "next_offset": end if end < len(self.candidates) else None,
                     "candidates_after_page": len(self.candidates) - end},
            "candidates": rows,
        }

    def check_indices(self, indices):
        if any(type(index) is not int or index < 0 or index >= len(self.candidates) for index in indices):
            raise ValueError("each index must be an integer in the snapshot candidate range")
        if len(indices) != len(set(indices)):
            raise ValueError("repeated indices are not allowed")

    def detail(self, indices):
        self.check_indices(indices)
        return {**self.identity(), "candidates": [
            {"index": index, "candidate": self.candidates[index]} for index in indices]}

    def expand_decisions(self, draft):
        if not isinstance(draft, dict) or not isinstance(draft.get("decisions"), list):
            raise ValueError("input must contain a decisions list")
        for key, value in self.identity().items():
            if key in draft and draft[key] != value:
                raise ValueError(f"{key} does not match the selected snapshot")
        decisions = draft["decisions"]
        if any(not isinstance(item, dict) for item in decisions):
            raise ValueError("each decision must be an object")
        self.check_indices([item.get("index") for item in decisions])
        expanded, seen_urls = [], set()
        for item in decisions:
            index = item["index"]
            url = self.candidates[index].get("url")
            if not isinstance(url, str) or not url:
                raise ValueError(f"candidate {index} has no URL")
            if url in seen_urls:
                raise ValueError("multiple decisions refer to the same URL")
            if "url" in item and item["url"] != url:
                raise ValueError(f"decision URL differs from candidate {index}")
            if item.get("status") not in {"reviewed", "delivered", "brief"}:
                raise ValueError("status must be reviewed, delivered, or brief")
            if not isinstance(item.get("reason"), str) or not item["reason"].strip():
                raise ValueError("each decision needs an explicit reason")
            if item["status"] == "delivered" and not item.get("receipt_file"):
                raise ValueError("delivered decisions require receipt_file; ACK will verify it")
            if item.get("duplicate_of") and item["status"] != "reviewed":
                raise ValueError("duplicate_of is valid only for reviewed decisions")
            seen_urls.add(url)
            expanded.append({key: value for key, value in item.items() if key != "index"} | {"url": url})
        return {**self.identity(), "decisions": expanded}


def parse_indices(value):
    try:
        indices = [int(part.strip()) for part in value.split(",")]
    except ValueError as exc:
        raise argparse.ArgumentTypeError("use comma-separated zero-based integers") from exc
    if not indices or any(index < 0 for index in indices):
        raise argparse.ArgumentTypeError("use comma-separated zero-based integers")
    return indices


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--snapshot", type=Path, required=True)
    commands = result.add_subparsers(dest="command", required=True)
    summary = commands.add_parser("summary", help="small coverage summary and complete page plan")
    summary.add_argument("--page-size", type=positive, default=DEFAULT_PAGE_SIZE)
    screen = commands.add_parser("screen", help="all candidates in a page, with no score filtering")
    screen.add_argument("--offset", type=nonnegative, default=0)
    screen.add_argument("--limit", type=positive, default=DEFAULT_PAGE_SIZE)
    screen.add_argument("--summary-chars", type=positive, default=DEFAULT_SUMMARY_CHARS)
    screen.add_argument("--include-urls", action="store_true")
    detail = commands.add_parser("detail", help="complete original fields for selected candidates")
    detail.add_argument("--indices", type=parse_indices, required=True)
    decisions = commands.add_parser("decisions", help="expand index decisions to URLs; no ACK or DB writes")
    decisions.add_argument("--input", type=Path, required=True)
    decisions.add_argument("--output", type=Path, required=True,
                           help="new per-run file; an existing file is never overwritten")
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        packet = RunPacket.load(args.snapshot)
        if args.command == "summary":
            output = packet.summary(args.page_size)
        elif args.command == "screen":
            output = packet.screen(args.offset, args.limit, args.summary_chars, args.include_urls)
        elif args.command == "detail":
            output = packet.detail(args.indices)
        else:
            draft = json.loads(args.input.read_text(encoding="utf-8-sig"))
            expanded = packet.expand_decisions(draft)
            with args.output.open("x", encoding="utf-8") as destination:
                destination.write(compact_json(expanded) + "\n")
            output = {**packet.identity(), "output": str(args.output.resolve()),
                      "decision_count": len(expanded["decisions"]), "ack_performed": False}
        print(compact_json(output))
        return 0
    except (OSError, ValueError) as exc:
        print(compact_json({"error": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
