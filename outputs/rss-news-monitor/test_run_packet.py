import contextlib
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path

from run_packet import RunPacket, compact_json, main


def snapshot():
    return {
        "run_id": "test-run",
        "candidates": [
            {"url": "https://news.example/a", "title": "Zero score still included", "score": 0,
             "summary": "Full fact " * 100, "published_at": None, "must_review": True},
            {"url": "https://news.example/b", "title": "Identical title", "score": 100,
             "summary": "Different fact B", "outside_lookback": True},
            {"url": "https://news.example/c", "title": "Identical title", "score": -1,
             "summary": "Different fact C", "content_updated_at": "2026-09-23"},
        ],
        "operational_scope": {"historical_reference_only_count": 5000,
                              "historical_reference_only": [{"url": "old"}] * 5000},
        "recent_delivered": [{"message": "previous message"}] * 100,
        "critical_gap": True,
        "failed_sources": [{"name": "FERC", "critical": True, "error": "HTTP 403"}],
    }


class RunPacketTests(unittest.TestCase):
    def test_pages_cover_every_candidate_in_original_order(self):
        packet = RunPacket(snapshot())
        pages = packet.summary(page_size=2)["page_plan"]
        self.assertEqual(pages, [{"offset": 0, "limit": 2}, {"offset": 2, "limit": 1}])
        rows = [row for page in pages for row in packet.screen(**page)["candidates"]]
        self.assertEqual([row["index"] for row in rows], [0, 1, 2])
        self.assertEqual(rows[1]["title"], rows[2]["title"])
        self.assertNotEqual(rows[1]["summary"], rows[2]["summary"])
        self.assertTrue(rows[1]["outside_lookback"])
        self.assertEqual(packet.screen(2, 100)["page"]["next_offset"], None)

    def test_compaction_retains_gaps_and_full_detail_without_mutation(self):
        original = snapshot()
        before = copy.deepcopy(original)
        packet = RunPacket(original)
        screen = packet.screen(summary_chars=40)
        self.assertEqual(len(screen["candidates"][0]["summary"]), 40)
        self.assertTrue(screen["candidates"][0]["summary_truncated"])
        self.assertNotIn("url", screen["candidates"][0])
        self.assertEqual(packet.detail([0])["candidates"][0]["candidate"], original["candidates"][0])
        self.assertEqual(packet.screen(include_urls=True)["candidates"][0]["url"], "https://news.example/a")
        summary = packet.summary()
        self.assertEqual(summary["historical_reference_only_count"], 5000)
        self.assertTrue(summary["coverage"]["critical_gap"])
        self.assertEqual(summary["coverage"]["failed_sources"], original["failed_sources"])
        self.assertNotIn("historical_reference_only", summary)
        self.assertNotIn("recent_delivered", summary)
        self.assertEqual(original, before)

    def test_invalid_indices_pages_and_partial_exports_fail(self):
        packet = RunPacket(snapshot())
        for indices in [[-1], [3], [True], [1, 1], [None]]:
            with self.assertRaises(ValueError):
                packet.detail(indices)
        for offset, limit in [(-1, 2), (4, 2), (0, 0)]:
            with self.assertRaises(ValueError):
                packet.screen(offset, limit)
        partial = snapshot() | {"pagination": {"has_more": True}}
        with self.assertRaisesRegex(ValueError, "paged"):
            RunPacket(partial)
        with self.assertRaisesRegex(ValueError, "paged"):
            RunPacket(snapshot() | {"pagination": {"total_candidates": 10}})
        with self.assertRaisesRegex(ValueError, "screening index"):
            RunPacket(snapshot() | {"snapshot_path": "full-snapshot.json"})

    def test_decisions_expand_exact_indices_and_require_evidence(self):
        packet = RunPacket(snapshot())
        draft = {"decisions": [{"index": 0, "status": "reviewed", "reason": "Concrete irrelevant topic"},
                                {"index": 2, "status": "delivered", "reason": "New confirmed change",
                                 "receipt_file": "receipt.json"}]}
        expanded = packet.expand_decisions(draft)
        self.assertEqual(expanded["run_id"], "test-run")
        self.assertEqual(expanded["decisions"][1]["url"], "https://news.example/c")
        self.assertNotIn("index", expanded["decisions"][0])
        with self.assertRaisesRegex(ValueError, "receipt"):
            packet.expand_decisions({"decisions": [{"index": 0, "status": "delivered", "reason": "News"}]})
        with self.assertRaisesRegex(ValueError, "run_id"):
            packet.expand_decisions(draft | {"run_id": "another-run"})
        with self.assertRaisesRegex(ValueError, "snapshot_sha256"):
            packet.expand_decisions(draft | {"snapshot_sha256": "different"})
        with self.assertRaisesRegex(ValueError, "differs"):
            packet.expand_decisions({"decisions": [draft["decisions"][0] | {"url": "wrong"}]})

    def test_decisions_cli_never_overwrites_or_acks(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            saved = root / "snapshot.json"
            draft = root / "draft.json"
            output = root / "decision-new.json"
            saved.write_text(compact_json(snapshot()), encoding="utf-8")
            draft.write_text(compact_json({"decisions": [{"index": 1, "status": "reviewed",
                                                          "reason": "Published old facts only"}]}), encoding="utf-8")
            args = ["--snapshot", str(saved), "decisions", "--input", str(draft), "--output", str(output)]
            stdout, stderr = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                self.assertEqual(main(args), 0)
                first = output.read_bytes()
                self.assertEqual(main(args), 2)
                self.assertEqual(first, output.read_bytes())
            self.assertFalse(json.loads(stdout.getvalue())["ack_performed"])
            self.assertEqual(json.loads(first)["decisions"][0]["url"], "https://news.example/b")


if __name__ == "__main__":
    unittest.main()
