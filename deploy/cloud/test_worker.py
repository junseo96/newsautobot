"""Activation gates and shutdown tests never authenticate or start real workers."""
import json
import io
import os
from pathlib import Path
import select
import signal
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import worker


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='news-cloud-preflight-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / 'app'
        self.data = self.root / 'state'
        self.project.mkdir()
        (self.data / 'work/runs').mkdir(parents=True)
        (self.project / 'work').symlink_to(self.data / 'work', target_is_directory=True)
        self.marker = self.data / '.news-state-migration.json'
        self.metadata = {
            'source_root': r'C:\News Bot',
            'archive_manifest_sha256': 'a' * 64,
            'classification': 'private-operational-state',
        }
        self.marker.write_text(json.dumps(self.metadata))
        for relative, tables in worker.DATABASES.items():
            database = self.data / 'work' / relative
            database.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(database) as connection:
                for table in tables:
                    connection.execute(f'CREATE TABLE "{table}" (id INTEGER)')
        self.environment = patch.dict(os.environ, {
            **{name: 'test-placeholder' for name in worker.REQUIRED_ENV},
            'NEWS_GMAIL_TRANSPORT': 'gmail_api',
        }, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.commands = patch.object(worker.shutil, 'which', side_effect=lambda name: '/fake/bin/' + name)
        self.commands.start()
        self.addCleanup(self.commands.stop)

    def check(self):
        return worker.preflight(project=self.project, data=self.data)

    def test_complete_local_prerequisites_pass_without_network_or_mutation(self):
        before = {path.relative_to(self.data): path.read_bytes() for path in self.data.rglob('*') if path.is_file()}
        with patch.object(worker.subprocess, 'run', side_effect=AssertionError('No authentication during preflight')):
            report = self.check()
        self.assertTrue(report['ready'], report)
        self.assertIn('unverified', report['checks'])
        after = {path.relative_to(self.data): path.read_bytes() for path in self.data.rglob('*') if path.is_file()}
        self.assertEqual(before, after)

    def test_missing_credentials_fail_without_exposing_values(self):
        os.environ.pop('NEWS_GMAIL_REFRESH_TOKEN')
        os.environ['NEWS_CODEX_API_KEY'] = 'do-not-print-this-value'
        report = self.check()
        self.assertFalse(report['ready'])
        self.assertIn('missing environment variable: NEWS_GMAIL_REFRESH_TOKEN', report['problems'])
        self.assertNotIn('do-not-print-this-value', json.dumps(report))

    def test_missing_executable_and_wrong_transport_fail(self):
        os.environ['NEWS_GMAIL_TRANSPORT'] = 'connected_plugin'
        with patch.object(worker.shutil, 'which', return_value=None):
            report = self.check()
        self.assertFalse(report['ready'])
        self.assertIn('missing executable: codex', report['problems'])
        self.assertIn('missing executable: pwsh', report['problems'])
        self.assertTrue(any('NEWS_GMAIL_TRANSPORT' in problem for problem in report['problems']))

    def test_ephemeral_work_directory_fails(self):
        (self.project / 'work').unlink()
        (self.project / 'work').mkdir()
        report = self.check()
        self.assertFalse(report['ready'])
        self.assertTrue(any('persistent data directory' in problem for problem in report['problems']))

    def test_missing_or_corrupt_database_is_not_recreated(self):
        database = self.data / 'work/rss-news-monitor.db'
        database.unlink()
        report = self.check()
        self.assertFalse(report['ready'])
        self.assertFalse(database.exists())
        database.write_bytes(b'not a sqlite database')
        report = self.check()
        self.assertFalse(report['ready'])
        self.assertEqual(database.read_bytes(), b'not a sqlite database')

    def test_missing_receipt_directory_fails(self):
        (self.data / 'work/runs').rmdir()
        report = self.check()
        self.assertFalse(report['ready'])
        self.assertTrue(any('receipt directory' in problem for problem in report['problems']))

    def test_missing_or_malformed_migration_marker_fails_cleanly(self):
        self.marker.unlink()
        self.assertFalse(self.check()['ready'])
        for content in ('not json', 'null', '[]', '1', '"text"', '{}', '{"source_root":123}'):
            with self.subTest(content=content):
                self.marker.write_text(content)
                report = self.check()
                self.assertFalse(report['ready'])
                self.assertTrue(any('marker' in problem for problem in report['problems']))

    def test_migration_marker_source_root_cannot_contain_traversal(self):
        for source_root in ('/old/project/../elsewhere', r'C:\News Bot\..\elsewhere'):
            with self.subTest(source_root=source_root):
                self.marker.write_text(json.dumps({**self.metadata, 'source_root': source_root}))
                report = self.check()
                self.assertFalse(report['ready'])
                self.assertTrue(any('marker' in problem for problem in report['problems']))

    def test_marker_requires_classification_and_manifest_hash(self):
        for fields in ({'classification': 'public'}, {'classification': None},
                       {'archive_manifest_sha256': 'not-hex' * 9}, {'archive_manifest_sha256': 'g' * 64},
                       {'archive_manifest_sha256': 'a' * 63}, {'archive_manifest_sha256': None}):
            with self.subTest(fields=fields):
                self.marker.write_text(json.dumps({**self.metadata, **fields}))
                self.assertFalse(self.check()['ready'])

    def test_standalone_audit_prerequisites_do_not_require_credentials_or_external_tools(self):
        with patch.dict(os.environ, {}, clear=True), \
                patch.object(worker.shutil, 'which', side_effect=AssertionError('No external runtime needed')):
            report = worker.preflight(project=self.project, data=self.data, require_runtime=False)
        self.assertTrue(report['ready'], report)

    def test_configure_migration_uses_marker_root_instead_of_stale_environment(self):
        with patch.object(worker, 'data_directory', return_value=self.data), \
                patch.dict(os.environ, {'NEWS_LEGACY_ROOT': '/stale/previous/project'}):
            worker.configure_migration()
            self.assertEqual(os.environ['NEWS_LEGACY_ROOT'], self.metadata['source_root'])

    def test_activation_with_failed_preflight_does_not_authenticate_or_construct_service(self):
        with patch.dict(os.environ, {'NEWS_SERVICE_ENABLED': 'true'}), \
                patch.object(worker.signal, 'signal'), \
                patch.object(worker, 'preflight', return_value={'ready': False, 'problems': ['missing state']}), \
                patch.object(worker, 'authenticate_model', side_effect=AssertionError('Must not authenticate')), \
                patch('builtins.print'):
            self.assertEqual(worker.run(), 2)

    def test_activation_audits_mapped_state_before_authentication(self):
        def fail_audit():
            self.assertEqual(os.environ['NEWS_LEGACY_ROOT'], self.metadata['source_root'])
            raise RuntimeError('audit refused')

        with patch.dict(os.environ, {'NEWS_SERVICE_ENABLED': 'true'}), \
                patch.object(worker.signal, 'signal'), \
                patch.object(worker, 'preflight', return_value={'ready': True}), \
                patch.object(worker, 'data_directory', return_value=self.data), \
                patch.object(worker, 'audit_state', side_effect=fail_audit), \
                patch.object(worker, 'authenticate_model', side_effect=AssertionError('Must not authenticate')), \
                patch('builtins.print'):
            with self.assertRaisesRegex(RuntimeError, 'audit refused'):
                worker.run()

    def test_stop_during_audit_prevents_authentication(self):
        handlers = {}
        def stop_during_audit():
            handlers[signal.SIGTERM](signal.SIGTERM, None)

        with patch.dict(os.environ, {'NEWS_SERVICE_ENABLED': 'true'}), \
                patch.object(worker.signal, 'signal', side_effect=lambda sig, handler: handlers.update({sig: handler})), \
                patch.object(worker, 'preflight', return_value={'ready': True}), \
                patch.object(worker, 'data_directory', return_value=self.data), \
                patch.object(worker, 'audit_state', side_effect=stop_during_audit), \
                patch.object(worker, 'authenticate_model', side_effect=AssertionError('Must not authenticate')), \
                patch('builtins.print'):
            self.assertEqual(worker.run(), 0)

    def test_stop_during_service_construction_prevents_run(self):
        handlers = {}
        service = SimpleNamespace(stop=threading.Event(), config={}, run=lambda: self.fail('Service must not start'))
        def construct(_):
            handlers[signal.SIGTERM](signal.SIGTERM, None)
            return service

        with patch.dict(os.environ, {'NEWS_SERVICE_ENABLED': 'true'}), \
                patch.object(worker.signal, 'signal', side_effect=lambda sig, handler: handlers.update({sig: handler})), \
                patch.object(worker, 'preflight', return_value={'ready': True}), \
                patch.object(worker, 'data_directory', return_value=self.data), \
                patch.object(worker, 'audit_state'), patch.object(worker, 'authenticate_model'), \
                patch.dict(sys.modules, {'v11_service': SimpleNamespace(Service=construct)}), \
                patch.object(sys, 'path', sys.path[:]), patch('builtins.print'):
            self.assertEqual(worker.run(), 0)
        self.assertTrue(service.stop.is_set())

    def test_audit_command_checks_state_without_authentication(self):
        with patch.object(sys, 'argv', ['worker.py', 'audit']), \
                patch.object(worker, 'preflight', return_value={'ready': True}) as preflight, \
                patch.object(worker, 'data_directory', return_value=self.data), \
                patch.object(worker, 'audit_state') as audit, \
                patch.object(worker, 'authenticate_model', side_effect=AssertionError('Audit must not authenticate')), \
                patch('builtins.print'):
            self.assertEqual(worker.main(), 0)
        preflight.assert_called_once_with(require_runtime=False)
        audit.assert_called_once_with()


class StateAuditTests(unittest.TestCase):
    def test_existing_read_only_auditor_runs_from_project_with_bounded_timeout(self):
        result = subprocess.CompletedProcess(['python'], 0, '{"private":"details"}', '')
        with patch.object(worker.subprocess, 'run', return_value=result) as command, patch('builtins.print') as output:
            worker.audit_state()
        args, kwargs = command.call_args
        self.assertEqual(args[0], [sys.executable, str(worker.PROJECT / 'outputs/rss-news-monitor/audit_migration.py')])
        self.assertEqual(kwargs['cwd'], worker.PROJECT)
        self.assertEqual(kwargs['timeout'], 300)
        self.assertEqual(kwargs['stdout'], subprocess.PIPE)
        self.assertEqual(kwargs['stderr'], subprocess.PIPE)
        output.assert_not_called()

    def test_failed_audit_never_exposes_captured_private_output(self):
        result = subprocess.CompletedProcess(['python'], 1, 'private receipt text', 'private path traceback')
        with patch.object(worker.subprocess, 'run', return_value=result):
            with self.assertRaisesRegex(RuntimeError, 'audit failed') as caught:
                worker.audit_state()
        self.assertNotIn('private', str(caught.exception))

    def test_timeout_and_launch_failures_do_not_expose_private_details(self):
        failures = (subprocess.TimeoutExpired(['private command'], 300, output='private receipt', stderr='private token'),
                    OSError('private path'))
        for failure in failures:
            with self.subTest(failure=type(failure).__name__), patch.object(worker.subprocess, 'run', side_effect=failure):
                with self.assertRaisesRegex(RuntimeError, 'audit could not complete') as caught:
                    worker.audit_state()
                self.assertNotIn('private', str(caught.exception))
                self.assertTrue(caught.exception.__suppress_context__)


class AuthenticationTests(unittest.TestCase):
    def test_key_is_only_passed_on_stdin(self):
        result = subprocess.CompletedProcess(['codex'], 0, '', '')
        with patch.dict(os.environ, {'NEWS_CODEX_API_KEY': 'test-key-never-authenticated'}), \
                patch.object(worker.subprocess, 'run', return_value=result) as command:
            worker.authenticate_model()
        args, kwargs = command.call_args
        self.assertNotIn('test-key-never-authenticated', repr(args))
        self.assertEqual(kwargs['input'], 'test-key-never-authenticated\n')

    def test_authentication_failures_do_not_leak_process_output(self):
        result = subprocess.CompletedProcess(['codex'], 1, 'secret stdout', 'secret stderr')
        with patch.dict(os.environ, {'NEWS_CODEX_API_KEY': 'secret key'}), \
                patch.object(worker.subprocess, 'run', return_value=result):
            with self.assertRaises(RuntimeError) as caught:
                worker.authenticate_model()
        self.assertNotIn('secret', str(caught.exception))


class CycleTests(unittest.TestCase):
    def setUp(self):
        self.service = SimpleNamespace(stop=threading.Event(), config={}, run=lambda: None)
        self.timers = []
        self.timer_class = threading.Timer
        fixtures = (
            patch.dict(os.environ, {'NEWS_SERVICE_ENABLED': 'true'}),
            patch.object(worker.signal, 'signal'),
            patch.object(worker, 'preflight', return_value={'ready': True}),
            patch.object(worker, 'configure_migration'),
            patch.object(worker, 'audit_state'),
            patch.object(worker, 'authenticate_model'),
            patch.dict(sys.modules, {'v11_service': SimpleNamespace(Service=lambda _: self.service)}),
            patch.object(sys, 'path', sys.path[:]),
        )
        for fixture in fixtures:
            fixture.start()
            self.addCleanup(fixture.stop)

    def short_timer(self, seconds, callback):
        self.assertEqual(seconds, 600)
        timer = self.timer_class(0.03, callback)
        self.timers.append(timer)
        return timer

    def test_cycle_deadline_requests_graceful_stop_and_waits_for_service_drain(self):
        drained = threading.Event()
        threads = []

        def service_run():
            def in_flight_work():
                if not self.service.stop.wait(2):
                    return
                # Represent completion of a local receipt write after stop was requested.
                time.sleep(0.03)
                drained.set()
            thread = threading.Thread(target=in_flight_work)
            threads.append(thread)
            thread.start()
            self.assertTrue(self.service.stop.wait(2))
            thread.join(timeout=2)

        self.service.run = service_run
        with patch.object(worker.threading, 'Timer', side_effect=self.short_timer), patch('builtins.print') as output:
            self.assertEqual(worker.run(seconds=600), 0)
        self.assertTrue(drained.is_set())
        self.assertFalse(threads[0].is_alive())
        self.assertFalse(self.timers[0].is_alive())
        statuses = [json.loads(call.args[0]).get('status') for call in output.call_args_list]
        self.assertEqual([status for status in statuses if status], ['started', 'stopped'])

    def test_early_service_return_cancels_and_joins_timer(self):
        def long_timer(seconds, callback):
            timer = self.timer_class(seconds, callback)
            self.timers.append(timer)
            return timer

        with patch.object(worker.threading, 'Timer', side_effect=long_timer), patch('builtins.print'):
            self.assertEqual(worker.run(seconds=3600), 0)
        self.assertTrue(self.service.stop.is_set())
        self.assertTrue(self.timers[0].finished.is_set())
        self.assertFalse(self.timers[0].is_alive())

    def test_service_error_cancels_and_joins_timer(self):
        def fail():
            raise RuntimeError('fake service failed')
        self.service.run = fail
        with patch.object(worker.threading, 'Timer', side_effect=self.short_timer), patch('builtins.print'):
            with self.assertRaisesRegex(RuntimeError, 'fake service failed'):
                worker.run(seconds=600)
        self.assertTrue(self.service.stop.is_set())
        self.assertFalse(self.timers[0].is_alive())

    def test_disabled_cycle_returns_without_waiting_or_starting_work(self):
        with patch.dict(os.environ, {'NEWS_SERVICE_ENABLED': 'false'}), \
                patch.object(worker, 'preflight', side_effect=AssertionError('Disabled cycle must stay idle')), \
                patch.object(worker.threading, 'Timer', side_effect=AssertionError('No timer for disabled cycle')), \
                patch('builtins.print') as output:
            self.assertEqual(worker.run(seconds=600), 0)
        self.assertEqual(json.loads(output.call_args.args[0])['status'], 'paused')

    def test_cycle_cli_defaults_to_ten_minutes_and_accepts_explicit_duration(self):
        for extra, expected in (([], 600), (['--seconds', '30'], 30)):
            with self.subTest(extra=extra), patch.object(sys, 'argv', ['worker.py', 'cycle', *extra]), \
                    patch.object(worker, 'run', return_value=0) as run:
                self.assertEqual(worker.main(), 0)
                run.assert_called_once_with(seconds=expected)

    def test_cycle_cli_rejects_invalid_or_excessive_duration(self):
        for value in ('0', '-1', '3601', '100000000', 'nan', '1.5'):
            with self.subTest(value=value), patch.object(sys, 'argv', ['worker.py', 'cycle', '--seconds', value]), \
                    patch.object(sys, 'stderr', io.StringIO()), patch.object(worker, 'run') as run:
                with self.assertRaises(SystemExit) as caught:
                    worker.main()
                self.assertEqual(caught.exception.code, 2)
                run.assert_not_called()

    def test_cycle_activation_failures_return_nonzero_without_starting_service(self):
        for stage in ('preflight', 'audit_state', 'authenticate_model'):
            failure = {'return_value': {'ready': False}} if stage == 'preflight' else {'side_effect': RuntimeError('activation failed')}
            with self.subTest(stage=stage), patch.object(sys, 'argv', ['worker.py', 'cycle']), \
                    patch.object(worker, stage, **failure), \
                    patch.object(worker.threading, 'Timer', side_effect=AssertionError('Failed activation cannot start cycle')), \
                    patch('builtins.print'):
                self.assertEqual(worker.main(), 2)


@unittest.skipIf(os.name == 'nt', 'Hosted Linux signal handling')
class PausedEntrypointTests(unittest.TestCase):
    def test_enabled_entrypoint_forwards_sigterm_to_service_stop(self):
        with tempfile.TemporaryDirectory(prefix='news-cloud-stop-') as directory:
            data = Path(directory)
            (data / '.news-state-migration.json').write_text(json.dumps({
                'source_root': str(worker.PROJECT), 'classification': 'private-operational-state',
                'archive_manifest_sha256': 'a' * 64,
            }))
            bootstrap = (
                'import sys, threading, types\n'
                f'sys.path.insert(0, {str(Path(worker.__file__).parent)!r})\n'
                'import worker\n'
                'worker.preflight = lambda: {"ready": True, "problems": []}\n'
                'worker.audit_state = lambda: None\n'
                'worker.authenticate_model = lambda: None\n'
                'module = types.ModuleType("v11_service")\n'
                'class FakeService:\n'
                '    def __init__(self, root):\n'
                '        self.stop = threading.Event()\n'
                '        self.config = {}\n'
                '    def run(self):\n'
                '        print("SERVICE_WAITING", flush=True)\n'
                '        if not self.stop.wait(20): raise RuntimeError("stop not forwarded")\n'
                'module.Service = FakeService\n'
                'sys.modules["v11_service"] = module\n'
                'raise SystemExit(worker.run())\n'
            )
            environment = os.environ.copy()
            environment.update(NEWS_SERVICE_ENABLED='true', NEWS_DATA_DIR=str(data))
            process = subprocess.Popen([sys.executable, '-c', bootstrap], env=environment,
                                       stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, text=True)
            try:
                # Read two startup lines with an outer timeout so a broken entrypoint cannot hang CI.
                import threading
                lines = []
                reader = threading.Thread(target=lambda: lines.extend(process.stdout.readline() for _ in range(2)), daemon=True)
                reader.start()
                reader.join(timeout=5)
                self.assertFalse(reader.is_alive(), 'Enabled entrypoint did not reach fake service')
                self.assertEqual(lines[-1].strip(), 'SERVICE_WAITING')
                process.send_signal(signal.SIGTERM)
                out, err = process.communicate(timeout=5)
                self.assertEqual(process.returncode, 0, err)
                self.assertEqual(out, '')
            finally:
                if process.poll() is None:
                    process.kill()
                process.communicate(timeout=5)

    def test_paused_entrypoint_is_idle_and_exits_on_sigterm_without_side_effects(self):
        with tempfile.TemporaryDirectory(prefix='news-cloud-paused-') as directory:
            data = Path(directory) / 'must-not-be-created'
            bootstrap = (
                'import sys; '
                f'sys.path.insert(0, {str(Path(worker.__file__).parent)!r}); '
                'import worker\n'
                'def forbidden(*args, **kwargs): raise AssertionError("paused entrypoint performed work")\n'
                'worker.preflight = forbidden\n'
                'worker.audit_state = forbidden\n'
                'worker.authenticate_model = forbidden\n'
                'raise SystemExit(worker.run())\n'
            )
            environment = os.environ.copy()
            environment.update(NEWS_SERVICE_ENABLED='false', NEWS_DATA_DIR=str(data))
            process = subprocess.Popen([sys.executable, '-c', bootstrap], env=environment,
                                       stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, text=True)
            try:
                readable, _, _ = select.select([process.stdout], [], [], 5)
                self.assertTrue(readable, 'Paused entrypoint must announce readiness promptly')
                line = process.stdout.readline()
                if not line:
                    self.fail('Paused entrypoint failed: ' + process.communicate(timeout=5)[1])
                self.assertEqual(json.loads(line)['status'], 'paused')
                self.assertIsNone(process.poll())
                process.send_signal(signal.SIGTERM)
                out, err = process.communicate(timeout=5)
                self.assertEqual(process.returncode, 0, err)
                self.assertEqual(out, '')
                self.assertFalse(data.exists())
            finally:
                if process.poll() is None:
                    process.kill()
                process.communicate(timeout=5)


if __name__ == '__main__':
    unittest.main()
