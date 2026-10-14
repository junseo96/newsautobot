"""Canary repair tests use temporary databases and stub all network calls."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import canary_repair_20260929 as repair
from v11_runtime import Queue, save_json


class CanaryRepairTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='newsflow-canary-repair-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.queue = Queue(self.root / 'work/v11/queue.db')
        self.now = 1800000000
        self.clock = patch.object(repair.time, 'time', return_value=self.now)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.network = patch.object(repair.source_cache, 'get')
        self.fetch = self.network.start()
        self.addCleanup(self.network.stop)
        self.fetch.side_effect = AssertionError('Network must be explicitly stubbed')
        self.evidence = patch.object(repair, 'candidate_link_evidence', return_value={'allowed': None})
        self.permission = self.evidence.start()
        self.addCleanup(self.evidence.stop)

    def add_job(self, number=1, status='deferred', **changes):
        candidate = {'url': f'https://hello.canarymedia.com/t/PRIVATE_TRACKING_FIXTURE_{number}',
                     'title': f'PRIVATE_TITLE_FIXTURE_{number}', 'summary': 'A new grid project',
                     'published_at': '2027-01-15T08:00:00+00:00',
                     'newsletter_message_id': f'mail-{number}', **changes}
        self.queue.enqueue({'candidates': [candidate]}, f'snapshot-{number}.json')
        with self.queue.connect() as con:
            con.execute('UPDATE jobs SET status=?,attempts=7,reason=?,result=?,not_before=? WHERE url=?',
                        (status, 'Private prior review reason', '{"action":"defer","private":"OLD_RESULT"}',
                         self.now + 600, candidate['url']))
        return candidate

    def state(self):
        with self.queue.connect() as con:
            return {table: [dict(row) for row in con.execute('SELECT * FROM ' + table)]
                    for table in ('jobs', 'events', 'completed_versions', 'state')}

    def job(self, candidate):
        with self.queue.connect() as con:
            return dict(con.execute('SELECT * FROM jobs WHERE url=?', (candidate['url'],)).fetchone())

    def result_audit(self):
        return json.loads(next((self.root / 'work/v12-fixes-20260929').glob('canary-*/result.json')).read_text(encoding='utf-8'))

    def cache(self, candidate, result):
        save_json(self.root / 'work/v11/source-cache' / (repair.digest(candidate['url']) + '.json'),
                  {'url': candidate['url'], 'result': result})

    def assert_payload_preserved(self, before, after):
        for field in ('url', 'fingerprint', 'candidate', 'snapshot', 'candidate_index', 'result',
                      'attempts', 'queued', 'updated'):
            self.assertEqual(after[field], before[field], field)

    def test_dry_run_never_resolves_or_changes_queue_and_redacts_audit(self):
        candidates = [self.add_job(i) for i in range(3)]
        self.permission.side_effect = lambda root, item: {'allowed': [True, False, None][int(item['url'][-1])]}
        before = self.state()
        report = repair.run(self.root)
        self.fetch.assert_not_called()
        self.assertEqual(before, self.state())
        self.assertEqual(report['selected_count'], 3)
        self.assertEqual(report['permission_true_count'], 1)
        self.assertEqual(report['permission_false_count'], 1)
        self.assertEqual(report['permission_unknown_count'], 1)
        self.assertEqual(report['dry_run_count'], 1)
        self.assertFalse((self.root / 'work/v11/supervisor.lock').exists())
        for path in (self.root / 'work/v12-fixes-20260929').rglob('*.json'):
            text = path.read_text(encoding='utf-8')
            for candidate in candidates:
                self.assertNotIn(candidate['url'], text)
                self.assertNotIn(candidate['title'], text)
            self.assertNotIn('Private prior review reason', text)
            self.assertNotIn('OLD_RESULT', text)
        audit = self.result_audit()['rows'][0]
        self.assertEqual(audit['attempts'], 7)
        self.assertEqual(audit['not_before'], self.now + 600)
        self.assertEqual(audit['reason_sha256'], repair.digest('Private prior review reason'))

    def test_new_final_destination_even_403_requeues_with_payload_preserved(self):
        candidate = self.add_job()
        before = self.job(candidate)
        self.permission.return_value = {'allowed': True}
        self.cache(candidate, {'final_url': candidate['url'], 'usable': False})

        def fetch(root, url):
            # Audit must precede the first permitted external request.
            self.assertTrue(list((root / 'work/v12-fixes-20260929').glob('canary-*/before.json')))
            self.assertEqual(url, candidate['url'])
            return {'final_url': 'https://www.canarymedia.com/articles/energy-storage/new-grid-project',
                    'usable': False, 'error': 'HTTP 403'}

        self.fetch.side_effect = fetch
        report = repair.run(self.root, apply=True)
        after = self.job(candidate)
        self.assertEqual(after['status'], 'queued')
        self.assertEqual(after['not_before'], 0)
        self.assert_payload_preserved(before, after)
        self.assertEqual(report['queued_new_source_clue_count'], 1)
        self.assertEqual(report['resolved_count'], 1)
        self.assertEqual(report['usable_count'], 0)
        self.assertEqual(report['distinct_resolved_url_hash_count'], 1)
        self.assertEqual(report['hosts'], ['www.canarymedia.com'])
        self.assertEqual(len(self.state()['completed_versions']), 0)
        self.assertEqual(len(self.state()['events']), 1)

    def test_confirmed_utility_link_queues_local_ack_without_network(self):
        candidate = self.add_job(status='inflight')
        before = self.job(candidate)
        self.permission.return_value = {'allowed': False}
        report = repair.run(self.root, apply=True)
        after = self.job(candidate)
        self.fetch.assert_not_called()
        self.assertEqual(after['status'], 'queued')
        self.assertEqual(report['queued_for_metadata_ack_count'], 1)
        self.assert_payload_preserved(before, after)

    def test_unknown_permission_defers_six_hours_and_repeat_does_not_extend(self):
        candidate = self.add_job(status='queued')
        before = self.job(candidate)
        report = repair.run(self.root, apply=True)
        after = self.job(candidate)
        self.assertEqual(after['status'], 'deferred')
        self.assertEqual(after['not_before'], self.now + 21600)
        self.assertEqual(report['deferred_unknown_permission_count'], 1)
        self.assert_payload_preserved(before, after)
        self.clock.return_value = self.now + 120
        report = repair.run(self.root, apply=True)
        self.assertEqual(self.job(candidate), after)
        self.assertEqual(report['already_repaired_count'], 1)
        self.fetch.assert_not_called()
        self.assertFalse(self.state()['completed_versions'])

    def test_completed_uncertain_retired_and_unrelated_jobs_are_excluded(self):
        for index, status in enumerate(('delivered', 'reviewed', 'delivery_uncertain', 'uncertain', 'retired')):
            self.add_job(index, status=status)
        self.add_job(99, url='https://example.com/article')
        self.permission.return_value = {'allowed': True}
        before = self.state()
        report = repair.run(self.root, apply=True)
        self.assertEqual(report['selected_count'], 0)
        self.assertEqual(before, self.state())
        self.fetch.assert_not_called()
        self.permission.assert_not_called()

    def test_stale_active_job_is_not_resolved_requeued_or_deleted(self):
        candidate = self.add_job(published_at='1970-01-01T00:00:00+00:00')
        self.queue.set('realtime_start_epoch', 1)
        self.permission.return_value = {'allowed': True}
        before = self.state()
        report = repair.run(self.root, apply=True)
        self.assertEqual(report['fresh_count'], 0)
        self.assertEqual(report['stale_or_changed_count'], 1)
        self.assertEqual(before, self.state())
        self.fetch.assert_not_called()
        self.assertEqual(self.job(candidate)['status'], 'deferred')

    def test_status_fingerprint_and_payload_changes_during_resolve_prevent_requeue(self):
        candidate = self.add_job()
        self.permission.return_value = {'allowed': True}
        for field, value in (('status', 'delivered'), ('fingerprint', 'new-version'),
                             ('candidate', json.dumps({**candidate, 'score': 99}))):
            with self.subTest(field=field):
                with self.queue.connect() as con:
                    con.execute('UPDATE jobs SET status=?,fingerprint=?,candidate=? WHERE url=?',
                                ('deferred', repair.fingerprint(candidate), json.dumps(candidate, ensure_ascii=False), candidate['url']))

                def changed(root, url):
                    with self.queue.connect() as con:
                        con.execute('UPDATE jobs SET ' + field + '=? WHERE url=?', (value, url))
                    return {'final_url': 'https://www.canarymedia.com/articles/new', 'usable': True}

                self.fetch.side_effect = changed
                report = repair.run(self.root, apply=True)
                self.assertEqual(report['stale_or_changed_count'], 1)
                self.assertEqual(self.job(candidate)[field], value)
                self.assertEqual(len(self.state()['events']), 0)

    def test_no_new_clue_or_resolver_exception_does_not_requeue(self):
        candidate = self.add_job()
        self.permission.return_value = {'allowed': True}
        cached = {'final_url': 'https://www.canarymedia.com/articles/same', 'usable': True,
                  'text': 'Same body', 'published_at': '2027-01-15'}
        self.cache(candidate, cached)
        before = self.state()
        self.fetch.side_effect = None
        self.fetch.return_value = {**cached, 'fetched_at': 'new', 'tracking_resolver_version': 999}
        self.assertEqual(repair.run(self.root, apply=True)['untouched_count'], 1)
        self.assertEqual(self.state(), before)
        self.fetch.side_effect = ValueError(candidate['url'])
        self.assertEqual(repair.run(self.root, apply=True)['untouched_count'], 1)
        self.assertEqual(self.state(), before)

    def test_usable_content_or_publication_change_is_a_new_clue(self):
        candidate = self.add_job()
        self.permission.return_value = {'allowed': True}
        cached = {'final_url': 'https://www.canarymedia.com/articles/same', 'usable': True,
                  'text': 'Same body', 'published_at': '2027-01-15'}
        self.cache(candidate, cached)
        self.fetch.side_effect = None
        self.fetch.return_value = {**cached, 'text': 'Now complete original article body'}
        self.assertEqual(repair.run(self.root, apply=True)['queued_new_source_clue_count'], 1)
        self.assertTrue(repair.has_new_clue(cached, {**cached, 'published_at': '2027-01-16'}, candidate['url']))

    def test_unknown_or_mismatched_candidate_cannot_gain_permission(self):
        candidate = self.add_job()
        with self.queue.connect() as con:
            con.execute('UPDATE jobs SET fingerprint=? WHERE url=?', ('mismatched', candidate['url']))
        before = self.state()
        self.permission.return_value = {'allowed': True}
        report = repair.run(self.root, apply=True)
        self.assertEqual(report['fresh_count'], 0)
        self.assertEqual(before, self.state())
        self.fetch.assert_not_called()
        self.permission.assert_not_called()

    def test_apply_lock_is_required_before_plan_or_network(self):
        self.add_job()
        with patch.object(repair, 'InstanceLock', side_effect=OSError('locked')):
            with self.assertRaises(OSError):
                repair.run(self.root, apply=True)
        self.fetch.assert_not_called()
        self.permission.assert_not_called()
        self.assertFalse((self.root / 'work/v12-fixes-20260929').exists())

    def test_resolution_pool_is_bounded_to_four(self):
        self.add_job()
        self.permission.return_value = {'allowed': True}
        self.fetch.side_effect = None
        self.fetch.return_value = {'usable': False}
        executor = repair.ThreadPoolExecutor
        with patch.object(repair, 'ThreadPoolExecutor', wraps=executor) as pool:
            repair.run(self.root, apply=True)
        pool.assert_called_once_with(max_workers=4)

    def test_main_failure_redacts_sensitive_exception(self):
        output = io.StringIO()
        with patch.object(repair, 'run', side_effect=ValueError('PRIVATE_TRACKING_FIXTURE')), \
                patch('sys.argv', ['repair']), redirect_stdout(output):
            self.assertEqual(repair.main(), 1)
        self.assertEqual(json.loads(output.getvalue()), {'repair_failed_count': 1})


if __name__ == '__main__':
    unittest.main()
