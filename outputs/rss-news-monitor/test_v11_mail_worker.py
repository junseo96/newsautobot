import json
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch

import gmail_scan
import v11_mail_worker as worker
import v11_runtime


def event(tool, arguments, payload, **changes):
    item = {"type": "mcp_tool_call", "server": "codex_apps", "tool": tool,
            "arguments": arguments, "result": {"content": [{"type": "text", "text": "Action completed."}],
                                                  "structured_content": payload},
            "error": None, "status": "completed"}
    item.update(changes)
    return {"type": "item.completed", "item": item}


def search(query, ids, token=None, next_token=None):
    return event('gmail.search_email_ids', {'query': query, 'max_results': 100, 'next_page_token': token},
                 {'message_ids': ids, 'next_page_token': next_token})


def message(mid, linked=True):
    return {'id': mid, 'internal_date': str(int(time.time() * 1000)), 'payload': {
        'mime_type': 'text/html', 'headers': [{'name': 'From', 'value': 'Energy News <news@example.com>'}],
        'parts': None, 'body': {'content': '<a href="https://example.com/news/1">New transmission project</a>'
                              if linked else '<p>Full body industrial news without a public link.</p>'}}}


class WorkerTests(unittest.TestCase):
    def setUp(self):
        # These cases exercise actual MCP evidence. Deployment defaults must
        # not switch their mocked connector calls to the independent REST path.
        transport = patch.dict('os.environ', {'NEWS_GMAIL_TRANSPORT': 'connected_plugin'})
        transport.start()
        self.addCleanup(transport.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / 'outputs/rss-news-monitor').mkdir(parents=True)
        (self.root / 'work').mkdir()
        v11_runtime.save_json(self.root / 'outputs/rss-news-monitor/runtime-v9.json',
                              {'version': 9, 'gmail_start_epoch': 100, 'retired_message_ids': []})
        with sqlite3.connect(self.root / 'work/rss-news-monitor.db') as con:
            con.execute('CREATE TABLE newsletter_messages(message_id TEXT PRIMARY KEY)')
            con.execute('INSERT INTO newsletter_messages VALUES(?)', ('old',))
        con.close()
        self.directory = self.root / 'work/poll'

    def tearDown(self):
        self.temp.cleanup()

    def transport(self, root, config, prompt, directory, **kwargs):
        request = json.loads(prompt.split('\n', 1)[1])
        events = [search(request['query'], ['old', 'new1']),
                  event('gmail.batch_read_email', {'message_ids': ['new1']}, {'emails': [message('new1')]})]
        Path(directory).mkdir(parents=True, exist_ok=True)
        (Path(directory) / 'events.jsonl').write_text('\n'.join(json.dumps(e) for e in events), encoding='utf-8')
        return {'claimed_complete': True}, events

    def test_actual_result_capture_and_finalize_only_after_collector(self):
        with patch.object(v11_runtime, 'codex', side_effect=self.transport):
            result = worker.run(self.root, {}, self.directory)
        self.assertEqual(result['status'], 'ready_for_collector')
        self.assertEqual(result['stats']['new_messages'], 1)
        self.assertFalse(result['stats']['ingestion_cursor_advanced'])
        newsletter = json.loads(Path(result['newsletter_file']).read_text())
        self.assertEqual([m['message_id'] for m in newsletter['messages']], ['new1'])
        self.assertIsNotNone(gmail_scan.cached_body_evidence(self.root, 'new1'))
        with sqlite3.connect(self.root / 'work/rss-news-monitor.db') as con:
            con.execute('INSERT INTO newsletter_messages VALUES(?)', ('new1',))
        con.close()
        self.assertTrue(worker.finalize(self.root, result['scan_file'])['advanced'])

    def test_model_claim_without_tool_evidence_never_advances(self):
        with patch.object(v11_runtime, 'codex', return_value=({'pagination_complete': True}, [])):
            result = worker.run(self.root, {'gmail_evidence_attempts': 1}, self.directory)
        self.assertEqual(result['status'], 'failed')
        self.assertFalse((self.root / 'work/gmail-scan-state.json').exists())
        self.assertFalse((self.root / 'work/gmail-staging-state.json').exists())

    def test_incomplete_luna_tool_evidence_retries_with_sol(self):
        models = []
        def transport(root, config, prompt, directory, **kwargs):
            models.append((config.get('gmail_model'), config.get('gmail_reasoning_effort')))
            if len(models) == 1:
                return None, []
            return self.transport(root, config, prompt, directory, **kwargs)
        config = {'model': 'gpt-6-sol', 'reasoning_effort': 'medium',
                  'gmail_model': 'gpt-6-luna', 'gmail_reasoning_effort': 'low'}
        with patch.object(v11_runtime, 'codex', side_effect=transport):
            result = worker.run(self.root, config, self.directory)
        self.assertEqual(models, [('gpt-6-luna', 'low'), ('gpt-6-sol', 'medium')])
        self.assertEqual(result['status'], 'ready_for_collector')

    def test_actual_batch_responses_wrapper_preserves_full_mime(self):
        def transport(root, config, prompt, directory, **kwargs):
            request = json.loads(prompt.split('\n', 1)[1])
            return None, [search(request['query'], ['new1']),
                          event('gmail.batch_read_email', {'message_ids': ['new1']},
                                {'responses': [message('new1')]})]
        with patch.object(v11_runtime, 'codex', side_effect=transport):
            result = worker.run(self.root, {'gmail_evidence_attempts': 1}, self.directory)
        self.assertEqual(result['stats']['full_body_reads'], 1)
        self.assertEqual(result['status'], 'ready_for_collector')

    def test_pagination_chain_and_query_must_match(self):
        events = [search('q', ['one'], next_token='p2'), search('wrong', ['bad'], token='p2')]
        self.assertFalse(worker.search_evidence(events, 'q')['pagination_complete'])
        events.append(search('q', ['two'], token='p2'))
        result = worker.search_evidence(events, 'q')
        self.assertTrue(result['pagination_complete'])
        self.assertEqual(result['message_ids'], ['one', 'two'])
        self.assertEqual(result['page_count'], 2)

    def test_successful_mime_survives_cli_final_failure(self):
        def broken(root, config, prompt, directory, **kwargs):
            self.transport(root, config, prompt, directory, **kwargs)
            raise RuntimeError('final turn failed')
        with patch.object(v11_runtime, 'codex', side_effect=broken):
            result = worker.run(self.root, {'gmail_evidence_attempts': 1}, self.directory)
        self.assertEqual(result['status'], 'ready_for_collector')
        self.assertEqual(result['stats']['full_body_reads'], 1)
        self.assertEqual(result['errors'][0]['stage'], 'transport')

    def test_only_queued_cache_selected_never_all_historical_cache(self):
        cache_dir = self.root / 'work/gmail-body-cache'
        cache_dir.mkdir()
        for mid in ['pending', 'historical']:
            v11_runtime.save_json(cache_dir / (mid + '.json'),
                                  {'message_id': mid, 'body_complete': True, 'message': message(mid)})
        scan = {'scan_started_epoch': int(time.time()), 'pagination_complete': True,
                'search_tool': 'gmail_search_email_ids', 'message_ids': ['pending']}
        gmail_scan.record_search(self.root, scan)
        gmail_scan.cache_body(self.root, 'pending', cache_dir / 'pending.json')
        def empty(root, config, prompt, directory, **kwargs):
            request = json.loads(prompt.split('\n', 1)[1])
            return None, [search(request['query'], [])]
        with patch.object(v11_runtime, 'codex', side_effect=empty):
            result = worker.run(self.root, {}, self.directory)
        self.assertEqual(result['ready_message_ids'], ['pending'])
        self.assertEqual(result['stats']['cached_body_reuse'], 1)

    def test_body_only_mail_stays_pending_for_explicit_classification(self):
        def body_only(root, config, prompt, directory, **kwargs):
            request = json.loads(prompt.split('\n', 1)[1])
            return None, [search(request['query'], ['new1']),
                event('gmail.read_email', {'message_id': 'new1', 'format': 'full'}, message('new1', linked=False))]
        with patch.object(v11_runtime, 'codex', side_effect=body_only):
            result = worker.run(self.root, {}, self.directory)
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['pending_message_ids'], ['new1'])
        self.assertEqual(result['stats']['manual_mail_classification_required'], 1)

    def test_error_and_unrelated_body_results_are_not_evidence(self):
        events = [event('gmail.read_email', {'message_id': 'new1'}, message('new1'), error='denied'),
                  event('gmail.read_email', {'message_id': 'unrelated'}, message('unrelated'))]
        self.assertEqual(worker.body_evidence(events, {'new1'}), {})

    def test_unsafe_message_id_rejected_before_filesystem_use(self):
        self.assertFalse(worker.search_evidence([search('q', ['../outside'])], 'q')['pagination_complete'])

    def test_partial_pagination_caches_successful_reads_for_next_poll(self):
        def partial(root, config, prompt, directory, **kwargs):
            request = json.loads(prompt.split('\n', 1)[1])
            return None, [search(request['query'], ['new1'], next_token='missing-page'),
                event('gmail.batch_read_email', {'message_ids': ['new1']}, {'emails': [message('new1')]})]
        with patch.object(v11_runtime, 'codex', side_effect=partial):
            result = worker.run(self.root, {'gmail_evidence_attempts': 1}, self.directory)
        self.assertEqual(result['status'], 'failed')
        self.assertFalse(result['stats']['search_cursor_advanced'])
        self.assertIsNotNone(gmail_scan.cached_body_evidence(self.root, 'new1'))
        self.assertEqual(gmail_scan._queue(self.root)['searched_through_epoch'], 0)
        def complete(root, config, prompt, directory, **kwargs):
            request = json.loads(prompt.split('\n', 1)[1])
            self.assertEqual(request['queued_body_read_ids'], [])
            self.assertIn('new1', request['already_cached_ids'])
            return None, [search(request['query'], ['new1'])]
        with patch.object(v11_runtime, 'codex', side_effect=complete):
            result = worker.run(self.root, {}, self.root/'work/next-poll')
        self.assertEqual(result['status'], 'ready_for_collector')
        self.assertEqual(result['stats']['cached_body_reuse'], 1)
        self.assertEqual(result['stats']['full_body_reads'], 0)

    def test_prompt_omits_old_ids_but_keeps_local_all_history_dedup(self):
        with sqlite3.connect(self.root/'work/rss-news-monitor.db') as con:
            con.execute('ALTER TABLE newsletter_messages ADD COLUMN received_at TEXT')
            con.execute("UPDATE newsletter_messages SET received_at='2000-01-01T00:00:00+00:00'")
        con.close()
        gmail_scan.finish(self.root, {'scan_started_epoch': int(time.time()),
                          'pagination_complete': True, 'message_ids': []})
        def transport(root, config, prompt, directory, **kwargs):
            request = json.loads(prompt.split('\n', 1)[1])
            self.assertEqual(request['already_ingested_ids'], [])
            # Even if the provider returns an out-of-window old ID, host-side
            # dedup must still prevent a second newsletter import.
            return None, [search(request['query'], ['old']),
                event('gmail.batch_read_email', {'message_ids': ['old']}, {'emails': [message('old')]})]
        with patch.object(v11_runtime, 'codex', side_effect=transport):
            result = worker.run(self.root, {}, self.directory)
        self.assertEqual(result['status'], 'complete_no_new_mail')
        self.assertEqual(result['stats']['full_body_reads'], 0)
        self.assertEqual(result['stats']['prompt_ingested_ids'], 0)
        self.assertEqual(result['stats']['total_ingested_ids'], 1)


if __name__ == '__main__':
    unittest.main()
