"""Regressions for false delivery, stale acknowledgements and silent exclusion."""
import contextlib
import datetime as dt
import hashlib
import importlib.util
import io
import json
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import project_paths
from argparse import Namespace
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("review_state", Path(__file__).with_name("review_state.py"))
REVIEW = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REVIEW)


def schema(con):
    con.executescript("""
    CREATE TABLE IF NOT EXISTS articles(
      url TEXT PRIMARY KEY,status TEXT,delivered_at TEXT,reviewed_at TEXT,
      decision_policy_version INTEGER DEFAULT 0,decision_reason TEXT,
      title TEXT DEFAULT 'Grid approval',summary TEXT DEFAULT '2GW capacity',published_at TEXT);
    CREATE TABLE IF NOT EXISTS source_runs(id INTEGER PRIMARY KEY,run_id TEXT);
    """)


class ReviewStateTests(unittest.TestCase):
    def test_migrated_receipt_and_snapshot_recovery_are_idempotent(self):
        body = self.root / 'sent.txt'
        self.receipt()
        receipt_data = json.loads((self.root/'receipt.json').read_text())
        body.write_bytes(receipt_data['message_text'].encode('utf-8'))
        old_receipt = str(project_paths.LEGACY_ROOT / 'receipt.json')
        receipt_data['message_file'] = str(project_paths.LEGACY_ROOT / 'sent.txt')
        self.write(self.root/'receipt.json',receipt_data)
        self.batch_data['run_files']['snapshot'] = str(project_paths.LEGACY_ROOT / 'batch.json')
        self.write(self.batch,self.batch_data)
        decisions = [{'url':self.urls[0],'status':'delivered','reason':'New 2GW approval','receipt_file':old_receipt}]
        with patch.object(project_paths,'ROOT',self.root):
            self.ack(decisions)
            # Model a preserved old DB row whose path must not be rewritten.
            with self.connection() as con:
                con.execute('UPDATE decision_history SET receipt_file=?',(old_receipt,))
            self.write(self.decisions,{'run_id':'run-1','decisions':decisions})
            args = self.args()
            args.recover_deliveries = True
            with contextlib.redirect_stdout(io.StringIO()):
                REVIEW.acknowledge(args,lambda u:u.rstrip('/'),schema)
            with self.connection() as con:
                self.assertEqual(con.execute('SELECT count(*) FROM delivery_history').fetchone()[0],1)
                self.assertEqual(con.execute('SELECT receipt_file FROM decision_history').fetchone()[0],old_receipt)
            body.write_bytes(b'tampered body')
            with self.assertRaises(ValueError):
                REVIEW.validate_receipt(old_receipt,self.urls[0],lambda u:u.rstrip('/'),dt.datetime.fromisoformat(self.generated))

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = self.root / "state.db"
        self.urls = [f"https://example.com/{x}" for x in ("send", "review", "brief", "untouched", "outside")]
        self.generated = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=2)).isoformat()
        self.batch = self.root / "batch.json"
        self.batch_data = {"run_id": "run-1", "policy_version": 5, "generated_at_kst": self.generated, "run_files": {"snapshot": str(self.batch)}, "candidates": [{"url": x, "title": "Grid approval", "summary": "2GW capacity"} for x in self.urls[:-1]]}
        self.write(self.batch, self.batch_data)
        self.config = self.root / "config.json"
        self.write(self.config, {"selection_policy_version": 5})
        self.decisions = self.root / "decisions.json"
        con = sqlite3.connect(self.db)
        schema(con)
        con.executemany("INSERT INTO articles(url,status) VALUES(?,'pending')", [(x,) for x in self.urls])
        con.execute("INSERT INTO source_runs(run_id) VALUES('run-1')")
        con.commit()
        con.close()

    def write(self, path, payload):
        path.write_text(json.dumps(payload), encoding="utf-8")

    @contextlib.contextmanager
    def connection(self):
        con = sqlite3.connect(self.db)
        try:
            yield con
            con.commit()
        finally:
            con.close()

    def receipt(self, url=None, **overrides):
        message = "**[송전망 투자 승인]**\n\n**- 2GW 계통 증설 승인**\n\n1. 2028년 준공 계획\n\n링크: https://example.com/send"
        path = self.root / "receipt.json"
        value = {
            "schema_version": 1, "status": "complete", "message_file": None,
            "message_text": message,
            "message_sha256": hashlib.sha256(message.encode("utf-8")).hexdigest(),
            "article_urls": [url or self.urls[0]],
            "sent_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "telegram_message_ids": [501],
        }
        value.update(overrides)
        self.write(path, value)
        return str(path)

    def args(self):
        return Namespace(config=self.config, db=self.db, batch=self.batch,
                         decision_file=self.decisions, delivered_url=[], reviewed_url=[], brief_url=[])

    def ack(self, decisions, run_id="run-1"):
        self.write(self.decisions, {"run_id": run_id, "decisions": decisions})
        with contextlib.redirect_stdout(io.StringIO()):
            return REVIEW.acknowledge(self.args(), lambda value: value.rstrip("/"), schema)

    def states(self):
        with self.connection() as con:
            return dict(con.execute("SELECT url,status FROM articles"))

    def test_atomic_success_records_receipt_text_and_leaves_unprocessed_pending(self):
        self.ack([
            {"url": self.urls[0], "status": "delivered", "reason": "New 2GW approval", "receipt_file": self.receipt()},
            {"url": self.urls[1], "status": "reviewed", "reason": "No power-industry facts in full text"},
            {"url": self.urls[2], "status": "brief", "reason": "Useful long-form research for morning"},
        ])
        self.assertEqual([self.states()[x] for x in self.urls], ["delivered", "reviewed", "brief", "pending", "pending"])
        with self.connection() as con:
            message, ids = con.execute("SELECT message_text,telegram_message_ids FROM delivery_history").fetchone()
            self.assertIn("2GW", message)
            self.assertEqual(json.loads(ids), [501])
            self.assertEqual(con.execute("SELECT count(*) FROM decision_history").fetchone()[0], 3)

    def test_one_invalid_url_rolls_back_all_valid_decisions(self):
        with self.assertRaisesRegex(ValueError, "not a candidate"):
            self.ack([
                {"url": self.urls[1], "status": "reviewed", "reason": "Unrelated subject"},
                {"url": self.urls[-1], "status": "reviewed", "reason": "Old stale file"},
            ])
        self.assertTrue(all(x == "pending" for x in self.states().values()))

    def test_old_decision_run_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Stale decision"):
            self.ack([], run_id="run-0")

    def test_old_snapshot_rejected_after_new_collection(self):
        with self.connection() as con:
            con.execute("INSERT INTO source_runs(run_id) VALUES('run-2')")
        with self.assertRaisesRegex(ValueError, "Stale batch"):
            self.ack([])

    def test_page_can_ack_candidates_in_matching_full_snapshot(self):
        snapshot = self.root / "snapshot.json"
        self.write(snapshot, self.batch_data)
        self.write(self.batch, {**self.batch_data, "candidates": [], "pagination": {"snapshot_path": str(snapshot)}})
        self.ack([{"url": self.urls[1], "status": "reviewed", "reason": "Unrelated full-text subject"}])
        self.assertEqual(self.states()[self.urls[1]], "reviewed")

    def test_delivered_without_receipt_rejected(self):
        with self.assertRaisesRegex(ValueError, "receipt_file"):
            self.ack([{"url": self.urls[0], "status": "delivered", "reason": "Assumed successful"}])

    def test_partial_wrong_url_tampered_or_old_receipt_rejected(self):
        cases = [
            ({"status": "partial"}, "complete Telegram"),
            ({"article_urls": [self.urls[1]]}, "does not cover"),
            ({"message_sha256": "0" * 64}, "hash"),
            ({"telegram_message_ids": []}, "message IDs"),
            ({"sent_at": "2020-01-01T00:00:00Z"}, "predates"),
        ]
        for overrides, error in cases:
            with self.subTest(overrides=overrides), self.assertRaisesRegex(ValueError, error):
                self.ack([{"url": self.urls[0], "status": "delivered", "reason": "New approval", "receipt_file": self.receipt(**overrides)}])
        self.assertEqual(self.states()[self.urls[0]], "pending")

    def test_altered_message_file_rejected(self):
        path = self.root / "message.txt"
        path.write_text("Different unsent content", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "changed"):
            self.ack([{"url": self.urls[0], "status": "delivered", "reason": "New approval", "receipt_file": self.receipt(message_file=str(path))}])

    def test_legacy_delivered_status_is_not_duplicate_evidence(self):
        with self.connection() as con:
            con.execute("UPDATE articles SET status='delivered' WHERE url=?", (self.urls[0],))
        with self.assertRaisesRegex(ValueError, "receipt-backed"):
            self.ack([{"url": self.urls[1], "status": "reviewed", "reason": "Duplicate event", "duplicate_of": self.urls[0]}])

    def test_legacy_recovery_requires_exact_direct_link_and_backfills_history(self):
        with self.connection() as con:
            con.execute("UPDATE articles SET status='delivered' WHERE url=?", (self.urls[0],))
        receipt = json.loads((self.root / 'receipt.json').read_text()) if (self.root / 'receipt.json').exists() else None
        if receipt is None:
            self.receipt()
            receipt = json.loads((self.root / 'receipt.json').read_text())
        mapping = self.root / 'legacy-mapping.json'
        self.write(mapping, {'mappings': [{'url': self.urls[0], 'receipt_file': str(self.root / 'receipt.json')}]})
        args = Namespace(db=self.db, mapping_file=mapping)
        with contextlib.redirect_stdout(io.StringIO()):
            REVIEW.recover_legacy_direct_link_deliveries(args, lambda value: value.rstrip('/'), schema)
        with self.connection() as con:
            self.assertEqual(con.execute('SELECT count(*) FROM delivery_history WHERE url=?', (self.urls[0],)).fetchone()[0], 1)
        self.assertEqual(json.loads((self.root / 'receipt.json').read_text())['article_urls'], [self.urls[0]])

    def test_legacy_recovery_rejects_title_only_receipt_match(self):
        with self.connection() as con:
            con.execute("UPDATE articles SET status='delivered' WHERE url=?", (self.urls[0],))
        self.receipt(message_text="**[Grid approval]**\nSame title, but no publisher link", message_sha256=hashlib.sha256("**[Grid approval]**\nSame title, but no publisher link".encode()).hexdigest())
        mapping = self.root / 'legacy-mapping.json'
        self.write(mapping, {'mappings': [{'url': self.urls[0], 'receipt_file': str(self.root / 'receipt.json')}]})
        with self.assertRaisesRegex(ValueError, "exact publisher URL"):
            REVIEW.recover_legacy_direct_link_deliveries(Namespace(db=self.db, mapping_file=mapping), lambda value: value.rstrip('/'), schema)

    def test_duplicate_requires_explicit_evidence_but_verified_reference_works(self):
        with self.assertRaisesRegex(ValueError, "duplicate_of"):
            self.ack([{"url": self.urls[1], "status": "reviewed", "reason": "이전 보도와 유사"}])
        self.ack([{"url": self.urls[0], "status": "delivered", "reason": "New approval", "receipt_file": self.receipt()}])
        self.ack([{"url": self.urls[1], "status": "reviewed", "reason": "Exact duplicate, no new capacity or approval", "duplicate_of": self.urls[0]}])
        self.assertEqual(self.states()[self.urls[1]], "reviewed")

    def test_idempotent_ack_does_not_duplicate_delivery_history(self):
        decision = {"url": self.urls[0], "status": "delivered", "reason": "New approval", "receipt_file": self.receipt()}
        self.ack([decision])
        self.ack([decision])
        with self.connection() as con:
            self.assertEqual(con.execute("SELECT count(*) FROM delivery_history").fetchone()[0], 1)

    def test_reopened_url_can_reference_its_own_previous_receipt(self):
        self.ack([{"url": self.urls[0], "status": "delivered", "reason": "New approval", "receipt_file": self.receipt()}])
        self.batch_data["run_id"] = "run-2"
        self.write(self.batch, self.batch_data)
        with self.connection() as con:
            con.execute("INSERT INTO source_runs(run_id) VALUES('run-2')")
            con.execute("UPDATE articles SET status='pending' WHERE url=?", (self.urls[0],))
        self.ack([{"url": self.urls[0], "status": "reviewed", "reason": "Duplicate facts; cosmetic source correction only", "duplicate_of": self.urls[0]}], run_id="run-2")
        self.assertEqual(self.states()[self.urls[0]], "reviewed")
        with self.connection() as con:
            self.assertEqual(con.execute("SELECT count(*) FROM delivery_history").fetchone()[0], 1)

    def test_legacy_url_files_cannot_claim_success_and_are_batch_bound(self):
        args = self.args()
        args.decision_file = None
        args.delivered_url = [self.urls[0]]
        with self.assertRaisesRegex(ValueError, "disabled"):
            REVIEW.acknowledge(args, lambda value: value, schema)
        args.delivered_url = []
        args.reviewed_url = [self.urls[-1]]
        with self.assertRaisesRegex(ValueError, "not a candidate"):
            REVIEW.acknowledge(args, lambda value: value, schema)

    def test_policy_change_and_missing_reason_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "specific editorial reason"):
            self.ack([{"url": self.urls[1], "status": "reviewed", "reason": ""}])
        self.write(self.config, {"selection_policy_version": 6})
        with self.assertRaisesRegex(ValueError, "policy changed"):
            self.ack([])

    def recover(self, decisions):
        self.write(self.decisions, {"run_id": "run-1", "decisions": decisions})
        args = self.args()
        args.recover_deliveries = True
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            REVIEW.acknowledge(args, lambda value: value.rstrip("/"), schema)
        return json.loads(output.getvalue())

    def test_recover_crash_after_send_even_after_new_run_and_policy(self):
        receipt = self.receipt()
        with self.connection() as con:
            con.execute("INSERT INTO source_runs(run_id) VALUES('run-2')")
        self.write(self.config, {"selection_policy_version": 6})
        decision = {"url": self.urls[0], "status": "delivered", "reason": "Recovered actual delivery after interruption", "receipt_file": receipt}
        result = self.recover([decision])
        self.assertEqual(result["recovered_history"], 1)
        self.assertEqual(result["delivered"], 1)
        self.assertEqual(self.states()[self.urls[0]], "delivered")
        self.assertEqual(self.recover([{**decision, "reason": "Recovered receipt again"}])["already_recorded"], 1)

    def test_recovery_of_old_facts_keeps_changed_article_pending(self):
        receipt = self.receipt()
        with self.connection() as con:
            con.execute("INSERT INTO source_runs(run_id) VALUES('run-2')")
            con.execute("UPDATE articles SET summary='Capacity increased to 4GW' WHERE url=?", (self.urls[0],))
        result = self.recover([{"url": self.urls[0], "status": "delivered", "reason": "Old 2GW notification sent", "receipt_file": receipt}])
        self.assertEqual(result["recovered_history"], 1)
        self.assertEqual(result["current_revision_preserved"], 1)
        self.assertEqual(result["delivered"], 0)
        self.assertEqual(self.states()[self.urls[0]], "pending")
        with self.connection() as con:
            self.assertIn("2GW", con.execute("SELECT message_text FROM delivery_history").fetchone()[0])

    def test_recovery_rejects_non_delivery_and_live_page(self):
        with self.assertRaisesRegex(ValueError, "only receipt-backed delivered"):
            self.recover([{"url": self.urls[1], "status": "reviewed", "reason": "Old article"}])
        self.batch_data["run_files"]["snapshot"] = str(self.root / "different-snapshot.json")
        self.write(self.batch, self.batch_data)
        with self.assertRaisesRegex(ValueError, "immutable run snapshot"):
            self.recover([])

    def test_recovery_preserves_new_monthly_release_on_same_url_and_title(self):
        receipt = self.receipt()
        with self.connection() as con:
            con.execute("INSERT INTO source_runs(run_id) VALUES('run-2')")
            con.execute("UPDATE articles SET published_at='2026-09-11T00:00:00Z' WHERE url=?", (self.urls[0],))
        result = self.recover([{"url": self.urls[0], "status": "delivered", "reason": "Previous monthly release", "receipt_file": receipt}])
        self.assertEqual(result["current_revision_preserved"], 1)
        self.assertEqual(self.states()[self.urls[0]], "pending")


if __name__ == "__main__":
    unittest.main()
