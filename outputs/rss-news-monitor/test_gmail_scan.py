import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
import gmail_scan


class GmailScan(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root/'work').mkdir()
        con = sqlite3.connect(self.root/'work/rss-news-monitor.db')
        con.execute('CREATE TABLE newsletter_messages(message_id TEXT PRIMARY KEY)')
        con.execute("INSERT INTO newsletter_messages VALUES('known')")
        con.commit(); con.close()

    def test_no_label_sender_read_or_category_restrictions(self):
        result = gmail_scan.begin(self.root, now=1000000)
        for forbidden in ('label:', 'from:', 'is:unread', 'category:','in:inbox'):
            self.assertNotIn(forbidden,result['query'])
        self.assertEqual(result['processed_message_ids'],['known'])

    def test_unresolved_message_keeps_cursor(self):
        result = gmail_scan.finish(self.root, {'scan_started_epoch':100, 'pagination_complete':True, 'message_ids':['known','missing']}, now=200)
        self.assertFalse(result['advanced'])
        self.assertFalse((self.root/'work/gmail-scan-state.json').exists())

    def test_incomplete_pagination_rejected(self):
        with self.assertRaises(ValueError):
            gmail_scan.finish(self.root, {'scan_started_epoch':100, 'pagination_complete':False, 'message_ids':['known']}, now=200)

    def test_completed_scan_and_long_downtime(self):
        gmail_scan.finish(self.root, {'scan_started_epoch':100000, 'pagination_complete':True, 'message_ids':['known']}, now=200000)
        result = gmail_scan.begin(self.root, now=1000000)
        self.assertIn('after:78400 ',result['query'])
        gmail_scan.finish(self.root, {'scan_started_epoch':90000, 'pagination_complete':True, 'message_ids':[]}, now=200000)
        saved = json.loads((self.root/'work/gmail-scan-state.json').read_text())
        self.assertEqual(saved['completed_through_epoch'],100000)

    def scan(self, started=900000, ids=None):
        return {'scan_started_epoch': started, 'pagination_complete': True,
                'search_tool': 'gmail_search_email_ids', 'message_ids': ids or ['unknown']}

    def test_regular_scan_uses_six_hour_overlap_not_three_days(self):
        gmail_scan.finish(self.root, self.scan(ids=['known']), now=1000000)
        result = gmail_scan.begin(self.root, now=910800, compact=True)
        self.assertIn('after:878400 ', result['query'])
        self.assertNotIn('processed_message_ids', result)
        self.assertEqual(result['processed_message_count'], 1)

    def test_initial_scan_starts_at_configured_floor_even_after_downtime(self):
        cfg = self.root/'outputs/rss-news-monitor'
        cfg.mkdir(parents=True)
        (cfg/'runtime-v9.json').write_text(json.dumps({'gmail_start_epoch': 100000}))
        self.assertIn('after:100000 ', gmail_scan.begin(self.root, now=1000000)['query'])

    def test_queue_advances_search_without_marking_ingested(self):
        result = gmail_scan.record_search(self.root, self.scan(), now=1000000)
        self.assertEqual(result['body_read_needed_ids'], ['unknown'])
        self.assertFalse(result['ingestion_complete'])
        self.assertFalse(result['editorial_completion_claimed'])
        self.assertFalse((self.root/'work/gmail-scan-state.json').exists())
        self.assertIn('after:878400 ', gmail_scan.begin(self.root, now=910800)['query'])
        later = gmail_scan.record_search(self.root, self.scan(950000, ['known']), now=1000000)
        self.assertEqual(later['queued_message_ids'], ['unknown'])
        self.assertFalse(gmail_scan.finish(self.root, self.scan(950000, ['known']), now=1000000)['advanced'])

    def test_queue_requires_actual_complete_search(self):
        scan = self.scan()
        scan['pagination_complete'] = False
        with self.assertRaises(ValueError):
            gmail_scan.record_search(self.root, scan, now=1000000)
        self.assertFalse((self.root/'work/gmail-staging-state.json').exists())
        scan['pagination_complete'] = True
        scan['search_tool'] = 'not_the_connector'
        with self.assertRaises(ValueError):
            gmail_scan.record_search(self.root, scan, now=1000000)

    def test_cached_full_body_reused_but_never_ingestion_complete(self):
        gmail_scan.record_search(self.root, self.scan(), now=1000000)
        path = self.root/'work/body.json'
        body = {'message_id': 'unknown', 'body_complete': True,
                'message': {'id': 'unknown', 'payload': {'headers': [], 'mimeType': 'text/html',
                            'body': {'data': 'ZnVsbCBhcnRpY2xl', 'size': 12}}}}
        path.write_text(json.dumps(body), encoding='utf-8')
        gmail_scan.cache_body(self.root, 'unknown', path)
        result = gmail_scan.record_search(self.root, self.scan(950000), now=1000000)
        self.assertEqual(result['body_read_needed_ids'], [])
        self.assertEqual(result['cached_bodies'][0]['message_id'], 'unknown')
        self.assertEqual(gmail_scan.read_cache(self.root, 'unknown'), body)
        self.assertFalse(gmail_scan.finish(self.root, self.scan(950000), now=1000000)['advanced'])

    def test_tampered_or_missing_cache_requires_plugin_read_again(self):
        gmail_scan.record_search(self.root, self.scan(), now=1000000)
        path = self.root/'work/body.json'
        path.write_text(json.dumps({'message_id': 'unknown', 'body_complete': True,
                                   'message': {'id': 'unknown', 'payload': {'headers': [],
                                               'body': {'data': 'ZnVsbCBhcnRpY2xl', 'size': 12}}}}))
        gmail_scan.cache_body(self.root, 'unknown', path)
        path.write_text('{}')
        result = gmail_scan.record_search(self.root, self.scan(950000), now=1000000)
        self.assertEqual(result['body_read_needed_ids'], ['unknown'])
        with self.assertRaises(ValueError):
            gmail_scan.read_cache(self.root, 'unknown')
        path.unlink()
        self.assertIsNone(gmail_scan.cached_body_evidence(self.root, 'unknown'))

    def test_summary_cannot_be_declared_full_body(self):
        gmail_scan.record_search(self.root, self.scan(), now=1000000)
        path = self.root/'work/body.json'
        path.write_text(json.dumps({'message_id': 'unknown', 'summary': 'title only'}))
        with self.assertRaises(ValueError):
            gmail_scan.cache_body(self.root, 'unknown', path)

    def test_full_body_flag_does_not_allow_summary_or_mismatched_message(self):
        gmail_scan.record_search(self.root, self.scan(), now=1000000)
        path = self.root/'work/body.json'
        for message in ({'id': 'unknown', 'summary': 'only a summary'},
                        {'id': 'different', 'payload': {'headers': [], 'body': {'size': 0}}},
                        {'id': 'unknown', 'payload': {'headers': [], 'body': {}}},
                        {'id': 'unknown', 'payload': {'headers': [], 'body': {'size': 100}}},
                        {'id': 'unknown', 'payload': {'headers': [], 'parts': [{'snippet': 'only a summary'}]}}):
            path.write_text(json.dumps({'message_id': 'unknown', 'body_complete': True, 'message': message}))
            with self.assertRaises(ValueError):
                gmail_scan.cache_body(self.root, 'unknown', path)

    def test_empty_and_multipart_mime_payloads_remain_valid(self):
        gmail_scan.record_search(self.root, self.scan(), now=1000000)
        path = self.root/'work/body.json'
        for payload in ({'headers': [], 'body': {'size': 0}},
                        {'headers': [], 'mime_type': 'multipart/alternative', 'parts': [
                            {'headers': [], 'mime_type': 'text/plain', 'body': {'data': 'Zm9v', 'size': 3}}]}):
            path.write_text(json.dumps({'message_id': 'unknown', 'body_complete': True,
                                       'message': {'id': 'unknown', 'payload': payload}}))
            self.assertTrue(gmail_scan.cache_body(self.root, 'unknown', path)['cached'])

    def test_connected_plugin_encoded_and_decoded_body_shapes(self):
        gmail_scan.record_search(self.root, self.scan(), now=1000000)
        path = self.root/'work/body.json'
        for content in ({'base64_url_content': 'PGI+bmV3czwvYj4='},
                        {'content': '<b>news</b>'}):
            payload = {'part_id': '', 'mime_type': 'multipart/alternative',
                       'filename': '', 'headers': [], 'body': {'size': 0},
                       'read_attachment_supported': False, 'parts': [
                           {'part_id': '0', 'mime_type': 'text/html', 'filename': '',
                            'headers': [], 'body': {'size': 11, **content},
                            'read_attachment_supported': False, 'parts': []}]}
            path.write_text(json.dumps({'message_id': 'unknown', 'body_complete': True,
                                       'message': {'id': 'unknown', 'payload': payload}}))
            self.assertTrue(gmail_scan.cache_body(self.root, 'unknown', path)['cached'])

    def test_connected_plugin_missing_body_content_still_rejected(self):
        gmail_scan.record_search(self.root, self.scan(), now=1000000)
        path = self.root/'work/body.json'
        payload = {'part_id': '', 'mime_type': 'text/html', 'headers': [], 'parts': [],
                   'body': {'size': 100, 'content': '', 'base64_url_content': '', 'attachment_id': None}}
        path.write_text(json.dumps({'message_id': 'unknown', 'body_complete': True,
                                   'message': {'id': 'unknown', 'payload': payload}}))
        with self.assertRaises(ValueError):
            gmail_scan.cache_body(self.root, 'unknown', path)

    def test_imported_queue_entry_is_pruned_without_deleting_evidence(self):
        gmail_scan.record_search(self.root, self.scan(), now=1000000)
        with sqlite3.connect(self.root/'work/rss-news-monitor.db') as con:
            con.execute("INSERT INTO newsletter_messages VALUES('unknown')")
        con.close()
        self.assertTrue(gmail_scan.finish(self.root, self.scan(), now=1000000)['advanced'])
        result = gmail_scan.record_search(self.root, self.scan(950000), now=1000000)
        self.assertTrue(result['ingestion_complete'])
        self.assertEqual(result['queued_message_ids'], [])

    def test_partial_actual_page_is_durable_without_cursor_advance(self):
        scan = self.scan()
        scan['pagination_complete'] = False
        result = gmail_scan.record_search(self.root, scan, now=1000000, partial=True)
        self.assertEqual(result['queued_message_ids'], ['unknown'])
        self.assertFalse(result['search_cursor_advanced'])
        self.assertFalse(result['ingestion_complete'])
        self.assertEqual(gmail_scan._queue(self.root)['searched_through_epoch'], 0)
        self.assertFalse((self.root/'work/gmail-scan-state.json').exists())

    def test_prompt_ids_respect_actual_receive_window_and_preserve_unknowns(self):
        with sqlite3.connect(self.root/'work/rss-news-monitor.db') as con:
            con.execute('ALTER TABLE newsletter_messages ADD COLUMN received_at TEXT')
            con.executemany('INSERT INTO newsletter_messages VALUES(?,?)', [
                ('recent', '2026-09-28T01:00:00+00:00'),
                ('old', '2026-09-27T01:00:00+00:00'), ('bad_date', 'unknown')])
        con.close()
        self.assertEqual(gmail_scan.prompt_processed_ids(self.root, 1790550000),
                         {'known', 'recent', 'bad_date'})
        self.assertIn('old', gmail_scan.processed_ids(self.root))

    def test_legacy_import_time_only_excludes_provably_older_mail(self):
        with sqlite3.connect(self.root/'work/rss-news-monitor.db') as con:
            con.execute('ALTER TABLE newsletter_messages ADD COLUMN received_at TEXT')
            con.execute('ALTER TABLE newsletter_messages ADD COLUMN imported_at TEXT')
            con.executemany('INSERT INTO newsletter_messages VALUES(?,?,?)', [
                ('old_import', None, '2026-09-20T01:00:00+00:00'),
                ('recent_import', None, '2026-09-28T01:00:00+00:00')])
        con.close()
        self.assertEqual(gmail_scan.prompt_processed_ids(self.root, 1790550000),
                         {'known', 'recent_import'})

if __name__ == '__main__':
    unittest.main()
