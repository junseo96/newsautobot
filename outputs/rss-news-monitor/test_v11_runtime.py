"""Durable V11 queue and delivery-window tests, isolated from production state."""
import datetime as dt
import hashlib
import json
from contextlib import closing
import sqlite3
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from v11_runtime import KST, Queue, fingerprint, may_send, normal_window, scheduled_brief_slot
from reset_v11_queue import reset


class DeliveryWindowTests(unittest.TestCase):
    def setUp(self):
        self.config = {"normal_delivery_window_kst": {"start": "06:00", "end": "21:00"},
                       "urgent_delivery_24h": True,
                       "delivery_mode": "important_realtime_standard_scheduled_briefs",
                       "standard_brief_times_kst": ["06:00", "10:00", "14:00", "18:00"],
                       "standard_brief_grace_minutes": 90}

    def at(self, hour, minute=0, second=0):
        return dt.datetime(2026, 9, 24, hour, minute, second, tzinfo=KST)

    def test_normal_window_boundary_minutes(self):
        for hour, minute, expected in ((0, 0, False), (5, 59, False), (6, 0, True),
                                       (12, 0, True), (20, 59, True), (21, 0, True),
                                       (21, 1, False), (23, 59, False)):
            with self.subTest(hour=hour, minute=minute):
                self.assertIs(normal_window(self.config, self.at(hour, minute)), expected)

    def test_normal_window_uses_kst_for_utc_input(self):
        self.assertTrue(normal_window(self.config, dt.datetime(2026, 9, 23, 21, 0, tzinfo=dt.timezone.utc)))
        self.assertFalse(normal_window(self.config, dt.datetime(2026, 9, 23, 20, 59, tzinfo=dt.timezone.utc)))

    def test_urgent_send_allowed_overnight_but_standard_held(self):
        for hour in (0, 5, 22, 23):
            with self.subTest(hour=hour):
                self.assertTrue(may_send({"action": "send", "urgency": "immediate"}, self.config, self.at(hour)))
                self.assertFalse(may_send({"action": "send", "urgency": "standard"}, self.config, self.at(hour)))

    def test_overnight_urgent_requires_config_true(self):
        for value in (False, "true", None):
            config = dict(self.config, urgent_delivery_24h=value)
            self.assertFalse(may_send({"urgency": "immediate"}, config, self.at(23)))

    def test_only_immediate_sends_outside_scheduled_brief(self):
        self.assertTrue(may_send({"urgency": "immediate"}, self.config, self.at(9)))
        self.assertFalse(may_send({"urgency": "standard"}, self.config, self.at(9)))

    def test_standard_brief_slots_and_grace(self):
        expected = ((5, 59, None), (6, 0, "06:00"), (7, 30, "06:00"),
                    (7, 31, None), (10, 15, "10:00"), (14, 0, "14:00"),
                    (18, 45, "18:00"), (19, 31, None), (23, 0, None))
        for hour, minute, suffix in expected:
            with self.subTest(hour=hour, minute=minute):
                slot=scheduled_brief_slot(self.config,self.at(hour,minute))
                self.assertEqual(slot.split('T')[1][:5] if slot else None,suffix)


class DurableQueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="newsflow-v11-queue-test-")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "queue.db"
        self.queue = Queue(self.path)
        self.clock = patch("v11_runtime.time.time", return_value=1000)
        self.time = self.clock.start()
        self.addCleanup(self.clock.stop)

    def candidate(self, number=1, **changes):
        return {"url": f"https://example.com/article-{number}", "title": f"Grid update {number}",
                "summary": "New industrial development", "published_at": "2026-09-24T06:00:00+09:00", **changes}

    def enqueue(self, *candidates, path="run-1/snapshot.json"):
        return self.queue.enqueue({"run_id": Path(path).parent.name, "candidates": list(candidates)}, path)

    def stored(self, url):
        with self.queue.connect() as con:
            return dict(con.execute("SELECT * FROM jobs WHERE url=?", (url,)).fetchone())

    def test_date_only_dart_filing_uses_discovery_order_not_midnight(self):
        self.time.return_value = dt.datetime(2026, 10, 1, 1, 10, tzinfo=dt.timezone.utc).timestamp()
        exact = self.candidate(1, published_at="2026-10-01T00:00:00+00:00", score=70, must_review=True)
        filing = self.candidate(2, published_at="2026-10-01", publication_precision="date",
                                score=70, must_review=True)
        self.enqueue(exact, filing)
        self.assertEqual(self.queue.take(1)[0]["url"], filing["url"])

    def test_fingerprint_tracks_content_but_ignores_discovery_score(self):
        base = self.candidate()
        self.assertEqual(fingerprint(base), fingerprint(dict(base, score=100, source="Another feed")))
        for key, value in (("url", "https://example.com/other"), ("title", "Changed decision"),
                           ("summary", "Changed contractual capacity"), ("published_at", "2026-09-24T07:00:00+09:00")):
            with self.subTest(key=key):
                self.assertNotEqual(fingerprint(base), fingerprint(dict(base, **{key: value})))
        self.assertEqual(fingerprint(base), fingerprint(dict(base,content_updated_at='2026-09-24T07:30:00+09:00')))

    def test_kpx_views_and_new_badge_do_not_change_fingerprint(self):
        url="https://new.kpx.or.kr/gallery.es?act=view&list_no=220"
        base=self.candidate(url=url,title="새글 [보도자료] 안정적 전력공급 작성일 2026/09/28 조회수 33")
        for title in ("[보도자료] 안정적 전력공급 작성일 2026/09/28 조회수 65","[보도자료] 안정적 전력공급"):
            self.assertEqual(fingerprint(base),fingerprint(dict(base,title=title)))
        for changes in ({"title":"[보도자료] 전력공급 차질"},{"summary":"Changed real industrial facts"},{"published_at":"2026-09-29T00:00:00+00:00"}):
            self.assertNotEqual(fingerprint(base),fingerprint(dict(base,**changes)))
        external=dict(base,url="https://example.com/gallery.es?act=view&list_no=220")
        self.assertNotEqual(fingerprint(external),fingerprint(dict(external,title=external["title"].replace("33","65"))))

    def test_kpx_completed_legacy_hash_migrates_without_reopening(self):
        candidate=self.candidate(url="https://new.kpx.or.kr/gallery.es?act=view&list_no=220",
                                 title="새글 [보도자료] 안정적 전력공급 작성일 2026/09/28 조회수 33")
        self.enqueue(candidate)
        job=self.queue.take(1)[0]
        result={"action":"reviewed","reason":"No new industrial fact"}
        self.queue.finish(job,"reviewed","Completed review",result)
        legacy=hashlib.sha256(json.dumps({k:candidate.get(k) for k in ('url','title','summary','published_at')},sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        with self.queue.connect() as con:
            con.execute('UPDATE jobs SET fingerprint=? WHERE url=?',(legacy,candidate['url']))
            con.execute('UPDATE completed_versions SET fingerprint=? WHERE url=?',(legacy,candidate['url']))
        self.assertEqual(self.enqueue(dict(candidate,title=candidate['title'].replace('33','65')),path='run-2/snapshot.json'),0)
        row=self.stored(candidate['url'])
        self.assertEqual(row['status'],'reviewed')
        self.assertEqual(json.loads(row['result']),result)
        self.assertEqual(row['fingerprint'],fingerprint(candidate))
        self.assertEqual(self.queue.take(1),[])
        with self.queue.connect() as con:
            hashes={r[0] for r in con.execute('SELECT fingerprint FROM completed_versions WHERE url=?',(candidate['url'],))}
        self.assertEqual(hashes,{legacy,fingerprint(candidate)})

    def test_proven_completed_alias_restores_normalized_pending_but_not_real_change(self):
        candidate=self.candidate(url="https://new.kpx.or.kr/gallery.es?act=view&list_no=220",
                                 title="새글 [보도자료] 안정적 전력공급 작성일 2026/09/28 조회수 72")
        self.enqueue(candidate)
        legacy=hashlib.sha256(json.dumps({k:candidate.get(k) for k in ('url','title','summary','published_at')},sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        result={"action":"reviewed","reason":"Prior identical-content review proven"}
        with self.queue.connect() as con:
            con.execute('UPDATE jobs SET fingerprint=? WHERE url=?',(legacy,candidate['url']))
            con.execute('INSERT INTO completed_versions VALUES(?,?,?,?,?)',(candidate['url'],fingerprint(candidate),'reviewed','Proven completed alias',json.dumps(result)))
        self.assertEqual(self.enqueue(dict(candidate,title=candidate['title'].replace('72','73')),path='run-2/snapshot.json'),0)
        self.assertEqual(self.stored(candidate['url'])['status'],'reviewed')
        self.assertEqual(self.queue.take(1),[])
        changed=dict(candidate,title='[보도자료] 전력공급 차질',summary='New outage and restoration schedule')
        self.assertEqual(self.enqueue(changed,path='run-3/snapshot.json'),1)
        self.assertEqual(self.stored(candidate['url'])['status'],'queued')
        self.assertEqual(json.loads(self.queue.take(1)[0]['candidate']),changed)

    def test_kpx_normalization_does_not_turn_unreviewed_into_completed(self):
        candidate=self.candidate(url="https://new.kpx.or.kr/gallery.es?act=view&list_no=220",
                                 title="새글 [보도자료] 안정적 전력공급 작성일 2026/09/28 조회수 33")
        self.enqueue(candidate)
        self.assertEqual(self.enqueue(dict(candidate,title=candidate['title'].replace('33','65'))),0)
        self.assertEqual(self.stored(candidate['url'])['status'],'queued')
        self.assertEqual(len(self.queue.take(1)),1)

    def test_restart_preserves_jobs_and_state(self):
        candidate = self.candidate()
        self.assertEqual(self.enqueue(candidate), 1)
        self.queue.set("source_last_poll", {"ercot": 999})
        restarted = Queue(self.path)
        self.assertEqual(restarted.counts(), {"queued": 1})
        self.assertEqual(restarted.get("source_last_poll"), {"ercot": 999})
        self.assertEqual(restarted.get("latest_snapshot"), "run-1/snapshot.json")
        self.assertEqual(json.loads(restarted.take(1)[0]["candidate"]), candidate)

    def test_realtime_start_rejects_old_repoll_and_accepts_only_new_publication(self):
        self.queue.set("realtime_start_epoch", 900)
        self.queue.set("realtime_max_age_hours", 12)
        at = lambda epoch: dt.datetime.fromtimestamp(epoch, dt.timezone.utc).isoformat()
        old = self.candidate(1, published_at=at(899))
        fresh = self.candidate(2, published_at=at(950))
        undated_new = self.candidate(3, published_at=None, first_seen_at=at(970))
        self.assertEqual(self.enqueue(old, fresh, undated_new), 2)
        with self.queue.connect() as con:
            self.assertIsNone(con.execute("SELECT 1 FROM jobs WHERE url=?", (old["url"],)).fetchone())
        self.assertEqual(self.queue.counts(), {"queued": 2})
        self.assertEqual(self.enqueue(old, path="run-2/snapshot.json"), 0)
        self.assertEqual(self.queue.get("last_realtime_filter")["old_or_undated_skipped"], 1)

    def test_new_gmail_edition_can_surface_pre_reset_article_temporarily(self):
        self.queue.set('realtime_start_epoch',900)
        self.queue.set('realtime_max_age_hours',12)
        at=lambda epoch:dt.datetime.fromtimestamp(epoch,dt.timezone.utc).isoformat()
        new_mail=self.candidate(1,published_at=at(899),newsletter_received_at=at(980))
        old_mail=self.candidate(2,published_at=at(899),newsletter_received_at=at(899))
        self.assertEqual(fingerprint(new_mail),fingerprint(dict(new_mail,newsletter_received_at=None)))
        self.assertEqual(self.enqueue(new_mail,old_mail),1)
        self.assertEqual(self.queue.counts(),{'queued':1})
        self.time.return_value=980+12*3600+1
        self.assertEqual(self.queue.take(1),[])

    def test_scheduled_standard_brief_survives_until_next_slot(self):
        self.queue.set('realtime_start_epoch',900)
        self.queue.set('realtime_max_age_hours',12)
        self.queue.set('scheduled_brief_max_age_hours',18)
        published=dt.datetime.fromtimestamp(950,dt.timezone.utc).isoformat()
        candidate=self.candidate(1,published_at=published)
        self.assertEqual(self.enqueue(candidate),1)
        job=self.queue.take(1)[0]
        self.queue.finish(job,'ready_day','verified standard brief',{'action':'send','urgency':'standard'})
        self.time.return_value=950+13*3600
        self.assertTrue(self.queue.active_fresh(job))
        self.time.return_value=950+18*3600+1
        self.assertFalse(self.queue.active_fresh(job))

    def test_undated_tdworld_article_cannot_use_first_discovery_as_publication(self):
        self.queue.set("realtime_start_epoch",900)
        self.queue.set("realtime_max_age_hours",12)
        candidate=self.candidate(7,source="T&D World",published_at=None,
                                 first_seen_at=dt.datetime.fromtimestamp(970,dt.timezone.utc).isoformat())
        self.assertEqual(self.enqueue(candidate),0)
        self.assertEqual(self.queue.counts(),{})

    def test_realtime_expiry_removes_pending_but_preserves_delivered_history(self):
        self.queue.set("realtime_start_epoch", 900)
        self.queue.set("realtime_max_age_hours", 12)
        at = lambda epoch: dt.datetime.fromtimestamp(epoch, dt.timezone.utc).isoformat()
        fresh = self.candidate(1, published_at=at(950))
        completed = self.candidate(2, published_at=at(950))
        self.enqueue(fresh, completed)
        jobs = self.queue.take(2)
        delivered = next(job for job in jobs if job["url"] == completed["url"])
        self.queue.finish(delivered, "delivered", "Receipt-backed delivery")
        remaining = next(job for job in jobs if job["url"] == fresh["url"])
        self.queue.finish(remaining, "deferred", "Public original currently unavailable")
        self.time.return_value = 950 + 12 * 3600 + 1
        self.assertEqual(self.queue.take(2), [])
        self.assertEqual(self.queue.counts(), {"delivered": 1})


    def test_same_content_moves_to_new_snapshot_without_reopening_done(self):
        candidate = self.candidate()
        self.enqueue(candidate)
        job = self.queue.take(1)[0]
        self.queue.finish(job, "reviewed", "A concrete completed editorial decision", {"verified": True})
        before = self.stored(candidate["url"])
        self.time.return_value = 1200
        self.assertEqual(self.enqueue(self.candidate(2), candidate, path="run-2/snapshot.json"), 1)
        after = self.stored(candidate["url"])
        self.assertEqual(after["status"], "reviewed")
        self.assertEqual(after["snapshot"], "run-2/snapshot.json")
        self.assertEqual(after["candidate_index"], 1)
        self.assertEqual(after["result"], before["result"])
        self.assertEqual(after["attempts"], before["attempts"])
        self.assertEqual(after["queued"], before["queued"])

    def test_deferred_job_is_not_completed_and_retries_when_due(self):
        self.enqueue(self.candidate())
        job = self.queue.take(1)[0]
        self.queue.finish(job, "deferred", "Source 403; retry after backoff", delay=300)
        self.assertEqual(self.queue.counts(), {"deferred": 1})
        self.assertEqual(self.queue.take(1), [])
        self.time.return_value = 1299
        self.assertEqual(self.queue.take(1), [])
        self.time.return_value = 1300
        retried = self.queue.take(1)
        self.assertEqual(len(retried), 1)
        self.assertEqual(self.stored(job["url"])["attempts"], 2)

    def test_unchanged_repoll_does_not_bypass_retry_backoff(self):
        candidate = self.candidate()
        self.enqueue(candidate)
        job = self.queue.take(1)[0]
        self.queue.finish(job, "deferred", "Unverified original remains pending", delay=300)
        self.time.return_value = 1100
        self.enqueue(candidate, path="run-2/snapshot.json")
        stored = self.stored(candidate["url"])
        self.assertEqual(stored["status"], "deferred")
        self.assertEqual(stored["not_before"], 1300)
        self.assertEqual(self.queue.take(1), [])

    def test_changed_candidate_resets_attempts_backoff_and_old_result(self):
        candidate = self.candidate()
        self.enqueue(candidate)
        job = self.queue.take(1)[0]
        self.queue.finish(job, "deferred", "Original failed", {"old": True}, delay=300)
        revised = dict(candidate, summary="Verified 2GW connection approval")
        self.time.return_value = 1100
        self.assertEqual(self.enqueue(revised, path="run-2/snapshot.json"), 1)
        row = self.stored(candidate["url"])
        self.assertEqual((row["status"], row["not_before"], row["attempts"]), ("queued", 0, 0))
        self.assertIsNone(row["reason"])
        self.assertIsNone(row["result"])
        self.assertEqual(json.loads(row["candidate"]), revised)
        self.assertEqual(len(self.queue.take(1)), 1)

    def test_old_inflight_result_cannot_overwrite_changed_candidate(self):
        candidate = self.candidate()
        self.enqueue(candidate)
        stale = self.queue.take(1)[0]
        revised = dict(candidate, title="Final approval instead of proposal")
        self.enqueue(revised, path="run-2/snapshot.json")
        self.queue.finish(stale, "reviewed", "Old proposal was preliminary", {"stale": True})
        row = self.stored(candidate["url"])
        self.assertEqual(row["status"], "queued")
        self.assertEqual(row["fingerprint"], fingerprint(revised))
        self.assertIsNone(row["result"])
        self.assertEqual(json.loads(self.queue.take(1)[0]["candidate"]), revised)

    def test_candidate_absent_from_next_snapshot_remains_durable(self):
        candidates = [self.candidate(1), self.candidate(2)]
        self.enqueue(*candidates)
        self.enqueue(candidates[1], path="run-2/snapshot.json")
        self.assertEqual(self.queue.counts(), {"queued": 2})
        taken = self.queue.take(10)
        self.assertEqual({job["url"] for job in taken}, {item["url"] for item in candidates})

    def test_restart_requeues_only_inflight_not_done_or_ready_day(self):
        self.enqueue(self.candidate(1), self.candidate(2), self.candidate(3))
        jobs = self.queue.take(3)
        self.queue.finish(jobs[0], "reviewed", "Complete editorial exclusion")
        self.queue.finish(jobs[1], "ready_day", "Verified standard article awaiting daytime", {"urgency": "standard"})
        restarted = Queue(self.path)
        restarted.reset_inflight()
        self.assertEqual(restarted.counts(), {"queued": 1, "ready_day": 1, "reviewed": 1})
        self.assertEqual(len(restarted.ready()), 1)
        self.assertEqual(restarted.take(3)[0]["url"], jobs[2]["url"])

    def test_ready_day_draft_survives_restart_and_is_not_reclaimed_for_review(self):
        candidate = self.candidate()
        self.enqueue(candidate)
        job = self.queue.take(1)[0]
        result = {"action": "send", "urgency": "standard", "message_text": "Prepared verified article"}
        self.queue.finish(job, "ready_day", "Wait until 06:00 KST", result)
        restarted = Queue(self.path)
        self.assertEqual(restarted.take(1), [])
        self.assertEqual(json.loads(restarted.ready()[0]["result"]), result)

    def test_separate_queue_connections_do_not_take_same_inflight_jobs(self):
        self.enqueue(*(self.candidate(i) for i in range(8)))
        other = Queue(self.path)
        first = self.queue.take(4)
        second = other.take(4)
        self.assertEqual(len(first), 4)
        self.assertEqual(len(second), 4)
        self.assertFalse({item["url"] for item in first} & {item["url"] for item in second})
        self.assertEqual(self.queue.counts(), {"inflight": 8})

    def test_batch_retains_oldest_work_under_new_arrivals(self):
        self.enqueue(self.candidate(0))
        self.time.return_value = 1100
        self.enqueue(*(self.candidate(i) for i in range(1, 20)))
        rows = self.queue.take(4)
        self.assertEqual(len(rows), 4)
        self.assertIn(self.candidate(0)["url"], {row["url"] for row in rows})

    def test_important_news_outranks_newer_low_score_with_oldest_reservation(self):
        oldest = self.candidate(0, score=1, published_at="2026-09-20T06:00:00+09:00")
        self.enqueue(oldest)
        self.time.return_value = 1100
        important = self.candidate(1, score=50, published_at="2026-09-24T09:00:00+09:00")
        required = self.candidate(2, score=0, must_review=True, published_at="2026-09-24T08:00:00+09:00")
        self.enqueue(important, required)
        self.time.return_value = 1200
        newest_noise = self.candidate(3, score=49, published_at="2026-09-24T10:00:00+09:00")
        self.enqueue(newest_noise, *(self.candidate(i, score=0, published_at="2026-09-24T09:30:00+09:00") for i in range(4, 12)))
        jobs = self.queue.take(4)
        self.assertEqual([job["url"] for job in jobs], [important["url"], required["url"], oldest["url"], newest_noise["url"]])
        self.assertEqual(len({job["url"] for job in jobs}), 4)
        self.assertEqual(self.queue.counts(), {"inflight": 4, "queued": 8})

    def test_domestic_residual_slot_preserves_important_and_oldest(self):
        oldest=self.candidate(0,score=1)
        self.enqueue(oldest)
        self.time.return_value=1100
        important=self.candidate(1,score=80,published_at='2026-09-24T09:00:00+09:00')
        required=self.candidate(2,must_review=True,published_at='2026-09-24T08:00:00+09:00')
        domestic=self.candidate(3,score=5,source_group='korea_industry',published_at='2026-09-24T07:00:00+09:00')
        noise=self.candidate(4,score=1,published_at='2026-09-24T10:00:00+09:00')
        self.enqueue(important,required,domestic,noise)
        jobs=self.queue.take(4)
        self.assertEqual([j['url'] for j in jobs],[important['url'],required['url'],oldest['url'],domestic['url']])

    def test_important_publication_order_is_timezone_aware_not_raw_text(self):
        earlier = self.candidate(1, score=80, published_at="2026-09-24T08:00:00+09:00")
        later = self.candidate(2, score=50, published_at="2026-09-24T00:30:00Z")
        self.enqueue(earlier, later, self.candidate(3), self.candidate(4))
        jobs = self.queue.take(4)
        self.assertEqual([job["url"] for job in jobs[:2]], [later["url"], earlier["url"]])

    def test_important_and_oldest_overlap_never_repeats_or_underfills_jobs(self):
        self.enqueue(self.candidate(0, score=90))
        self.time.return_value = 1100
        self.enqueue(*(self.candidate(i, score=60) for i in range(1, 10)))
        jobs = self.queue.take(8)
        self.assertEqual(len(jobs), 8)
        self.assertEqual(len({job["url"] for job in jobs}), 8)
        self.assertEqual(len(self.queue.take(8)), 2)

    def test_single_job_batches_eventually_serve_old_low_score_amid_important_arrivals(self):
        oldest = self.candidate(0, score=0, published_at="2026-09-20T06:00:00+09:00")
        self.enqueue(oldest)
        served = []
        for cycle in range(4):
            self.time.return_value = 1100 + cycle
            self.enqueue(self.candidate(cycle + 1, score=80, published_at=f"2026-09-24T{8 + cycle:02d}:00:00+09:00"))
            # Reopening the connection/process does not reset fairness.
            queue = Queue(self.path)
            served.extend(job["url"] for job in queue.take(1))
        self.assertEqual(served[2], oldest["url"])
        self.assertEqual(len(set(served)), 4)


class RealtimeResetTests(unittest.TestCase):
    def test_reset_archives_pending_and_keeps_completed_rows(self):
        with tempfile.TemporaryDirectory(prefix="newsflow-v11-reset-test-") as temporary:
            root = Path(temporary)
            queue = Queue(root / "work/v11/queue.db")
            now = dt.datetime.now(dt.timezone.utc).isoformat()
            candidates = [{"url": f"https://example.com/{i}", "title": f"Item {i}",
                           "summary": "Industrial development", "published_at": now} for i in range(4)]
            queue.enqueue({"run_id": "test", "candidates": candidates}, root / "snapshot.json")
            taken = queue.take(4)
            queue.finish(taken[0], "delivered", "Receipt-backed delivery")
            queue.finish(taken[1], "reviewed", "Completed editorial decision")
            queue.finish(taken[2], "deferred", "Retry pending")
            result = reset(root, 12)
            self.assertEqual(result["removed"], 2)
            self.assertEqual(result["after"], {"delivered": 1, "reviewed": 1})
            archive = Path(result["archive"])
            self.assertTrue(archive.is_file())
            with closing(sqlite3.connect(archive)) as backup:
                self.assertEqual(backup.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 4)
            self.assertIsInstance(queue.get("realtime_start_epoch"), float)


if __name__ == "__main__":
    unittest.main()
