import datetime as dt
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
import gmail_scan
import runtime_scope
import newsletter_completion
import newsletter_queue
from test_newsletter_queue import make_item, parse_date

FLOOR = 1789624800
SCOPE = {'version':9, 'gmail_start_epoch':FLOOR, 'freshness_hours':72,
         'retired_message_ids':['old'], 'retired_unresolved_urls':['old-url']}

class V9Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root/'outputs/rss-news-monitor').mkdir(parents=True)
        (self.root/'work').mkdir()
        (self.root/'outputs/rss-news-monitor/runtime-v9.json').write_text(json.dumps(SCOPE))
        self.con = sqlite3.connect(self.root/'work/rss-news-monitor.db')
        self.addCleanup(self.con.close)
        self.con.executescript("""
        CREATE TABLE newsletter_messages(message_id,source,imported_at,article_count,classification_reason);
        CREATE TABLE newsletter_message_articles(message_id,article_url);
        CREATE TABLE articles(url,title,status,delivered_at,decision_policy_version,decision_reason);
        CREATE TABLE delivery_history(url,sent_at);
        CREATE TABLE decision_history(url,status,policy_version,reason);
        INSERT INTO newsletter_messages VALUES('old','source','before',1,NULL);
        INSERT INTO newsletter_message_articles VALUES('old','old-url');
        INSERT INTO articles VALUES('old-url','title','pending',NULL,NULL,NULL);
        """)
        self.con.commit()

    def test_scan_never_crosses_v9_boundary(self):
        result = gmail_scan.begin(self.root, now=FLOOR+3600)
        self.assertIn(f'after:{FLOOR} ',result['query'])
        self.assertFalse(result['scan_deferred_until_start'])

    def test_v10_overrides_schedule_without_resetting_gmail_history(self):
        settings={'version':10,'scheduled_hours_kst':[6,9,12,15,18,21],
                  'active_window_kst':{'start':'06:00','end':'21:00'}}
        (self.root/'outputs/rss-news-monitor/runtime-v10.json').write_text(json.dumps(settings))
        scope=runtime_scope.load(self.root)
        self.assertEqual(scope['version'],10)
        self.assertEqual(scope['scheduled_hours_kst'],[6,9,12,15,18,21])
        self.assertEqual(scope['gmail_start_epoch'],FLOOR)
        self.assertEqual(scope['retired_message_ids'],['old'])
        self.assertEqual(scope['retired_unresolved_urls'],['old-url'])

    def test_v10_cannot_override_retirement_baseline(self):
        (self.root/'outputs/rss-news-monitor/runtime-v10.json').write_text(
            json.dumps({'version':10,'retired_message_ids':[]}))
        with self.assertRaises(ValueError):
            runtime_scope.load(self.root)

    def test_v11_continuous_override_preserves_v9_gmail_and_retirement_baseline(self):
        directory = self.root / 'outputs/rss-news-monitor'
        baseline = dict(SCOPE, gmail_start_kst='2026-09-17T15:00:00+09:00',
                        baseline_counts={'retired_messages': 1}, retirement_reason='User-retired historical backlog')
        (directory / 'runtime-v9.json').write_text(json.dumps(baseline))
        (directory / 'runtime-v10.json').write_text(json.dumps(
            {'version': 10, 'scheduled_hours_kst': [6, 9, 12, 15, 18, 21]}))
        (directory / 'runtime-v11.json').write_text(json.dumps(
            {'version': 11, 'operation': 'continuous_incremental', 'collection_interval_seconds': 300,
             'normal_delivery_window_kst': {'start': '06:00', 'end': '21:00'}, 'urgent_delivery_24h': True}))
        original = (directory / 'runtime-v9.json').read_bytes()
        scope = runtime_scope.load(self.root)
        self.assertEqual(scope['version'], 11)
        self.assertEqual(scope['operation'], 'continuous_incremental')
        self.assertEqual(scope['collection_interval_seconds'], 300)
        for key in ('gmail_start_epoch', 'gmail_start_kst', 'retired_message_ids',
                    'retired_unresolved_urls', 'baseline_counts', 'retirement_reason'):
            self.assertEqual(scope[key], baseline[key])
        self.assertEqual((directory / 'runtime-v9.json').read_bytes(), original)
        self.assertIn(f'after:{FLOOR} ', gmail_scan.begin(self.root, now=FLOOR+3600)['query'])
        self.assertEqual(self.con.execute('SELECT status FROM articles').fetchone()[0], 'pending')

    def test_v11_cannot_override_any_historical_gmail_baseline_field(self):
        target = self.root / 'outputs/rss-news-monitor/runtime-v11.json'
        for field in ('gmail_start_epoch', 'gmail_start_kst', 'retired_message_ids',
                      'retired_unresolved_urls', 'baseline_counts', 'retirement_reason'):
            with self.subTest(field=field):
                target.write_text(json.dumps({'version': 11, field: None}))
                with self.assertRaisesRegex(ValueError, 'historical Gmail baseline'):
                    runtime_scope.load(self.root)

    def test_v11_requires_preserved_historical_baseline(self):
        with tempfile.TemporaryDirectory() as empty:
            directory = Path(empty) / 'outputs/rss-news-monitor'
            directory.mkdir(parents=True)
            (directory / 'runtime-v11.json').write_text(json.dumps({'version': 11}))
            with self.assertRaisesRegex(ValueError, 'preserved historical baseline'):
                runtime_scope.load(empty)

    def test_future_boundary_is_not_a_fake_zero_mail_search(self):
        self.assertTrue(gmail_scan.begin(self.root, now=FLOOR-100)['scan_deferred_until_start'])

    def test_retirement_is_not_false_review_or_database_deletion(self):
        result = newsletter_completion.audit(self.con, 8)
        self.assertEqual(result['retired_historical_messages'],1)
        self.assertEqual(result['unresolved_article_count'],0)
        self.assertEqual(self.con.execute('SELECT status FROM articles').fetchone()[0],'pending')
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM newsletter_messages').fetchone()[0],1)

    def test_new_mail_can_reference_previously_retired_article(self):
        self.con.execute("INSERT INTO newsletter_messages VALUES('new','source','after',1,NULL)")
        self.con.execute("INSERT INTO newsletter_message_articles VALUES('new','old-url')")
        result = newsletter_completion.audit(self.con, 8)
        self.assertEqual(result['unresolved_article_count'],1)
        self.assertEqual(result['workflow_incomplete_messages'],1)

    def row(self, **overrides):
        row = dict(url='fresh-url',published_at='2026-09-17T06:00:00+00:00',
                   first_seen_at='2026-09-17T06:00:00+00:00', content_updated_at=None)
        row.update(overrides)
        return row

    def test_old_rss_history_is_reference_only_not_a_new_brief(self):
        row=self.row(published_at='2026-07-01T00:00:00+00:00')
        self.assertEqual(runtime_scope.exclusion(row,SCOPE,FLOOR),'historical_reference_only')

    def test_new_announcement_about_old_project_remains_eligible(self):
        self.assertIsNone(runtime_scope.exclusion(self.row(),SCOPE,FLOOR+3600))

    def test_new_newsletter_old_links_still_receive_explicit_editorial_judgment(self):
        row=self.row(published_at='2026-07-01T00:00:00+00:00')
        self.assertIsNone(runtime_scope.exclusion(row,SCOPE,FLOOR,{'fresh-url'}))

    def test_retired_url_is_not_reinjected_by_rss(self):
        self.assertEqual(runtime_scope.exclusion(self.row(url='old-url'),SCOPE,FLOOR),
                         'user_retired_gmail_backlog')

    def test_import_requires_real_in_scope_received_timestamp(self):
        path=self.root/'mail.json'
        base={'message_id':'new','source':'EIA','source_url':'https://www.eia.gov/',
              'articles':[], 'non_article_reason':'Subscription confirmation'}
        for received in (None,'2026-09-17T14:59:59+09:00','2026-09-17T15:00:00'):
            path.write_text(json.dumps({'schema_version':1,'messages':[dict(base,received_at=received)]}))
            with self.assertRaises(ValueError):
                newsletter_queue.load_newsletter_results(path,make_item,parse_date,received_after_epoch=FLOOR)
        path.write_text(json.dumps({'schema_version':1,'messages':[dict(base,received_at='2026-09-17T15:00:01+09:00')]}))
        self.assertEqual(len(newsletter_queue.load_newsletter_results(path,make_item,parse_date,received_after_epoch=FLOOR)),1)
