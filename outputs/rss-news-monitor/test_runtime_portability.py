"""Cloud runtime regressions use temporary files and local child processes only."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from v11_runtime import powershell, run_process


class ProcessPortabilityTests(unittest.TestCase):
    def test_stdin_stdout_stderr_and_exit_code_survive(self):
        code, out, err = run_process([sys.executable, '-c',
            'import sys; print(sys.stdin.read()); print("failure detail", file=sys.stderr); sys.exit(3)'],
            stdin='기사 내용', timeout=5)
        self.assertEqual(code, 3)
        self.assertEqual(out.strip(), '기사 내용')
        self.assertEqual(err.strip(), 'failure detail')

    @unittest.skipIf(os.name == 'nt', 'POSIX process group regression')
    def test_timeout_terminates_descendants_holding_output_pipes(self):
        self.assert_timeout_terminates_descendants(parent_waits=True)

    @unittest.skipIf(os.name == 'nt', 'POSIX process group regression')
    def test_timeout_terminates_descendants_after_parent_exits(self):
        self.assert_timeout_terminates_descendants(parent_waits=False)

    def assert_timeout_terminates_descendants(self, parent_waits):
        with tempfile.TemporaryDirectory() as directory:
            ready = Path(directory) / 'ready'
            survived = Path(directory) / 'survived'
            descendant = (
                'import pathlib, time; '
                f'pathlib.Path({str(ready)!r}).write_text("ready"); '
                'time.sleep(1.5); '
                f'pathlib.Path({str(survived)!r}).write_text("orphan")'
            )
            parent = (
                'import subprocess, sys, time; '
                f'subprocess.Popen([sys.executable, "-c", {descendant!r}]); '
            )
            if parent_waits:
                parent += 'time.sleep(5)'
            with self.assertRaises(TimeoutError):
                run_process([sys.executable, '-c', parent], timeout=1)
            self.assertTrue(ready.exists(), 'Descendant must have started before the timeout')
            time.sleep(0.8)
            self.assertFalse(survived.exists(), 'Timed out descendants must not keep executing')

    def test_powershell_selects_platform_host_and_preserves_arguments(self):
        for platform, executable in (('nt', 'powershell.exe'), ('posix', 'pwsh')):
            with self.subTest(platform=platform), patch('v11_runtime.os', SimpleNamespace(name=platform)), \
                    patch('v11_runtime.run_process', return_value=(0, '\ufeff {"ok":true}\n', '')) as run:
                root = Path(tempfile.gettempdir()) / 'news bot'
                self.assertEqual(powershell(root, 'Run-Collector.ps1', '-OutputFile', '한글 file.json', timeout=19), {'ok': True})
                run.assert_called_once_with([
                    executable, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                    root / 'outputs/rss-news-monitor/Run-Collector.ps1', '-OutputFile', '한글 file.json'],
                    timeout=19, cwd=root)

    def test_powershell_failure_retains_exit_and_stderr(self):
        with patch('v11_runtime.run_process', return_value=(7, '', 'failure detail')):
            with self.assertRaisesRegex(RuntimeError, 'Check.ps1 exited 7: failure detail'):
                powershell('.', 'Check.ps1')

    def test_powershell_requires_json_on_success(self):
        with patch('v11_runtime.run_process', return_value=(0, 'plain output', '')):
            with self.assertRaisesRegex(ValueError, 'did not return JSON: plain output'):
                powershell('.', 'Check.ps1')


class PowerShellPortabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.shell = shutil.which('pwsh') or shutil.which('powershell.exe')
        if not cls.shell:
            raise unittest.SkipTest('PowerShell is required for wrapper integration tests')

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='news-runtime-portability-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.scripts = self.root / 'outputs/rss-news-monitor'
        self.scripts.mkdir(parents=True)
        for filename in ('Resolve-Python.ps1', 'Run-Collector.ps1'):
            shutil.copyfile(Path(__file__).with_name(filename), self.scripts / filename)
        self.environment = os.environ.copy()
        self.environment['XDG_CACHE_HOME'] = str(self.root / 'cache')
        self.environment['XDG_CONFIG_HOME'] = str(self.root / 'config')
        self.environment['XDG_DATA_HOME'] = str(self.root / 'data')
        self.environment.pop('USERPROFILE', None)
        self.environment['NEWS_PYTHON'] = sys.executable
        self.environment['NEWS_DART_KEY'] = 'test-key-never-sent'

    def run_script(self, script):
        path = self.root / 'test.ps1'
        path.write_text(script, encoding='utf-8-sig')
        result = subprocess.run([self.shell, '-NoProfile', '-File', str(path)],
                                cwd=self.root, env=self.environment, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout.lstrip('\ufeff'))

    def test_explicit_python_resolves_without_userprofile(self):
        result = self.run_script(". './outputs/rss-news-monitor/Resolve-Python.ps1'\n@{python=(Resolve-NewsPython)} | ConvertTo-Json")
        self.assertEqual(result['python'], sys.executable)

    @unittest.skipIf(os.name == 'nt', 'POSIX Python discovery')
    def test_python3_discovered_without_userprofile_or_override(self):
        self.environment.pop('NEWS_PYTHON')
        result = self.run_script(". './outputs/rss-news-monitor/Resolve-Python.ps1'\n@{python=(Resolve-NewsPython)} | ConvertTo-Json")
        self.assertEqual(Path(result['python']), Path(shutil.which('python3')))

    def test_collector_inherits_key_and_preserves_callers_value(self):
        (self.scripts / 'collector.py').write_text(
            'import os\nassert os.environ["NEWS_DART_KEY"] == "test-key-never-sent"\n', encoding='utf-8')
        # An inherited cloud key takes priority over an old Windows DPAPI file.
        secrets = self.root / '.news-monitor-secrets'
        secrets.mkdir()
        (secrets / 'dart-key.dpapi').write_text('not-decryptable', encoding='utf-8')
        result = self.run_script("& './outputs/rss-news-monitor/Run-Collector.ps1'\n@{key_unchanged=($env:NEWS_DART_KEY -eq 'test-key-never-sent')} | ConvertTo-Json")
        self.assertTrue(result['key_unchanged'])

    def test_collector_failure_preserves_key_and_exit_status(self):
        (self.scripts / 'collector.py').write_text('import sys\nsys.exit(7)\n', encoding='utf-8')
        result = self.run_script("try { & './outputs/rss-news-monitor/Run-Collector.ps1' } catch { $failure = $_.Exception.Message }\n@{key_unchanged=($env:NEWS_DART_KEY -eq 'test-key-never-sent'); failure=$failure} | ConvertTo-Json")
        self.assertTrue(result['key_unchanged'])
        self.assertIn('7', result['failure'])


if __name__ == '__main__':
    unittest.main()
