"""Supervisor shutdown and migrated-state tests; all external work is mocked."""
import json
import os
from pathlib import Path, PureWindowsPath
import threading
import unittest
from unittest.mock import Mock, patch

import test_v11_service as fixtures
from v11_runtime import read_json, save_json


class ServiceShutdownTests(unittest.TestCase):
    snapshot = fixtures.SupervisorSafetyTests.snapshot
    stored = fixtures.SupervisorSafetyTests.stored
    manifest = fixtures.SupervisorSafetyTests.manifest
    fake_publish = fixtures.SupervisorSafetyTests.fake_publish

    def setUp(self):
        fixtures.SupervisorSafetyTests.setUp(self)
        self.service.config.update(fast_poll_interval_seconds=60, collection_interval_seconds=60,
                                   gmail_interval_seconds=60)

    def test_preexisting_stop_starts_no_threads_or_queue_reset(self):
        self.service.stop.set()
        with patch.object(self.service.queue, 'reset_inflight') as reset, \
             patch.object(self.service, 'recover') as recover, \
             patch('v11_service.threading.Thread') as thread:
            self.service.run()
        reset.assert_not_called(); recover.assert_not_called(); thread.assert_not_called()

    def test_stop_during_startup_joins_started_thread_under_supervisor_lock(self):
        state = {'locked': False}
        class Lock:
            def __init__(self, path): pass
            def __enter__(self): state['locked'] = True
            def __exit__(self, *args): state['locked'] = False
        thread = Mock(ident=1)
        thread.start.side_effect = self.service.stop.set
        def joined():
            self.assertTrue(state['locked'])
            self.assertTrue(self.service.stop.is_set())
        thread.join.side_effect = joined
        with patch('v11_service.InstanceLock', Lock), \
             patch('v11_service.threading.Thread', return_value=thread) as create, \
             patch.object(self.service, 'recover'), patch.object(self.service, 'update'):
            self.service.run()
        self.assertEqual(create.call_count, 1)
        thread.join.assert_called_once_with()
        self.assertFalse(state['locked'])

    def test_partial_start_failure_still_stops_and_joins_existing_threads(self):
        state = {'locked': False}
        class Lock:
            def __init__(self, path): pass
            def __enter__(self): state['locked'] = True
            def __exit__(self, *args): state['locked'] = False
        first = Mock(ident=1)
        second = Mock(ident=None)
        second.start.side_effect = RuntimeError('synthetic thread start failure')
        def joined():
            self.assertTrue(state['locked'])
            self.assertTrue(self.service.stop.is_set())
        first.join.side_effect = joined
        with patch('v11_service.InstanceLock', Lock), \
             patch('v11_service.threading.Thread', side_effect=[first, second]), \
             patch.object(self.service, 'recover'), patch.object(self.service, 'update'):
            with self.assertRaisesRegex(RuntimeError, 'synthetic thread start failure'):
                self.service.run()
        first.join.assert_called_once_with(); second.join.assert_not_called()
        self.assertFalse(state['locked'])

    def test_running_background_work_finishes_before_supervisor_lock_release(self):
        started = threading.Event(); release = threading.Event(); finished = threading.Event()
        state = {'locked': False}; errors = []
        class Lock:
            def __init__(self, path): pass
            def __enter__(self): state['locked'] = True
            def __exit__(self, *args): state['locked'] = False
        def loop(*args):
            started.set()
            if not release.wait(5): raise AssertionError('Test worker was not released')
            if not state['locked']: errors.append('Supervisor lock released before worker finished')
        def run():
            try: self.service.run()
            except BaseException as error: errors.append(error)
            finally: finished.set()
        with patch('v11_service.InstanceLock', Lock), patch.object(self.service, 'timed_loop', side_effect=loop), \
             patch.object(self.service, 'recover'), patch.object(self.service, 'update'), \
             patch.object(self.service, 'review', return_value=False):
            runner = threading.Thread(target=run)
            runner.start()
            try:
                self.assertTrue(started.wait(3))
                self.service.stop.set()
                self.assertFalse(finished.wait(.05))
                self.assertTrue(state['locked'])
            finally:
                self.service.stop.set(); release.set(); runner.join(5)
        self.assertFalse(runner.is_alive()); self.assertEqual(errors, [])
        self.assertFalse(state['locked'])

    def test_stopped_review_and_publication_leave_pending_state_untouched(self):
        manifest = self.manifest(status='prepared')
        before = self.stored(); manifest_bytes = manifest.read_bytes()
        self.service.stop.set()
        with patch('v11_service.powershell') as publisher, patch.object(self.service.queue, 'take') as take:
            self.assertFalse(self.service.review())
            self.service.apply(self.job, self.decision, self.service.work/'reviews/stopped')
            self.service.publish_manifest(manifest)
        publisher.assert_not_called(); take.assert_not_called()
        self.assertEqual(self.stored(), before)
        self.assertEqual(manifest.read_bytes(), manifest_bytes)

    def test_stop_while_waiting_for_publication_lock_prevents_send(self):
        before = self.stored(); stop = self.service.stop
        class StopAtLock:
            def __enter__(self): stop.set()
            def __exit__(self, *args): pass
        self.service.delivery_lock = StopAtLock()
        with patch('v11_service.delivery_guard.inspect', return_value=self.guard), \
             patch('v11_service.powershell') as publisher:
            self.service.apply(self.job, self.decision, self.service.work/'reviews/stopped')
        publisher.assert_not_called()
        self.assertEqual(self.stored(), before)
        self.assertFalse(list((self.service.work/'publications').glob('*.json')))

    def test_stop_during_preflight_does_not_mark_attempted_or_send(self):
        manifest = self.manifest(status='prepared'); before = self.stored()
        def validate(*args, **kwargs):
            self.assertIn('-ValidateOnly', args)
            self.service.stop.set()
            return {'valid': True, 'novelty_checked': True}
        with patch('v11_service.powershell', side_effect=validate) as publisher:
            self.service.publish_manifest(manifest)
        self.assertEqual(publisher.call_count, 1)
        self.assertEqual(read_json(manifest)['status'], 'prepared')
        self.assertEqual(self.stored(), before)

    def test_stop_during_attempt_marker_preserves_retryable_manifest(self):
        manifest = self.manifest(status='prepared'); before = self.stored()
        def save(path, value):
            save_json(path, value)
            if Path(path) == manifest and value.get('status') == 'attempted': self.service.stop.set()
        with patch('v11_service.powershell', return_value={'valid': True, 'novelty_checked': True}) as publisher, \
             patch('v11_service.save_json', side_effect=save):
            self.service.publish_manifest(manifest)
        self.assertEqual(publisher.call_count, 1)
        self.assertEqual(read_json(manifest)['status'], 'prepared')
        self.assertEqual(self.stored(), before)

    def test_stop_after_send_starts_still_completes_receipt_and_ack(self):
        manifest = self.manifest(status='prepared')
        def publish(root, name, *args, **kwargs):
            if '-ValidateOnly' not in args: self.service.stop.set()
            return self.fake_publish(root, name, *args, **kwargs)
        with patch('v11_service.powershell', side_effect=publish):
            self.service.publish_manifest(manifest)
        self.assertEqual(read_json(manifest)['status'], 'complete')
        self.assertEqual(self.stored()['status'], 'delivered')
        self.assertEqual(self.service.queue.get('last_delivery')['message_ids'], [999])

    def test_interrupted_scheduled_brief_does_not_claim_slot_complete(self):
        self.service.queue.finish(self.job, 'ready_day', 'Ready for next slot', self.decision)
        before = self.stored()
        with patch.object(self.service, 'apply', side_effect=lambda *args, **kwargs:self.service.stop.set()) as apply:
            self.service.deliver_scheduled_brief('2026-10-15T10:00+09:00')
        apply.assert_called_once()
        self.assertEqual(self.stored(), before)
        self.assertIsNone(self.service.queue.get('last_standard_brief_slot'))
        self.assertNotIn('scheduled_brief', self.service.health['stages'])

    def legacy(self, path):
        return str(PureWindowsPath(r'D:\Operations\newsautobot').joinpath(*Path(path).relative_to(self.root).parts))

    def test_moved_complete_receipt_is_acknowledged_without_resend_or_evidence_rewrite(self):
        for entry in ('recover', 'apply'):
            with self.subTest(entry=entry):
                self.service.stop.clear()
                manifest = self.manifest(receipt_status='complete')
                record = read_json(manifest)
                receipt = Path(record['arguments']['ReceiptFile'])
                for key in ('BatchFile', 'MessageFile', 'ArticleUrlsFile', 'NoveltyReviewFile', 'ReceiptFile', 'DecisionFile'):
                    record['arguments'][key] = self.legacy(record['arguments'][key])
                original_arguments = dict(record['arguments'])
                save_json(manifest, record)
                snapshot = self.root/'work/runs/run-1/snapshot.json'
                snapshot_bytes = snapshot.read_bytes(); receipt_bytes = receipt.read_bytes()
                def acknowledge(root, name, *arguments, **kwargs):
                    self.assertNotIn('-ValidateOnly', arguments)
                    args = dict(zip(arguments[::2], arguments[1::2]))
                    for key, value in original_arguments.items():
                        if key == 'Reason': self.assertEqual(args['-'+key], value)
                        else: self.assertTrue(Path(args['-'+key]).is_relative_to(self.root))
                    self.assertEqual(read_json(args['-ReceiptFile'])['status'], 'complete')
                    return {'status':'delivered', 'telegram_message_ids':[999], 'ack':{'delivered':1}}
                with patch.dict(os.environ, {'NEWS_LEGACY_ROOT':r'D:\Operations\newsautobot'}), \
                     patch('v11_service.powershell', side_effect=acknowledge) as publisher:
                    if entry == 'recover': self.service.recover()
                    else: self.service.apply(self.job, self.decision, self.service.work/'reviews/migrated')
                publisher.assert_called_once()
                self.assertEqual(read_json(manifest)['arguments'], original_arguments)
                self.assertEqual(read_json(manifest)['status'], 'complete')
                self.assertEqual(receipt.read_bytes(), receipt_bytes)
                self.assertEqual(snapshot.read_bytes(), snapshot_bytes)
                self.assertEqual(self.stored()['status'], 'delivered')

    def test_moved_snapshot_and_pending_mail_handoff_use_explicit_legacy_root(self):
        snapshot = self.root/'work/runs/run-1/snapshot.json'
        snapshot_bytes = snapshot.read_bytes()
        mail = self.service.work/'gmail/migrated'
        pending = {'newsletter_file':self.legacy(mail/'newsletter.json'),
                   'scan_file':self.legacy(mail/'scan.json'), 'directory':self.legacy(mail)}
        self.service.queue.set('pending_newsletter', pending)
        self.service.queue.set('latest_snapshot', self.legacy(snapshot))
        def collect(root, name, *args, **kwargs):
            self.assertEqual(args[args.index('-NewsletterFile')+1], str(mail/'newsletter.json'))
            return {'run_files':{'snapshot':str(snapshot)}}
        with patch.dict(os.environ, {'NEWS_LEGACY_ROOT':r'D:\Operations\newsautobot'}), \
             patch('v11_service.powershell', side_effect=collect), \
             patch('v11_mail_worker.finalize', return_value={'completed':True}) as finalize:
            packet, current = self.service._latest([self.job])
            self.assertEqual(packet.snapshot['run_id'], 'run-1')
            self.assertEqual(len(current), 1)
            self.service.collect()
        finalize.assert_called_once_with(self.root, mail/'scan.json')
        self.assertIsNone(self.service.queue.get('pending_newsletter'))
        self.assertEqual(read_json(mail/'finalized.json'), {'completed':True})
        self.assertEqual(snapshot.read_bytes(), snapshot_bytes)


if __name__ == '__main__':
    unittest.main()
