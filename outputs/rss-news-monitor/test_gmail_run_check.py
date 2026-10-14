import json
import tempfile
import unittest
from pathlib import Path
import gmail_run_check
import gmail_scan


class GmailRunCheck(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root/'work').mkdir()
        self.scan = {'scan_started_epoch': 900000, 'pagination_complete': True,
                     'search_tool': 'gmail_search_email_ids', 'message_ids': ['new'],
                     'new_message_ids': ['new'], 'read_message_ids': ['new']}

    def check(self, known=('new',)):
        return gmail_run_check.check(self.scan, 900000, known, 901000, self.root)

    def test_legacy_fresh_search_and_read_evidence_still_pass(self):
        self.assertTrue(self.check()['gmail_ingestion_evidence_complete'])

    def test_malformed_ids_return_error_not_exception(self):
        self.scan['read_message_ids'] = [None, {}]
        self.assertFalse(self.check()['gmail_ingestion_evidence_complete'])

    def test_cache_claim_without_valid_artifact_cannot_replace_read(self):
        self.scan['read_message_ids'] = []
        self.scan['cached_message_ids'] = ['new']
        result = self.check()
        self.assertIn('new_message_body_unread', result['errors'])
        self.assertIn('cached_body_missing_or_changed:new', result['errors'])

    def test_old_unimported_queue_cannot_be_omitted_from_current_scan(self):
        (self.root/'work/gmail-staging-state.json').write_text(json.dumps({
            'schema_version': 1, 'searched_through_epoch': 899000,
            'pending_messages': {'earlier': {'first_queued_epoch': 899000}}}))
        result = self.check()
        self.assertEqual(result['unimported_message_ids'], ['earlier'])
        self.assertFalse(result['gmail_ingestion_evidence_complete'])

    def test_unchanged_cache_can_replace_repeated_plugin_body_read(self):
        path = self.root/'work/body.json'
        path.write_text(json.dumps({'message_id': 'new', 'body_complete': True,
                                    'message': {'id': 'new', 'payload': {'headers': [],
                                                'body': {'data': 'RnVsbCBtZXNzYWdl', 'size': 12}}}}))
        (self.root/'work/gmail-staging-state.json').write_text(json.dumps({
            'schema_version': 1, 'searched_through_epoch': 899000,
            'pending_messages': {'new': {'first_queued_epoch': 899000}}}))
        gmail_scan.cache_body(self.root, 'new', path)
        self.scan['read_message_ids'] = []
        self.scan['cached_message_ids'] = ['new']
        self.assertTrue(self.check()['gmail_ingestion_evidence_complete'])
        path.write_text('{}')
        self.assertFalse(self.check()['gmail_ingestion_evidence_complete'])


if __name__ == '__main__':
    unittest.main()
