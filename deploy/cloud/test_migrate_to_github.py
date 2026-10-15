"""Windows migration helper checks with synthetic state and mocked processes.

PowerShell exercises the actual orchestration; no GitHub request, DPAPI access,
secret registration, source shutdown, or production-state write is performed.
"""
import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).with_name("Migrate-ToGitHub.ps1")


def ps_literal(value):
    return "'" + str(value).replace("'", "''") + "'"


class MigrationHelperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.shell = next((shutil.which(name) for name in ("pwsh", "pwsh.exe", "powershell.exe")
                          if shutil.which(name)), None)
        if not cls.shell:
            raise unittest.SkipTest("PowerShell is required for migration helper tests")

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="news-migration-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "source"
        self.source.mkdir()
        (self.source / "work").mkdir()
        self.private = self.root / "private"
        self.private.mkdir()

    def run_powershell(self, body, *, source=True, mock_native=True, credentials=None):
        environment = {name: value for name, value in os.environ.items()
                       if not name.startswith(("NEWS_", "GH_", "GITHUB_"))}
        environment.update(credentials or {})
        environment.update({name: str(self.root / directory) for name, directory in (
            ("XDG_CACHE_HOME", "cache"), ("XDG_CONFIG_HOME", "config"), ("XDG_DATA_HOME", "data"))})
        setup = "\n".join((
            "$ErrorActionPreference = 'Stop'",
            "[Console]::OutputEncoding = New-Object Text.UTF8Encoding($false)",
            "$helper = " + ps_literal(SCRIPT),
            "$testShell = " + ps_literal(self.shell),
            "$testSource = " + ps_literal(self.source),
            "$testPrivate = " + ps_literal(self.private),
            "$global:nativeCalls = @()",
        ))
        if source:
            setup += "\n. $helper -Phase Prepare -SourceRoot $testSource\n"
        if source and mock_native:
            setup += r'''
function Invoke-MigrationNative {
    param([string]$File, [string[]]$Arguments, [string]$InputText, [int]$TimeoutSeconds = 60)
    $global:nativeCalls += @{file=$File;arguments=@($Arguments);hasInput=[bool]$InputText}
    throw 'Unexpected process invocation in isolated test'
}
'''
        encoded = base64.b64encode((setup + "\n" + body).encode("utf-16-le")).decode("ascii")
        result = subprocess.run(
            [self.shell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded],
            capture_output=True, text=True, encoding="utf-8", env=environment, timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout.lstrip("\ufeff"))

    def test_powershell_parser_accepts_script(self):
        result = self.run_powershell(r'''
$tokens = $null
$parseErrors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile($helper, [ref]$tokens, [ref]$parseErrors)
@{errors=@($parseErrors | ForEach-Object {$_.Message});hasMain=[bool]($ast.Find({
    param($node)
    $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Invoke-NewsGitHubMigration'
}, $true))} | ConvertTo-Json -Compress -Depth 10
''', source=False)
        self.assertEqual(result["errors"], [])
        self.assertTrue(result["hasMain"])

    def test_dot_sourcing_does_not_start_migration(self):
        result = self.run_powershell(r'''
@{nativeCalls=@($global:nativeCalls);sourceFiles=@(Get-ChildItem -LiteralPath $testSource -Recurse -File)} | ConvertTo-Json -Compress
''')
        self.assertEqual(result, {"nativeCalls": [], "sourceFiles": []})

    def test_native_wrapper_preserves_argument_boundaries_and_uses_stdin(self):
        argument = 'path with spaces\\quoted"value\\'
        stdin = "synthetic-secret-passed-only-through-stdin\nsecond line"
        child = self.private / "synthetic process.ps1"
        child.write_text(r'''
param([string]$Value)
@{argument=$Value;input=[Console]::In.ReadToEnd()} | ConvertTo-Json -Compress
''', encoding="utf-8")
        result = self.run_powershell(
            "$response = Invoke-MigrationNative -File $testShell -Arguments "
            "@('-NoProfile','-NonInteractive','-File'," + ps_literal(child) + ",'-Value'," + ps_literal(argument)
            + ") -InputText " + ps_literal(stdin)
            + "\n$response\n", mock_native=False)
        self.assertEqual(result["argument"], argument)
        # The native writer may terminate the supplied input with one newline.
        self.assertEqual(result["input"].rstrip("\r\n"), stdin)

    def test_native_wrapper_suppresses_credential_bearing_process_errors(self):
        secret = "synthetic-sensitive-error-marker"
        child = self.private / "failing process.ps1"
        child.write_text(
            "[Console]::Out.WriteLine('" + secret + "')\n"
            "[Console]::Error.WriteLine('" + secret + "')\nexit 7\n", encoding="utf-8")
        result = self.run_powershell(
            "$failure = $null\ntry { $null = Invoke-MigrationNative -File $testShell -Arguments "
            "@('-NoProfile','-NonInteractive','-File'," + ps_literal(child) + ") }\n"
            "catch {$failure = $_.Exception.Message}\n"
            "@{failure=$failure} | ConvertTo-Json -Compress\n", mock_native=False)
        self.assertTrue(result["failure"])
        self.assertNotIn(secret, result["failure"])

    def test_cutover_requires_explicit_stopped_before_prerequisites_or_processes(self):
        result = self.run_powershell(r'''
$global:toolChecks = 0
function Get-MigrationTools {
    param($SourceRoot, $CodeRoot)
    $global:toolChecks++
    throw 'Prerequisites must not run without stopped confirmation'
}
$failure = $null
try { Invoke-NewsGitHubMigration -Phase Cutover -SourceRoot $testSource 6>$null }
catch {$failure = $_.Exception.Message}
@{failure=$failure;toolChecks=$global:toolChecks;nativeCalls=@($global:nativeCalls)} | ConvertTo-Json -Compress
''')
        self.assertTrue(result["failure"])
        self.assertEqual(result["toolChecks"], 0)
        self.assertEqual(result["nativeCalls"], [])

    def test_existing_remote_identity_is_never_rotated_when_local_key_is_missing(self):
        result = self.run_powershell(r'''
$failure = $null
try {
    $null = Get-MigrationIdentity -IdentityFile (Join-Path $testPrivate 'absent-identity.txt') -Keygen 'mock-keygen' -RemoteExists $true
} catch {$failure = $_.Exception.Message}
@{failure=$failure;nativeCalls=@($global:nativeCalls);files=@(Get-ChildItem -LiteralPath $testPrivate -File)} | ConvertTo-Json -Compress
''')
        self.assertTrue(result["failure"])
        self.assertEqual(result["nativeCalls"], [])
        self.assertEqual(result["files"], [])

    def test_existing_local_identity_is_not_overwritten_by_a_different_environment_key(self):
        identity = self.private / "identity.txt"
        original = "AGE-SECRET-KEY-1EXISTING\n"
        identity.write_text(original, encoding="ascii")
        result = self.run_powershell(r'''
$failure = $null
try {
    $null = Get-MigrationIdentity -IdentityFile (Join-Path $testPrivate 'identity.txt') -Keygen 'mock-keygen' -RemoteExists $true
} catch {$failure = $_.Exception.Message}
@{failure=$failure;nativeCalls=@($global:nativeCalls)} | ConvertTo-Json -Compress
''', credentials={"NEWS_STATE_AGE_KEY": "AGE-SECRET-KEY-1DIFFERENT"})
        self.assertTrue(result["failure"])
        self.assertEqual(result["nativeCalls"], [])
        self.assertEqual(identity.read_text(encoding="ascii"), original)

    def run_phase(self, phase, failure=""):
        body = r'''
$global:scenario = __SCENARIO__
$global:encryptTemp = $null
$global:activationCalled = $false
$initialTemp = [Environment]::GetEnvironmentVariable('TEMP','Process')
$initialTmp = [Environment]::GetEnvironmentVariable('TMP','Process')
$initialTmpdir = 'synthetic-original-temp-override'
[Environment]::SetEnvironmentVariable('TMPDIR', $initialTmpdir, 'Process')
function Get-MigrationTools {
    param($SourceRoot, $CodeRoot)
    return @{Gh='mock-gh';Age='mock-age';Keygen='mock-keygen';Python='mock-python'}
}
function Get-MigrationInputs {
    param($SourceRoot)
    return @{Secrets=@{NEWS_CODEX_API_KEY='synthetic-model-secret';NEWS_GRID_TOKEN='synthetic-grid-secret'};GridUrl='https://dashboard.example/project'}
}
function Get-MigrationIdentity {
    param($IdentityFile, $Keygen, $RemoteExists, [switch]$ExistingOnly)
    return 'AGE-SECRET-KEY-1SYNTHETIC'
}
function Wait-MigrationRun {
    param($Gh, $Repository, $Workflow, $Title, $Minutes)
    $global:nativeCalls += @{file='wait';arguments=@($Workflow);input=$null}
    if ($global:scenario -eq 'probe' -and $Workflow -eq 'news-connection-check.yml') {throw 'Synthetic failed probe'}
    if ($global:scenario -eq 'bootstrap' -and $Workflow -eq 'news-runtime.yml') {throw 'Synthetic failed bootstrap'}
    return @{databaseId=123;status='completed';conclusion='success'}
}
function Invoke-MigrationNative {
    param([string]$File, [string[]]$Arguments, [string]$InputText, [int]$TimeoutSeconds = 60)
    $global:nativeCalls += @{file=$File;arguments=@($Arguments);input=$InputText}
    if ($File -eq 'mock-python') {
        if ($env:NEWS_STATE_AGE_KEY -ne 'AGE-SECRET-KEY-1SYNTHETIC') {throw 'Missing child identity'}
        if ($env:TEMP -ne $env:TMP -or $env:TEMP -ne $env:TMPDIR -or [IO.Path]::GetDirectoryName($env:TEMP) -ne $testPrivate) {throw 'Unprotected child temporary directory'}
        $global:encryptTemp = $env:TEMP
        if ($global:scenario -eq 'encrypt') {throw 'Synthetic failed encryption'}
        $index = [Array]::IndexOf($Arguments, '--destination')
        $destination = $Arguments[$index + 1]
        $null = [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($destination))
        [IO.File]::WriteAllText($destination, 'synthetic ciphertext only')
        return ''
    }
    if ($File -ne 'mock-gh') {throw 'Unexpected process'}
    if ($Arguments[0] -eq 'auth') {return ''}
    if ($Arguments[0] -eq 'repo') {return '{"nameWithOwner":"junseo96/newsautobot","defaultBranchRef":{"name":"main"}}'}
    if ($Arguments[0] -eq 'variable') {
        if ($Arguments[2] -eq 'NEWS_SERVICE_ENABLED') {
            if ($Arguments[-1] -eq 'true') {
                $global:activationCalled = $true
                if ($global:scenario -like 'activation*') {throw 'Synthetic uncertain activation response'}
            }
            if ($Arguments[-1] -eq 'false' -and $global:activationCalled -and $global:scenario -eq 'activation-reset') {throw 'Synthetic uncertain disable response'}
        }
        return ''
    }
    if ($Arguments[0] -eq 'secret' -and $Arguments[1] -eq 'list') {return '[]'}
    if ($Arguments[0] -eq 'secret' -and $Arguments[1] -eq 'set') {return ''}
    if ($Arguments[0] -eq 'run' -and $Arguments[1] -eq 'list') {
        if ($global:scenario -eq 'active') {return '[{"status":"in_progress"}]'}
        return '[]'
    }
    if ($Arguments[0] -eq 'run' -and $Arguments[1] -eq 'view') {
        if ($global:scenario -eq 'prior-check') {return '{"status":"completed","conclusion":"failure","workflowName":"News connection check","headBranch":"main"}'}
        return '{"status":"completed","conclusion":"success","workflowName":"News connection check","headBranch":"main"}'
    }
    if ($Arguments[0] -eq 'api' -and $Arguments[1] -like '*/releases?*') {
        if ($global:scenario -eq 'release') {return '[[{"tag_name":"news-state-bootstrap"}]]'}
        return '[[]]'
    }
    if ($Arguments[0] -eq 'api' -and $Arguments[1] -like '*/artifacts?*') {
        if ($global:scenario -eq 'artifact') {return '{"artifacts":[{"name":"newsautobot-state","expired":true,"size_in_bytes":12}]}'}
        return '{"artifacts":[{"name":"newsautobot-state","expired":false,"size_in_bytes":12}]}'
    }
    if ($Arguments[0] -eq 'workflow' -or $Arguments[0] -eq 'release') {return ''}
    throw 'Unexpected GitHub command'
}
$receiptPath = Join-Path $testPrivate 'prepare.json'
if (__PHASE__ -eq 'Cutover' -or $global:scenario -eq 'probe') {
    $verifiedAt = [DateTime]::UtcNow.ToString('o')
    if ($global:scenario -eq 'stale-prepare') {$verifiedAt = [DateTime]::UtcNow.AddDays(-2).ToString('o')}
    $receipt = @{source_root=$testSource;repository='junseo96/newsautobot';verification_run_id=122;verified_at=$verifiedAt}
    [IO.File]::WriteAllText($receiptPath, ($receipt | ConvertTo-Json))
}
$failure = $null
try {
    Invoke-NewsGitHubMigration -Phase __PHASE__ -SourceRoot $testSource -IdentityFile (Join-Path $testPrivate 'identity.txt') -Stopped 6>$null
} catch {$failure=$_.Exception.Message}
$scratchExists = $false
if ($global:encryptTemp) {$scratchExists = Test-Path -LiteralPath $global:encryptTemp}
@{failure=$failure;calls=@($global:nativeCalls);receiptExists=(Test-Path -LiteralPath $receiptPath);stateKeyRestored=($null -eq [Environment]::GetEnvironmentVariable('NEWS_STATE_AGE_KEY','Process'));tempRestored=($initialTemp -ceq [Environment]::GetEnvironmentVariable('TEMP','Process'));tmpRestored=($initialTmp -ceq [Environment]::GetEnvironmentVariable('TMP','Process'));tmpdirRestored=($initialTmpdir -ceq [Environment]::GetEnvironmentVariable('TMPDIR','Process'));scratchExists=$scratchExists} | ConvertTo-Json -Compress -Depth 10
'''.replace("__PHASE__", ps_literal(phase)).replace("__SCENARIO__", ps_literal(failure))
        return self.run_powershell(body)

    @staticmethod
    def schedule_values(result):
        return [call["arguments"][-1] for call in result["calls"]
                if call["arguments"][:3] == ["variable", "set", "NEWS_SERVICE_ENABLED"]]

    def test_prepare_disables_schedule_and_verifies_stdin_secrets_without_bootstrap(self):
        result = self.run_phase("Prepare")
        self.assertIsNone(result["failure"])
        self.assertEqual(self.schedule_values(result), ["false"])
        self.assertTrue(result["receiptExists"])
        arguments = [call["arguments"] for call in result["calls"]]
        secret_calls = [call for call in result["calls"] if call["arguments"][:2] == ["secret", "set"]]
        self.assertEqual({call["arguments"][2]: call["input"] for call in secret_calls}, {
            "NEWS_CODEX_API_KEY": "synthetic-model-secret",
            "NEWS_GRID_TOKEN": "synthetic-grid-secret",
            "NEWS_STATE_AGE_KEY": "AGE-SECRET-KEY-1SYNTHETIC",
        })
        for call in secret_calls:
            self.assertNotIn(call["input"], json.dumps(arguments))
        self.assertFalse(any(call["file"] == "mock-python" for call in result["calls"]))
        self.assertFalse(any(args[:2] == ["release", "create"] for args in arguments))
        self.assertFalse(any("bootstrap=true" in args for args in arguments))
        disable = next(index for index, args in enumerate(arguments) if args[:3] == ["variable", "set", "NEWS_SERVICE_ENABLED"])
        first_secret = next(index for index, args in enumerate(arguments) if args[:2] == ["secret", "set"])
        probe = next(index for index, args in enumerate(arguments) if args[:3] == ["workflow", "run", "news-connection-check.yml"])
        self.assertLess(disable, first_secret)
        self.assertLess(first_secret, probe)

    def test_prepare_failure_or_existing_activity_cannot_issue_readiness_receipt(self):
        for scenario in ("active", "release", "probe"):
            with self.subTest(scenario=scenario):
                result = self.run_phase("Prepare", scenario)
                self.assertTrue(result["failure"])
                self.assertEqual(self.schedule_values(result), ["false"])
                self.assertFalse(result["receiptExists"])
                if scenario in {"active", "release"}:
                    self.assertFalse(any(call["arguments"][:2] == ["secret", "set"] for call in result["calls"]))

    def test_cutover_enables_schedule_only_after_encryption_bootstrap_and_artifact(self):
        result = self.run_phase("Cutover")
        self.assertIsNone(result["failure"])
        self.assertEqual(self.schedule_values(result), ["false", "true"])
        self.assertTrue(result["stateKeyRestored"])
        self.assertTrue(result["tempRestored"])
        self.assertTrue(result["tmpRestored"])
        self.assertTrue(result["tmpdirRestored"])
        self.assertFalse(result["scratchExists"])
        calls = result["calls"]
        encryption = next(index for index, call in enumerate(calls) if call["file"] == "mock-python")
        release = next(index for index, call in enumerate(calls) if call["arguments"][:2] == ["release", "create"])
        bootstrap = next(index for index, call in enumerate(calls) if "bootstrap=true" in call["arguments"])
        wait = next(index for index, call in enumerate(calls) if call["file"] == "wait")
        artifact = next(index for index, call in enumerate(calls) if any("/artifacts?" in arg for arg in call["arguments"]))
        self.assertLess(encryption, release)
        self.assertLess(release, bootstrap)
        self.assertLess(bootstrap, wait)
        self.assertLess(wait, artifact)
        self.assertLess(artifact, len(calls) - 1)
        self.assertIn("--stopped", calls[encryption]["arguments"])
        self.assertNotIn("--clobber", calls[release]["arguments"])
        self.assertEqual(calls[-1]["arguments"][-1], "true")

    def test_cutover_failures_keep_schedule_disabled_and_restore_child_identity(self):
        for scenario in ("stale-prepare", "prior-check", "encrypt", "bootstrap", "artifact"):
            with self.subTest(scenario=scenario):
                result = self.run_phase("Cutover", scenario)
                self.assertTrue(result["failure"])
                self.assertEqual(self.schedule_values(result), ["false"])
                self.assertTrue(result["stateKeyRestored"])
                self.assertTrue(result["tempRestored"])
                self.assertTrue(result["tmpRestored"])
                self.assertTrue(result["tmpdirRestored"])
                self.assertFalse(result["scratchExists"])
                if scenario in {"stale-prepare", "prior-check", "encrypt"}:
                    self.assertFalse(any(call["arguments"][:2] == ["release", "create"] for call in result["calls"]))
                    self.assertFalse(any("bootstrap=true" in call["arguments"] for call in result["calls"]))

    def test_uncertain_activation_attempts_disable_and_reports_unknown_state_if_that_fails(self):
        for scenario in ("activation", "activation-reset"):
            with self.subTest(scenario=scenario):
                result = self.run_phase("Cutover", scenario)
                self.assertTrue(result["failure"])
                self.assertEqual(self.schedule_values(result), ["false", "true", "false"])
                self.assertNotIn("Synthetic uncertain", result["failure"])
                if scenario == "activation-reset":
                    self.assertIn("Verify NEWS_SERVICE_ENABLED=false", result["failure"])
                    self.assertNotIn("scheduling remains disabled", result["failure"])


if __name__ == "__main__":
    unittest.main()
