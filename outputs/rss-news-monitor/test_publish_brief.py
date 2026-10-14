"""Publish helper integration tests: mock only Telegram, use the real ACK/SQLite.

All artifacts and the sender stub live in a temporary project. No credentials,
production DB, network endpoint, or public Telegram channel are accessed.
"""
import contextlib
import datetime as dt
import hashlib
import html
import json
import os
from pathlib import Path, PureWindowsPath
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import collector


SENDER_STUB = r'''
param([string]$MessageFile,[string]$ArticleUrlsFile,[string]$NoveltyReviewFile,[string]$ReceiptFile,[switch]$NewsFormat,[switch]$MarkdownBold,[switch]$ValidateOnly)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'Telegram-Format.ps1')
$root=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$mode=[IO.File]::ReadAllText((Join-Path $root 'sender-mode.txt')).Trim()
$event=if($ValidateOnly){'validate'}else{'send'}
[IO.File]::AppendAllText((Join-Path $root 'sender-calls.txt'), $event+"`n")
$message=[IO.File]::ReadAllText($MessageFile,[Text.Encoding]::UTF8).Trim()
$hash=Get-MessageHash $message
$urls=@([IO.File]::ReadAllLines($ArticleUrlsFile) | Where-Object { $_.Trim() } | ForEach-Object { $_.Trim() } | Sort-Object -Unique)
$parts=@(Split-NewsMessage -Value $message -Bold $true)
if($ValidateOnly){
 if($mode -eq 'tamper'){[IO.File]::AppendAllText($MessageFile,"`nChanged after validation")}
 [pscustomobject]@{valid=$true;novelty_checked=($mode -ne 'invalid_novelty');message_sha256=$hash;article_count=$urls.Count;parts=$parts.Count}|ConvertTo-Json -Compress
 return
}
if($mode -eq 'failure'){throw 'Simulated rejected send'}
$ids=@();$completed=@()
for($i=0;$i -lt $parts.Count;$i++){
 $chunk=$parts[$i]
 if($parts.Count -gt 1){$chunk="[{0}/{1}]`r`n{2}" -f ($i+1),$parts.Count,$chunk}
 $ids+=100+$i
 $completed+=[pscustomobject]@{index=$i;message_id=(100+$i);sha256=(Get-MessageHash (ConvertTo-TelegramHtml $chunk))}
}
$receipt=[pscustomobject]@{schema_version=1;status='complete';message_file=$MessageFile;message_text=$message;message_sha256=$hash;markdown_bold=$true;article_urls=$urls;sent_at=[DateTimeOffset]::UtcNow.ToString('o');telegram_message_ids=$ids;completed_parts=$completed;total_parts=$parts.Count;in_flight_part=$null}
if($mode -eq 'uncertain'){$receipt.status='uncertain';$receipt.in_flight_part=0}
if($mode -eq 'bad_chunks'){$receipt.completed_parts[0].sha256='invalid'}
Save-TelegramReceipt $ReceiptFile $receipt
if($mode -eq 'uncertain'){throw 'Simulated uncertain transport'}
'''


class PublishBriefTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.shell = shutil.which('pwsh.exe') or shutil.which('pwsh') or shutil.which('powershell.exe')
        if not cls.shell:
            raise unittest.SkipTest('PowerShell is required')

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='newsflow-publish-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.monitor = self.root / 'outputs/rss-news-monitor'
        self.sender = self.root / 'outputs/telegram-forwarder'
        self.run = self.root / 'work/runs/test-run'
        for directory in (self.monitor, self.sender, self.run):
            directory.mkdir(parents=True)
        source = Path(__file__).parent
        for name in ('Publish-Brief.ps1', 'Ack-Collector.ps1', 'Resolve-Python.ps1',
                     'collector.py', 'source_normalization.py', 'review_state.py', 'newsletter_queue.py',
                     'newsletter_completion.py', 'runtime_scope.py', 'project_paths.py'):
            shutil.copy2(source / name, self.monitor / name)
        shutil.copy2(source.parent / 'telegram-forwarder/Telegram-Format.ps1', self.sender / 'Telegram-Format.ps1')
        (self.sender / 'Send-Telegram.ps1').write_text(SENDER_STUB, encoding='utf-8')
        (self.root / 'sender-mode.txt').write_text('success', encoding='utf-8')
        self.write_json(self.monitor / 'sources.json', {'selection_policy_version': 10})
        self.url = 'https://example.com/grid-approval'
        self.message = '**[송전망 투자 승인]**\n\n**- 2GW 계통 증설 신규 승인**\n\n1. 2028년 준공 계획 확정\n\n링크: ' + self.url
        self.message_path = self.run / 'message.txt'
        self.message_path.write_bytes(self.message.encode('utf-8'))
        self.urls_path = self.run / 'urls.txt'
        self.urls_path.write_text(self.url + '\n', encoding='utf-8')
        self.novelty_path = self.run / 'novelty.json'
        self.write_json(self.novelty_path, {'message_sha256':hashlib.sha256(self.message.encode()).hexdigest(), 'new_facts':['규제기관 최종 승인으로 2GW 송전 증설과 2028년 준공 계획 확정'], 'comparisons':[]})
        self.batch_path = self.run / 'snapshot.json'
        self.generated = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=2)).isoformat()
        self.batch = {'run_id':'test-run', 'policy_version':10, 'generated_at_kst':self.generated, 'run_files':{'snapshot':str(self.batch_path)}, 'candidates':[{'url':self.url, 'title':'Grid approval', 'summary':'2GW capacity'}]}
        self.write_json(self.batch_path, self.batch)
        self.db = self.root / 'work/rss-news-monitor.db'
        with self.connection() as con:
            collector.ensure_db(con)
            con.execute("INSERT INTO articles(url,url_hash,normalized_title,title,summary,source,source_url,first_seen_at,last_seen_at,score,score_reasons) VALUES (?,?,?,?,?,?,?,?,?,?,?)", (self.url,'hash','grid','Grid approval','2GW capacity','Test',self.url,self.generated,self.generated,10,'[]'))
            con.execute("INSERT INTO source_runs(run_id,source,source_url,ok,item_count,started_at,finished_at) VALUES (?,?,?,?,?,?,?)", ('test-run','Test',self.url,1,1,self.generated,self.generated))

    def write_json(self, path, value):
        path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')

    @contextlib.contextmanager
    def connection(self):
        con = sqlite3.connect(self.db)
        try:
            yield con
            con.commit()
        finally:
            con.close()

    def invoke(self, *extra):
        env = dict(os.environ, NEWS_PYTHON=sys.executable)
        for name, directory in (('XDG_CACHE_HOME', 'cache'), ('XDG_CONFIG_HOME', 'config'), ('XDG_DATA_HOME', 'data')):
            env[name] = str(self.root / directory)
        return subprocess.run([self.shell,'-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',str(self.monitor/'Publish-Brief.ps1'),'-BatchFile',str(self.batch_path),'-MessageFile',str(self.message_path),'-ArticleUrlsFile',str(self.urls_path),'-NoveltyReviewFile',str(self.novelty_path),'-Reason','Confirmed new 2GW final approval', *extra], capture_output=True, text=True, encoding='utf-8', env=env, timeout=45)

    def calls(self):
        path = self.root / 'sender-calls.txt'
        return path.read_text().splitlines() if path.exists() else []

    def status(self):
        with self.connection() as con:
            return con.execute('SELECT status FROM articles WHERE url=?',(self.url,)).fetchone()[0]

    def set_mode(self, value):
        (self.root/'sender-mode.txt').write_text(value)

    def assert_failed(self, result):
        self.assertNotEqual(result.returncode,0, result.stdout)
        self.assertEqual(self.status(),'pending')
        with self.connection() as con:
            self.assertEqual(con.execute('SELECT count(*) FROM delivery_history').fetchone()[0],0)

    def test_validate_only_does_not_send_or_ack_or_create_outputs(self):
        result = self.invoke('-ValidateOnly')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout)['status'],'validated')
        self.assertEqual(self.calls(),['validate'])
        self.assertEqual(self.status(),'pending')
        self.assertEqual(list(self.run.glob('receipt-*.json')),[])
        self.assertEqual(list(self.run.glob('decisions-*.json')),[])

    def test_success_real_ack_and_idempotent_receipt_reuse(self):
        first = self.invoke()
        self.assertEqual(first.returncode,0,first.stderr)
        report = json.loads(first.stdout)
        self.assertEqual(report['telegram_message_ids'],[100])
        self.assertEqual(report['ack']['delivered'],1)
        self.assertEqual(self.status(),'delivered')
        second = self.invoke()
        self.assertEqual(second.returncode,0,second.stderr)
        self.assertTrue(json.loads(second.stdout)['reused_receipt'])
        self.assertEqual(json.loads(second.stdout)['ack']['already_recorded'],1)
        self.assertEqual(self.calls(),['validate','send'])
        with self.connection() as con:
            self.assertEqual(con.execute('SELECT count(*) FROM delivery_history').fetchone()[0],1)

    def test_unknown_candidate_never_calls_sender(self):
        self.urls_path.write_text('https://example.com/unknown\n')
        self.assert_failed(self.invoke())
        self.assertEqual(self.calls(),[])

    def test_summary_label_never_calls_sender_or_acks(self):
        self.message = self.message.replace('2GW 계통 증설 신규 승인', '요약')
        self.message_path.write_bytes(self.message.encode('utf-8'))
        novelty = json.loads(self.novelty_path.read_text(encoding='utf-8'))
        novelty['message_sha256'] = hashlib.sha256(self.message.encode()).hexdigest()
        self.write_json(self.novelty_path, novelty)
        result = self.invoke()
        self.assert_failed(result)
        self.assertIn('substantive one-line summary', result.stderr)
        self.assertEqual(self.calls(), [])
        self.assertEqual(list(self.run.glob('receipt-*.json')), [])
        self.assertEqual(list(self.run.glob('decisions-*.json')), [])

    def test_complete_legacy_summary_receipt_recovers_without_resend(self):
        # A historically sent label-only message remains immutable. Current
        # format validation must not demand editing or resending its evidence.
        self.message = self.message.replace('2GW 계통 증설 신규 승인', '요약')
        self.message_path.write_bytes(self.message.encode('utf-8'))
        digest = hashlib.sha256(self.message.encode()).hexdigest()
        novelty = json.loads(self.novelty_path.read_text(encoding='utf-8'))
        novelty['message_sha256'] = digest
        self.write_json(self.novelty_path, novelty)
        import re
        rendered = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', html.escape(self.message, quote=False))
        receipt_path = self.run / 'receipt-legacy.json'
        self.write_json(receipt_path, {
            'schema_version': 1, 'status': 'complete',
            'message_file': str(self.message_path), 'message_text': self.message,
            'message_sha256': digest, 'markdown_bold': True,
            'article_urls': [self.url], 'sent_at': dt.datetime.now(dt.timezone.utc).isoformat(),
            'telegram_message_ids': [99], 'total_parts': 1, 'in_flight_part': None,
            'completed_parts': [{'index': 0, 'message_id': 99,
                                 'sha256': hashlib.sha256(rendered.encode()).hexdigest()}],
        })
        before = receipt_path.read_bytes()
        result = self.invoke('-ReceiptFile', str(receipt_path))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)['reused_receipt'])
        self.assertEqual(json.loads(result.stdout)['ack']['recovered_history'], 1)
        self.assertEqual(self.calls(), [])
        self.assertEqual(self.status(), 'delivered')
        self.assertEqual(receipt_path.read_bytes(), before)

    def test_tampered_message_never_calls_sender(self):
        self.message_path.write_text(self.message.replace('2GW','3GW'),encoding='utf-8')
        self.assert_failed(self.invoke())
        self.assertEqual(self.calls(),[])

    def test_cross_run_receipt_path_never_calls_sender(self):
        self.assert_failed(self.invoke('-ReceiptFile',str(self.root/'work/receipt-wrong.json')))
        self.assertEqual(self.calls(),[])

    def test_stale_snapshot_never_calls_sender(self):
        with self.connection() as con:
            con.execute("UPDATE source_runs SET run_id='newer-run'")
        self.assert_failed(self.invoke())
        self.assertEqual(self.calls(),[])

    def test_future_snapshot_never_calls_sender(self):
        self.batch['generated_at_kst'] = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)).isoformat()
        self.write_json(self.batch_path,self.batch)
        self.assert_failed(self.invoke())
        self.assertEqual(self.calls(),[])

    def test_send_failure_never_acks(self):
        self.set_mode('failure')
        self.assert_failed(self.invoke())
        self.assertEqual(self.calls(),['validate','send'])
        self.assertEqual(list(self.run.glob('decisions-*.json')),[])

    def test_uncertain_receipt_never_retries_or_acks(self):
        self.set_mode('uncertain')
        self.assert_failed(self.invoke())
        self.set_mode('success')
        self.assert_failed(self.invoke())
        self.assertEqual(self.calls(),['validate','send'])

    def test_bad_chunk_receipt_never_acks(self):
        self.set_mode('bad_chunks')
        self.assert_failed(self.invoke())
        self.assertEqual(list(self.run.glob('decisions-*.json')),[])

    def test_missing_novelty_validation_never_sends(self):
        self.set_mode('invalid_novelty')
        self.assert_failed(self.invoke())
        self.assertEqual(self.calls(),['validate'])

    def test_input_changed_during_validation_never_sends(self):
        self.set_mode('tamper')
        self.assert_failed(self.invoke())
        self.assertEqual(self.calls(),['validate'])

    def test_complete_receipt_recovers_after_newer_run_without_resend(self):
        first = self.invoke()
        self.assertEqual(first.returncode,0,first.stderr)
        with self.connection() as con:
            con.execute('DELETE FROM decision_history')
            con.execute('DELETE FROM delivery_history')
            con.execute("UPDATE articles SET status='pending'")
            con.execute("UPDATE source_runs SET run_id='newer-run'")
        recovered = self.invoke()
        self.assertEqual(recovered.returncode,0,recovered.stderr)
        self.assertEqual(json.loads(recovered.stdout)['ack']['recovered_history'],1)
        self.assertEqual(self.status(),'delivered')
        self.assertEqual(self.calls(),['validate','send'])

    def migrated_artifacts(self):
        import re
        legacy_root = r'D:\Operations\newsautobot'
        def legacy(path):
            return str(PureWindowsPath(legacy_root).joinpath(*path.relative_to(self.root).parts))
        self.batch['run_files']['snapshot'] = legacy(self.batch_path)
        self.write_json(self.batch_path, self.batch)
        digest = hashlib.sha256(self.message.encode()).hexdigest()
        rendered = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', html.escape(self.message, quote=False))
        receipt_path = self.run/'receipt-migrated.json'
        self.write_json(receipt_path, {
            'schema_version':1, 'status':'complete', 'message_file':legacy(self.message_path),
            'message_text':self.message, 'message_sha256':digest, 'markdown_bold':True,
            'article_urls':[self.url], 'sent_at':dt.datetime.now(dt.timezone.utc).isoformat(),
            'telegram_message_ids':[99], 'total_parts':1, 'in_flight_part':None,
            'completed_parts':[{'index':0, 'message_id':99, 'sha256':hashlib.sha256(rendered.encode()).hexdigest()}],
        })
        decision_path = self.run/'decisions-migrated.json'
        self.write_json(decision_path, {'run_id':'test-run', 'decisions':[
            {'url':self.url, 'status':'delivered', 'reason':'Confirmed new 2GW final approval',
             'receipt_file':legacy(receipt_path)}]})
        return legacy_root, receipt_path, decision_path

    def test_migrated_windows_complete_receipt_and_decisions_recover_without_resend(self):
        legacy_root, receipt_path, decision_path = self.migrated_artifacts()
        immutable = {path:path.read_bytes() for path in (self.batch_path, receipt_path, decision_path, self.message_path)}
        with self.connection() as con:
            con.execute("UPDATE source_runs SET run_id='newer-run'")
        with patch.dict(os.environ, {'NEWS_LEGACY_ROOT':legacy_root}):
            first = self.invoke('-ReceiptFile', str(receipt_path), '-DecisionFile', str(decision_path))
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(json.loads(first.stdout)['ack']['recovered_history'], 1)
            second = self.invoke('-ReceiptFile', str(receipt_path), '-DecisionFile', str(decision_path))
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(json.loads(second.stdout)['ack']['already_recorded'], 1)
        self.assertEqual(self.status(), 'delivered')
        self.assertEqual(self.calls(), [])
        for path, content in immutable.items():
            self.assertEqual(path.read_bytes(), content)
        with self.connection() as con:
            self.assertEqual(con.execute('SELECT count(*) FROM delivery_history').fetchone()[0], 1)

    def test_migrated_decision_comparison_keeps_all_non_path_fields_exact(self):
        legacy_root, receipt_path, decision_path = self.migrated_artifacts()
        original = json.loads(decision_path.read_text())
        variants = [
            {**original, 'unexpected':True},
            {**original, 'decisions':[{**original['decisions'][0], 'reason':'Changed decision reason'}]},
            {**original, 'decisions':[{**original['decisions'][0], 'receipt_file':str(self.run/'receipt-different.json')}]},
        ]
        for value in variants:
            with self.subTest(value=value):
                self.write_json(decision_path, value)
                before = decision_path.read_bytes()
                with patch.dict(os.environ, {'NEWS_LEGACY_ROOT':legacy_root}):
                    result = self.invoke('-ReceiptFile', str(receipt_path), '-DecisionFile', str(decision_path))
                self.assert_failed(result)
                self.assertIn('DecisionFile already contains different decisions', result.stderr)
                self.assertEqual(decision_path.read_bytes(), before)
                self.assertEqual(self.calls(), [])


if __name__ == '__main__':
    unittest.main()
