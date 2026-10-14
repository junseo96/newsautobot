import datetime as dt
import json
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from v12_controls import verified_publication_is_fresh
from v11_runtime import Queue


class V12FreshnessTests(unittest.TestCase):
    def test_fresh_feed_cannot_revive_old_original(self):
        now=dt.datetime(2026,9,28,6,tzinfo=dt.timezone.utc).timestamp()
        self.assertFalse(verified_publication_is_fresh({'source_published_at':'2026-07-01'}, {}, now))
        self.assertTrue(verified_publication_is_fresh({'source_published_at':'2026-09-28'}, {}, now))
    def test_newsletter_exception_uses_actual_received_date(self):
        now=dt.datetime(2026,9,28,6,tzinfo=dt.timezone.utc).timestamp()
        mail={'newsletter_received_at':'2026-09-28T04:00:00+00:00'}
        self.assertTrue(verified_publication_is_fresh({'source_published_at':'2026-09-27T08:00:00+00:00'},mail,now))
        self.assertFalse(verified_publication_is_fresh({'source_published_at':'2026-09-26T08:00:00+00:00'},mail,now))
    def test_future_exact_time_rejected(self):
        now=dt.datetime(2026,9,28,6,tzinfo=dt.timezone.utc).timestamp()
        self.assertFalse(verified_publication_is_fresh({'source_published_at':'2026-09-30T08:00:00+00:00'}, {}, now))
    def test_date_only_korean_morning_not_rejected_as_future(self):
        now=dt.datetime.fromisoformat('2026-09-29T06:00:00+09:00').timestamp()
        self.assertTrue(verified_publication_is_fresh({'source_published_at':'2026-09-29'}, {}, now))
        self.assertFalse(verified_publication_is_fresh({'source_published_at':'2026-09-30'}, {}, now))


class V12QueueTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.queue=Queue(Path(self.temp.name)/'queue.db')
        self.candidate={'url':'https://example.com/item','title':'New transformer contract','summary':'2GW awarded','published_at':'2026-09-28T00:00:00+00:00'}
    def add(self,candidate):
        return self.queue.enqueue({'candidates':[candidate]},'snapshot.json')
    def test_crawl_timestamp_churn_does_not_repeat_model_review(self):
        self.add(self.candidate)
        self.queue.finish(self.queue.take(1)[0],'reviewed','Verified non-material update',{'action':'reviewed'})
        self.assertEqual(self.add({**self.candidate,'content_updated_at':'2026-09-28T01:00:00Z'}),0)
        self.assertEqual(self.queue.counts(),{'reviewed':1})
    def test_reverting_to_completed_version_does_not_repeat_review(self):
        self.add(self.candidate)
        self.queue.finish(self.queue.take(1)[0],'reviewed','Verified non-material update',{'action':'reviewed'})
        self.add({**self.candidate,'summary':'3GW awarded'})
        self.assertEqual(self.add(self.candidate),0)
        self.assertEqual(self.queue.counts(),{'reviewed':1})
    def test_changed_metadata_cannot_clear_uncertain_send(self):
        self.add(self.candidate)
        self.queue.finish(self.queue.take(1)[0],'delivery_uncertain','Attempt must reconcile')
        self.assertEqual(self.add({**self.candidate,'title':'Updated contract title'}),0)
        self.assertEqual(self.queue.counts(),{'delivery_uncertain':1})
    def test_date_only_is_not_assumed_to_have_expired_at_noon(self):
        now=dt.datetime(2026,9,28,17,tzinfo=dt.timezone.utc).timestamp()
        self.queue.set('realtime_start_epoch',now-4*86400)
        with patch('v11_runtime.time.time',return_value=now):
            self.assertEqual(self.add({**self.candidate,'publication_precision':'date','first_seen_at':'2026-09-28T17:00:00Z'}),1)
    def test_date_only_queue_accepts_korean_morning(self):
        now=dt.datetime.fromisoformat('2026-09-28T06:00:00+09:00').timestamp()
        self.queue.set('realtime_start_epoch',now-4*86400)
        with patch('v11_runtime.time.time',return_value=now):
            self.assertEqual(self.add({**self.candidate,'publication_precision':'date','first_seen_at':'2026-09-27T21:00:00Z'}),1)


if __name__=='__main__':unittest.main()
