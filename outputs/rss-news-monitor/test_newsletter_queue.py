import datetime as dt
import importlib.util
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("newsletter_queue", Path(__file__).with_name("newsletter_queue.py"))
QUEUE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(QUEUE)


def make_item(src, url, title, summary, published):
    return {"source": src["name"], "source_url": src["url"], "url": url.rstrip("/"),
            "title": title, "summary": summary, "published_at": published,
            "primary": src["primary"], "must_review": src["must_review"]}


def parse_date(value):
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class NewsletterQueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "mail.json"
        self.message = {"message_id": "eia860-1", "source": "EIA Electricity", "source_url": "https://www.eia.gov/",
                        "primary": True, "must_review": True,
                        "articles": [{"url": "https://www.eia.gov/electricity/data/eia860m/", "title": "New generator inventory",
                                      "summary": "Monthly unit-level capacity inventory release", "published_at": "2026-09-10T20:00:00Z"}]}

    def load(self, messages=None):
        self.path.write_text(json.dumps({"schema_version": 1, "messages": messages if messages is not None else [self.message]}), encoding="utf-8")
        return QUEUE.load_newsletter_results(self.path, make_item, parse_date)

    def db(self):
        con = sqlite3.connect(":memory:")
        self.addCleanup(con.close)
        con.execute("CREATE TABLE articles(url TEXT PRIMARY KEY)")
        return con

    def insert(self, con, results):
        for result in results:
            con.executemany("INSERT OR IGNORE INTO articles(url) VALUES(?)", [(x["url"],) for x in result["items"]])

    def test_official_eia_notice_becomes_mandatory_primary_candidate(self):
        result = self.load()[0]
        self.assertTrue(result["ok"])
        self.assertEqual(result["source"]["name"], "Gmail:EIA Electricity")
        self.assertEqual(result["source"]["kind"], "newsletter")
        self.assertTrue(result["items"][0]["primary"])
        self.assertTrue(result["items"][0]["must_review"])
        self.assertIsInstance(result["items"][0]["published_at"], dt.datetime)

    def test_actual_gmail_receipt_is_preserved_for_newsletter_lane(self):
        self.message['received_at']='2026-09-24T14:00:00+00:00'
        self.path.write_text(json.dumps({'schema_version':1,'messages':[self.message]}),encoding='utf-8')
        results=QUEUE.load_newsletter_results(self.path,make_item,parse_date,received_after_epoch=0)
        con=self.db(); self.insert(con,results)
        QUEUE.journal_newsletter_results(con,results,'run-1')
        self.assertEqual(con.execute('SELECT received_at FROM newsletter_messages').fetchone()[0],self.message['received_at'])

    def test_spoofed_primary_flag_does_not_create_agency_evidence(self):
        self.message["source_url"] = "https://eia.gov.fake.example/"
        self.message["articles"][0]["url"] = "https://eia.gov.fake.example/release"
        result = self.load()[0]
        self.assertFalse(result["source"]["primary"])
        self.assertFalse(result["items"][0]["primary"])

    def test_official_source_with_third_party_links_is_not_marked_primary(self):
        self.message["articles"][0]["url"] = "https://news.example/energy"
        self.assertFalse(self.load()[0]["source"]["primary"])

    def test_invalid_later_message_rejects_whole_extraction(self):
        bad = {**self.message, "message_id": "mail-2", "source": ""}
        with self.assertRaisesRegex(ValueError, "source name"):
            self.load([self.message, bad])

    def test_invalid_ids_urls_dates_and_empty_extractions_rejected(self):
        cases = [
            ({**self.message, "message_id": ""}, "message_id"),
            ({**self.message, "articles": []}, "non_article_reason"),
            ({**self.message, "articles": [{"url": "file:///secret", "title": "News"}]}, "HTTP"),
            ({**self.message, "articles": [{"url": "https://name:secret@www.eia.gov/x", "title": "News"}]}, "credentials"),
            ({**self.message, "articles": [{"url": "https://www.eia.gov/x", "title": "News", "published_at": "nonsense"}]}, "published_at"),
        ]
        for message, error in cases:
            with self.subTest(error=error), self.assertRaisesRegex(ValueError, error):
                self.load([message])

    def test_missing_file_is_error_not_zero_news(self):
        with self.assertRaises(FileNotFoundError):
            QUEUE.load_newsletter_results(self.path, make_item, parse_date)

    def test_explicit_non_news_classification_is_journaled_without_fake_articles(self):
        self.message["articles"] = []
        self.message["non_article_reason"] = "Subscription confirmation only; full message reviewed"
        results = self.load()
        self.assertEqual(results[0]["items"], [])
        con = self.db()
        counts = QUEUE.journal_newsletter_results(con, results, "run-1")
        con.commit()
        self.assertEqual(counts["confirmed_message_ids"], ["eia860-1"])
        self.assertEqual(counts["article_count"], 0)
        self.assertEqual(con.execute("SELECT classification_reason FROM newsletter_messages").fetchone()[0], self.message["non_article_reason"])
        self.assertEqual(QUEUE.unimported_newsletter_results(con, results), [])

    def test_non_news_reason_cannot_hide_extracted_articles(self):
        self.message["non_article_reason"] = "Not news"
        with self.assertRaisesRegex(ValueError, "only for"):
            self.load()

    def test_message_marked_only_after_articles_exist_and_commit(self):
        results = self.load()
        con = self.db()
        with self.assertRaisesRegex(ValueError, "absent"):
            QUEUE.journal_newsletter_results(con, results, "run-1")
        self.assertEqual(con.execute("SELECT count(*) FROM newsletter_messages").fetchone()[0], 0)
        self.insert(con, results)
        counts = QUEUE.journal_newsletter_results(con, results, "run-1")
        self.assertEqual(counts["imported_messages"], 1)
        self.assertEqual(counts["confirmed_message_ids"], ["eia860-1"])
        con.rollback()
        self.assertEqual(con.execute("SELECT count(*) FROM newsletter_messages").fetchone()[0], 0)
        self.assertEqual(con.execute("SELECT count(*) FROM articles").fetchone()[0], 0)

    def test_idempotent_input_and_persisted_url_associations(self):
        results = self.load()
        con = self.db()
        self.insert(con, results)
        QUEUE.journal_newsletter_results(con, results, "run-1")
        con.commit()
        counts = QUEUE.journal_newsletter_results(con, results, "run-2")
        self.assertEqual(counts["already_imported_messages"], 1)
        self.assertEqual(counts["imported_messages"], 0)
        self.assertEqual(con.execute("SELECT count(*) FROM newsletter_messages").fetchone()[0], 1)
        self.assertEqual(con.execute("SELECT article_url FROM newsletter_message_articles").fetchone()[0], results[0]["items"][0]["url"])

    def test_old_persistent_input_not_replayed_over_newer_monthly_release(self):
        results = self.load()
        con = self.db()
        self.assertEqual(len(QUEUE.unimported_newsletter_results(con, results)), 1)
        self.insert(con, results)
        QUEUE.journal_newsletter_results(con, results, "run-1")
        con.commit()
        self.assertEqual(QUEUE.unimported_newsletter_results(con, results), [])
        self.message["message_id"] = "next-month-2"
        self.message["articles"][0]["published_at"] = "2026-10-10T20:00:00Z"
        self.assertEqual(len(QUEUE.unimported_newsletter_results(con, self.load())), 1)

    def test_changed_message_and_uninserted_later_article_never_partially_journal(self):
        results = self.load()
        con = self.db()
        self.insert(con, results)
        QUEUE.journal_newsletter_results(con, results, "run-1")
        con.commit()
        self.message["articles"][0]["summary"] = "Changed extraction"
        with self.assertRaisesRegex(ValueError, "changed"):
            QUEUE.journal_newsletter_results(con, self.load(), "run-2")
        new = {**self.message, "message_id": "new-2", "articles": [{"url": "https://www.eia.gov/new", "title": "New"}]}
        another = {**self.message, "message_id": "new-3", "articles": [{"url": "https://www.eia.gov/missing", "title": "Missing"}]}
        staged = self.load([new, another])
        self.insert(con, staged[:1])
        with self.assertRaisesRegex(ValueError, "absent"):
            QUEUE.journal_newsletter_results(con, staged, "run-2")
        self.assertEqual(con.execute("SELECT count(*) FROM newsletter_messages").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
