"""Cloud credential and receipt regression tests with a fake Telegram transport.

Scripts run in an isolated temporary checkout with synthetic credentials only.
"""
import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


SOURCE = Path(__file__).resolve().parent.parent / 'telegram-forwarder'
TOKEN = 'synthetic-cloud-token'


class TelegramCredentialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.shell = next((shutil.which(command) for command in ('pwsh', 'pwsh.exe', 'powershell.exe')
                          if shutil.which(command)), None)
        if not cls.shell:
            raise unittest.SkipTest('PowerShell is required for the credential tests')

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='telegram-cloud-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.sender = self.root / 'outputs/telegram-forwarder'
        self.sender.mkdir(parents=True)
        (self.root / 'work').mkdir()
        for name in ('Telegram-Format.ps1', 'Telegram-Auth.ps1', 'Send-Telegram.ps1',
                     'Send-VerifiedTelegram.ps1', 'Test-VerifiedTelegram.ps1'):
            shutil.copy2(SOURCE / name, self.sender / name)
        self.config = self.root / 'local-config'
        self.config.mkdir()
        (self.config / 'bot-token.dpapi').write_text('invalid-local-credential', encoding='utf-8')
        (self.config / 'chat-id.txt').write_text('local-chat-must-not-be-used', encoding='utf-8')

    def run_script(self, body, credentials=None):
        environment = dict(os.environ)
        for name, directory in (('XDG_CACHE_HOME', 'cache'), ('XDG_CONFIG_HOME', 'config'),
                                ('XDG_DATA_HOME', 'data')):
            environment[name] = str(self.root / directory)
        for name in ('NEWS_TELEGRAM_BOT_TOKEN', 'NEWS_TELEGRAM_CHAT_ID'):
            environment.pop(name, None)
        if credentials is None:
            credentials = {'NEWS_TELEGRAM_BOT_TOKEN': TOKEN, 'NEWS_TELEGRAM_CHAT_ID': '-100123'}
        environment.update(credentials)
        script = r'''
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object Text.UTF8Encoding($false)
$root = '__ROOT__'
$sender = Join-Path $root 'outputs/telegram-forwarder/Send-Telegram.ps1'
$config = Join-Path $root 'local-config'
$receipt = Join-Path $root 'receipt.json'
$global:FakeTelegramCalls = 0
function Invoke-RestMethod {
    param($Method, $Uri, $Body, $TimeoutSec)
    $global:FakeTelegramCalls++
    if ($Uri -ne 'https://api.telegram.org/botsynthetic-cloud-token/sendMessage' -or $Body.chat_id -ne '-100123') {
        throw 'Unexpected synthetic credential selection'
    }
    return @{ok=$true;result=@{message_id=100+$global:FakeTelegramCalls}}
}
'''.replace('__ROOT__', str(self.root).replace("'", "''")) + body
        encoded = base64.b64encode(script.encode('utf-16-le')).decode('ascii')
        result = subprocess.run(
            [self.shell, '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-EncodedCommand', encoded],
            capture_output=True, text=True, encoding='utf-8', timeout=60, env=environment,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout.lstrip('\ufeff'))

    def test_pair_bypasses_local_files_in_both_senders(self):
        result = self.run_script(r'''
& $sender -Text 'Synthetic cloud message' -ConfigDir $config 6>$null
& $sender -Text 'Synthetic cloud message' -ConfigDir $config -ReceiptFile $receipt 6>$null
$proof = Get-Content -Raw $receipt | ConvertFrom-Json
@{calls=$global:FakeTelegramCalls;status=$proof.status;ids=@($proof.telegram_message_ids)} | ConvertTo-Json -Compress
''')
        self.assertEqual(result, {'calls': 2, 'status': 'complete', 'ids': [102]})
        self.assertEqual((self.config / 'bot-token.dpapi').read_text(), 'invalid-local-credential')
        self.assertNotIn(TOKEN, (self.root / 'receipt.json').read_text(encoding='utf-8-sig'))

    def test_incomplete_pair_never_falls_back_or_calls_transport(self):
        for credentials in ({'NEWS_TELEGRAM_BOT_TOKEN': TOKEN}, {'NEWS_TELEGRAM_CHAT_ID': '-100123'},
                            {'NEWS_TELEGRAM_BOT_TOKEN': TOKEN, 'NEWS_TELEGRAM_CHAT_ID': ' '},
                            {'NEWS_TELEGRAM_BOT_TOKEN': ' ', 'NEWS_TELEGRAM_CHAT_ID': '-100123'}):
            with self.subTest(names=sorted(credentials)):
                result = self.run_script(r'''
$failures = @()
try { & $sender -Text 'Synthetic cloud message' -ConfigDir $config 6>$null } catch { $failures += $_.Exception.Message }
try { & $sender -Text 'Synthetic cloud message' -ConfigDir $config -ReceiptFile $receipt 6>$null } catch { $failures += $_.Exception.Message }
@{calls=$global:FakeTelegramCalls;failures=$failures} | ConvertTo-Json -Compress
''', credentials)
                self.assertEqual(result['calls'], 0)
                self.assertEqual(len(result['failures']), 2)
                self.assertTrue(all('must be configured together' in error for error in result['failures']))
                self.assertNotIn(TOKEN, json.dumps(result))

    def test_transport_errors_hide_credentials_and_uncertain_receipt_blocks_retry(self):
        result = self.run_script(r'''
function Invoke-RestMethod {
    param($Method, $Uri, $Body, $TimeoutSec)
    $global:FakeTelegramCalls++
    throw ('Synthetic timeout containing ' + $Uri)
}
$failures = @()
try { & $sender -Text 'Synthetic cloud message' -ConfigDir $config 6>$null } catch { $failures += $_.Exception.Message }
try { & $sender -Text 'Synthetic cloud message' -ConfigDir $config -ReceiptFile $receipt 6>$null } catch { $failures += $_.Exception.Message }
try { & $sender -Text 'Synthetic cloud message' -ConfigDir $config -ReceiptFile $receipt 6>$null } catch { $failures += $_.Exception.Message }
$proof = Get-Content -Raw $receipt | ConvertFrom-Json
@{calls=$global:FakeTelegramCalls;failures=$failures;status=$proof.status;in_flight=$proof.in_flight_part} | ConvertTo-Json -Compress
''')
        self.assertEqual(result['calls'], 2)
        self.assertEqual(result['status'], 'uncertain')
        self.assertEqual(result['in_flight'], 0)
        self.assertEqual(len(result['failures']), 3)
        self.assertNotIn(TOKEN, json.dumps(result))
        self.assertNotIn('https://', json.dumps(result))
        self.assertIn('Delivery verification required', result['failures'][-1])

    def test_windows_file_fallback_or_linux_explicit_environment_requirement(self):
        result = self.run_script(r'''
$dummy = ConvertTo-SecureString 'synthetic-cloud-token' -AsPlainText -Force
try { [IO.File]::WriteAllText((Join-Path $config 'bot-token.dpapi'), (ConvertFrom-SecureString $dummy)) }
finally { $dummy.Dispose() }
[IO.File]::WriteAllText((Join-Path $config 'chat-id.txt'), '-100123')
$failure = $null
try { & $sender -Text 'Synthetic cloud message' -ConfigDir $config -ReceiptFile $receipt 6>$null }
catch { $failure = $_.Exception.Message }
@{windows=([Environment]::OSVersion.Platform -eq [PlatformID]::Win32NT);calls=$global:FakeTelegramCalls;failure=$failure} | ConvertTo-Json -Compress
''', {})
        if result['windows']:
            self.assertEqual(result['calls'], 1)
            self.assertIsNone(result['failure'])
        else:
            self.assertEqual(result['calls'], 0)
            self.assertIn('requires NEWS_TELEGRAM_BOT_TOKEN and NEWS_TELEGRAM_CHAT_ID', result['failure'])

    def test_existing_mock_receipt_resume_and_novelty_regressions(self):
        result = self.run_script(r'''
$output = & (Join-Path $root 'outputs/telegram-forwarder/Test-VerifiedTelegram.ps1') 6>$null
@{output=($output -join "`n")} | ConvertTo-Json -Compress
''')
        self.assertIn('PASS: validation', result['output'])
        self.assertIn('uncertain-send protection (mock transport only)', result['output'])


if __name__ == '__main__':
    unittest.main()
