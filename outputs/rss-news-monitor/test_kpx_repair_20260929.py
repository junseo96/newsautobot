"""One-time repair regressions in temporary DBs only; no production mutation."""
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from kpx_repair_20260929 import build_plan, digest, raw_fingerprint, repair
from v11_runtime import InstanceLock, fingerprint


class KPXRepairTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='newsflow-kpx-repair-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'work/v11/reviews/proof').mkdir(parents=True)
        self.url = 'https://new.kpx.or.kr/gallery.es?act=view&list_no=220'
        self.url_sha = digest(self.url)
        self.old = {'url': self.url, 'title': '새글 [보도자료] 전력공급 점검 작성일 2026/09/28 조회수 33',
                    'summary': '수요 전망 45.3GW와 계통 점검 결과', 'published_at': '2026-09-28T00:00:00+00:00'}
        self.current = {**self.old, 'title': self.old['title'].replace('조회수 33', '조회수 72')}
        self.result = {'index': 0, 'action': 'reviewed', 'verified': True, 'review_basis': 'original',
                       'reason': 'Actual original review found no new industrial change',
                       'review_category': 'industrial_news', 'message_text': None}
        self.queue = self.root / 'work/v11/queue.db'
        con = sqlite3.connect(self.queue)
        con.executescript('''
            CREATE TABLE jobs(url TEXT PRIMARY KEY,fingerprint TEXT,candidate TEXT,snapshot TEXT,candidate_index INTEGER,
                status TEXT,queued REAL,updated REAL,not_before REAL,attempts INTEGER,reason TEXT,result TEXT);
            CREATE TABLE completed_versions(url TEXT,fingerprint TEXT,status TEXT,reason TEXT,result TEXT,PRIMARY KEY(url,fingerprint));
            CREATE TABLE events(id INTEGER PRIMARY KEY,at TEXT,url TEXT,action TEXT,detail TEXT);
        ''')
        con.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                    (self.url, raw_fingerprint(self.current), json.dumps(self.current), 'current-snapshot', 3,
                     'inflight', 1.0, 2.0, 0, 17, 'pending repeated count', None))
        con.execute('INSERT INTO completed_versions VALUES(?,?,?,?,?)',
                    (self.url, raw_fingerprint(self.old), 'reviewed', self.result['reason'], json.dumps(self.result)))
        con.commit();con.close()
        con = sqlite3.connect(self.root / 'work/rss-news-monitor.db')
        con.execute('CREATE TABLE decision_history(id INTEGER PRIMARY KEY,run_id TEXT,url TEXT,status TEXT,reason TEXT,decided_at TEXT)')
        con.execute('INSERT INTO decision_history VALUES(?,?,?,?,?,?)',
                    (1, 'actual-ack-run', self.url, 'reviewed', self.result['reason'], '2026-09-28T06:00:00Z'))
        con.commit();con.close()
        prompt = 'Read-only original review\nASSIGNMENT\n' + json.dumps({'run_id': 'worker-run', 'candidates': [dict(self.old, index=0)]}, ensure_ascii=False)
        (self.root / 'work/v11/reviews/proof/prompt.txt').write_bytes(prompt.replace('\n', '\r\n').encode('utf-8'))

    def state(self):
        con = sqlite3.connect(self.queue);con.row_factory = sqlite3.Row
        try:
            return {'job': dict(con.execute('SELECT * FROM jobs').fetchone()),
                    'versions': [dict(row) for row in con.execute('SELECT * FROM completed_versions ORDER BY fingerprint')],
                    'events': [dict(row) for row in con.execute('SELECT * FROM events')]}
        finally:con.close()

    def sql(self, statement, args=()):
        con = sqlite3.connect(self.queue)
        try:con.execute(statement, args);con.commit()
        finally:con.close()

    def test_dry_run_proves_exact_alias_without_mutation_or_raw_output(self):
        before = self.state()
        report = repair(self.root, target_url_sha256=self.url_sha)
        self.assertEqual(report['status'], 'ready')
        self.assertEqual(report['mode'], 'dry_run')
        self.assertEqual(report['proof_count'], 1)
        self.assertEqual(report['normalized_fingerprint'], fingerprint(self.current))
        self.assertNotIn(self.url, json.dumps(report))
        self.assertNotIn(self.result['reason'], json.dumps(report))
        self.assertEqual(self.state(), before)
        self.assertFalse((self.root / 'work/v12-fixes-20260929').exists())
        self.assertFalse((self.root / 'work/v11/supervisor.lock').exists())

    def test_apply_restores_only_proven_review_and_keeps_old_history(self):
        before = self.state()
        report = repair(self.root, apply=True, target_url_sha256=self.url_sha)
        after = self.state()
        self.assertEqual(report['status'], 'applied')
        self.assertEqual(after['job']['status'], 'reviewed')
        self.assertEqual(after['job']['result'], before['versions'][0]['result'])
        self.assertEqual(after['job']['candidate'], before['job']['candidate'])
        self.assertEqual(after['job']['attempts'], before['job']['attempts'])
        self.assertEqual(len(after['versions']), 2)
        self.assertIn(before['versions'][0], after['versions'])
        audit = json.loads(Path(report['audit_file']).read_text(encoding='utf-8'))
        self.assertEqual(audit['plan']['old_job'], before['job'])
        self.assertEqual(audit['plan']['proof']['reviewed_ack']['id'], 1)
        self.assertIs(audit['new_ack_created'], False)
        self.assertIs(audit['telegram_called'], False)
        con = sqlite3.connect(self.root / 'work/rss-news-monitor.db')
        self.assertEqual(con.execute('SELECT count(*) FROM decision_history').fetchone()[0], 1)
        con.close()
        again = repair(self.root, apply=True, target_url_sha256=self.url_sha)
        self.assertEqual(again['status'], 'protected_or_already_complete')
        self.assertEqual(self.state(), after)

    def test_real_headline_or_body_or_publication_change_cannot_reuse(self):
        for change in ({'title': self.current['title'].replace('전력공급 점검', '신규 용량시장 제도 승인')},
                       {'summary': 'New approved 2GW capacity allocation'},
                       {'published_at': '2026-09-29T00:00:00+00:00'}):
            with self.subTest(change=change):
                candidate = {**self.current, **change}
                self.sql('UPDATE jobs SET fingerprint=?,candidate=?', (raw_fingerprint(candidate), json.dumps(candidate)))
                before = self.state()
                self.assertEqual(repair(self.root, apply=True, target_url_sha256=self.url_sha)['status'], 'no_proven_alias')
                self.assertEqual(self.state(), before)

    def test_unverified_or_nonreviewed_completion_cannot_reuse(self):
        for result in ({**self.result, 'verified': False}, {**self.result, 'action': 'defer'},
                       {**self.result, 'reason': 'A different unproven statement'}):
            with self.subTest(result=result):
                self.sql('UPDATE completed_versions SET result=?', (json.dumps(result),))
                self.assertEqual(build_plan(self.root, self.url_sha)['status'], 'no_proven_alias')

    def test_no_actual_ack_record_prevents_alias(self):
        con = sqlite3.connect(self.root / 'work/rss-news-monitor.db')
        con.execute('DELETE FROM decision_history');con.commit();con.close()
        self.assertEqual(build_plan(self.root, self.url_sha)['status'], 'no_proven_alias')

    def test_no_saved_assignment_prevents_alias(self):
        (self.root / 'work/v11/reviews/proof/prompt.txt').unlink()
        self.assertEqual(build_plan(self.root, self.url_sha)['status'], 'no_proven_alias')

    def test_delivered_and_uncertainty_are_untouched(self):
        for status in ('delivered', 'delivery_uncertain'):
            with self.subTest(status=status):
                self.sql('UPDATE jobs SET status=?', (status,))
                before = self.state()
                report = repair(self.root, apply=True, target_url_sha256=self.url_sha)
                self.assertEqual(report['status'], 'protected_or_already_complete')
                self.assertEqual(self.state(), before)

    def test_running_supervisor_blocks_apply(self):
        before = self.state()
        with InstanceLock(self.root / 'work/v11/supervisor.lock'):
            with self.assertRaises(OSError):
                repair(self.root, apply=True, target_url_sha256=self.url_sha)
        self.assertEqual(self.state(), before)

    def test_conflicting_alias_is_not_overwritten(self):
        result = {**self.result, 'reason': 'A different existing completion'}
        self.sql('INSERT INTO completed_versions VALUES(?,?,?,?,?)',
                 (self.url, fingerprint(self.current), 'reviewed', result['reason'], json.dumps(result)))
        before = self.state()
        self.assertEqual(repair(self.root, apply=True, target_url_sha256=self.url_sha)['status'], 'existing_alias_conflict')
        self.assertEqual(self.state(), before)

    def test_wrong_target_hash_does_not_select_other_notice(self):
        before = self.state()
        self.assertEqual(repair(self.root, apply=True, target_url_sha256='0' * 64)['status'], 'no_target')
        self.assertEqual(self.state(), before)

    def test_apply_does_not_change_another_job(self):
        other = 'https://new.kpx.or.kr/gallery.es?act=view&list_no=221'
        self.sql('INSERT INTO jobs SELECT ?,fingerprint,candidate,snapshot,candidate_index,status,queued,updated,not_before,attempts,reason,result FROM jobs WHERE url=?',
                 (other, self.url))
        con = sqlite3.connect(self.queue)
        before = con.execute('SELECT * FROM jobs WHERE url=?', (other,)).fetchone()
        con.close()
        self.assertEqual(repair(self.root, apply=True, target_url_sha256=self.url_sha)['status'], 'applied')
        con = sqlite3.connect(self.queue)
        self.assertEqual(con.execute('SELECT * FROM jobs WHERE url=?', (other,)).fetchone(), before)
        self.assertEqual(con.execute('SELECT count(*) FROM completed_versions WHERE url=?', (other,)).fetchone()[0], 0)
        con.close()


if __name__ == '__main__':
    unittest.main()
