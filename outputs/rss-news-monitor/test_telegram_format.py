"""Offline regression tests for Telegram news formatting.

Only Telegram-Format.ps1 is dot-sourced. These tests never invoke a sender,
read credentials, open the production database, or make network requests.
Both Windows PowerShell and PowerShell 7 are tested when available.
"""
import base64
import json
from pathlib import Path
import shutil
import subprocess
import unittest


FORMAT_SCRIPT = Path(__file__).resolve().parent.parent / 'telegram-forwarder/Telegram-Format.ps1'


def news_message(summary='2GW 송전망 증설 승인에 따른 대형부하 접속 여력 확대', newline='\n'):
    return newline.join([
        '**[송전망 투자 승인]**', '',
        '**- ' + summary + '**', '',
        '1. 규제기관의 2GW 송전망 증설 최종 승인', '',
        '2. 2028년 준공 이후 데이터센터 계통접속 여력 확대', '',
        '링크: https://example.com/grid-approval',
    ])


class TelegramFormatTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.shells = []
        for command in ('powershell.exe', 'pwsh.exe', 'pwsh'):
            shell = shutil.which(command)
            if shell and shell.casefold() not in {item.casefold() for item in cls.shells}:
                cls.shells.append(shell)
        if not cls.shells:
            raise unittest.SkipTest('PowerShell is required for the formatting tests')

    def validate_cases(self, cases):
        """Batch fixtures over an encoded command; no temporary files required."""
        payload = base64.b64encode(json.dumps(cases, ensure_ascii=False).encode('utf-8')).decode('ascii')
        escaped_path = str(FORMAT_SCRIPT).replace("'", "''")
        script = r'''
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object Text.UTF8Encoding($false)
. '__FORMAT_PATH__'
$cases = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('__PAYLOAD__')) | ConvertFrom-Json
$results = @(foreach ($case in $cases) {
    try {
        Assert-NewsFormat -Value $case.message
        [pscustomobject]@{ name = $case.name; valid = $true; error = $null }
    } catch {
        [pscustomobject]@{ name = $case.name; valid = $false; error = $_.Exception.Message }
    }
})
ConvertTo-Json -InputObject $results -Compress -Depth 4
'''.replace('__FORMAT_PATH__', escaped_path).replace('__PAYLOAD__', payload)
        encoded = base64.b64encode(script.encode('utf-16-le')).decode('ascii')
        for shell in self.shells:
            with self.subTest(shell=shell):
                result = subprocess.run(
                    [shell, '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                     '-EncodedCommand', encoded], capture_output=True, text=True,
                    encoding='utf-8', timeout=30,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                checks = json.loads(result.stdout.lstrip('\ufeff'))
                self.assertEqual(len(checks), len(cases))
                for case, check in zip(cases, checks):
                    with self.subTest(case=case['name']):
                        self.assertEqual(check['name'], case['name'])
                        self.assertEqual(check['valid'], case['valid'], check.get('error'))

    def test_source_url_renders_as_clickable_label(self):
        url = 'https://example.com/a(b)?x=1&y=2'
        cases = ['링크: ' + url, '[원문보기](' + url + ')']
        payload = base64.b64encode(json.dumps(cases, ensure_ascii=False).encode('utf-8')).decode('ascii')
        script = r'''
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object Text.UTF8Encoding($false)
. '__FORMAT_PATH__'
$cases = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('__PAYLOAD__')) | ConvertFrom-Json
$result = @($cases | ForEach-Object { ConvertTo-TelegramHtml $_ })
ConvertTo-Json -InputObject $result -Compress
'''.replace('__FORMAT_PATH__', str(FORMAT_SCRIPT).replace("'", "''")).replace('__PAYLOAD__', payload)
        encoded = base64.b64encode(script.encode('utf-16-le')).decode('ascii')
        for shell in self.shells:
            with self.subTest(shell=shell):
                result = subprocess.run(
                    [shell, '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                     '-EncodedCommand', encoded], capture_output=True, text=True,
                    encoding='utf-8', timeout=30,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                rendered = json.loads(result.stdout.lstrip('\ufeff'))
                self.assertEqual(rendered, ['<a href="https://example.com/a(b)?x=1&amp;y=2">원문보기</a>'] * 2)

    def test_real_korean_summary_is_accepted_with_lf_and_crlf(self):
        self.validate_cases([
            {'name': name + ' ' + summary,
             'message': news_message(summary=summary, newline=newline), 'valid': True}
            for name, newline in (('LF', '\n'), ('CRLF', '\r\n'))
            for summary in ('2GW 송전망 증설 승인에 따른 대형부하 접속 여력 확대',
                            '요약: 56MW ESS 신규 발주에 따른 계통 안정성 보강', '2GW 증설 승인')
        ])

    def test_empty_or_whitespace_summary_is_rejected_despite_complete_details(self):
        self.validate_cases([
            {'name': name, 'message': news_message(summary=summary), 'valid': False}
            for name, summary in (
                ('empty', ''), ('spaces', '    '), ('tabs', '\t\t'),
                ('non-breaking space', '\u00a0\u00a0'),
                ('ideographic space', '\u3000'),
                ('zero-width space', '\u200b'),
                ('mixed invisible characters', ' \t\u200b\ufeff '),
            )
        ])

    def test_summary_label_alone_is_rejected_with_lf_and_crlf(self):
        self.validate_cases([
            {'name': repr(summary) + ' ' + name,
             'message': news_message(summary=summary, newline=newline), 'valid': False}
            for name, newline in (('LF', '\n'), ('CRLF', '\r\n'))
            for summary in ('요약', ' 요약 ', '요약:', '요약 : ', '핵심 요약', '한 줄 요약',
                            'Summary', 'summary:', 'tl;dr')
        ])

    def test_placeholder_summary_is_rejected_despite_substantive_numbered_details(self):
        self.validate_cases([
            {'name': summary, 'message': news_message(summary=summary), 'valid': False}
            for summary in ('TODO', 'todo', 'TBD', '작성 예정', '작성 필요', '요약 내용 작성',
                            '...', '…', '---', '!!!')
        ])

    def test_every_summary_line_is_validated(self):
        message = news_message()
        self.validate_cases([
            {'name': 'valid first summary followed by empty label',
             'message': message.replace('\n\n1. ', '\n\n**- 요약**\n\n1. '), 'valid': False},
            {'name': 'empty label followed by valid summary',
             'message': message.replace('승인]**\n\n', '승인]**\n\n**- 요약**\n\n'), 'valid': False},
            {'name': 'valid summary followed by whitespace-only summary',
             'message': message.replace('\n\n1. ', '\n\n**-    **\n\n1. '), 'valid': False},
        ])

    def test_existing_korean_noun_ending_requirement_is_preserved(self):
        message = news_message()
        self.validate_cases([
            {'name': 'polite summary', 'message': news_message(summary='2GW 송전망 증설을 승인했습니다'),
             'valid': False},
            {'name': 'polite numbered detail',
             'message': message.replace('최종 승인', '최종 승인입니다'), 'valid': False},
        ])

    def test_existing_headline_numbering_spacing_and_link_requirements_are_preserved(self):
        message = news_message()
        self.validate_cases([
            {'name': 'headline must be bold',
             'message': message.replace('**[송전망 투자 승인]**', '[송전망 투자 승인]'), 'valid': False},
            {'name': 'headline must be bracketed',
             'message': message.replace('**[송전망 투자 승인]**', '**송전망 투자 승인**'), 'valid': False},
            {'name': 'headline needs blank line',
             'message': message.replace('승인]**\n\n', '승인]**\n'), 'valid': False},
            {'name': 'summary must be bold',
             'message': message.replace('**- 2GW 송전망 증설 승인에 따른 대형부하 접속 여력 확대**',
                                        '- 2GW 송전망 증설 승인에 따른 대형부하 접속 여력 확대'), 'valid': False},
            {'name': 'summary must exist',
             'message': message.replace('**- 2GW 송전망 증설 승인에 따른 대형부하 접속 여력 확대**\n\n', ''),
             'valid': False},
            {'name': 'numbered details must start at one',
             'message': message.replace('\n1. ', '\n3. '), 'valid': False},
            {'name': 'numbered details need blank line',
             'message': message.replace('최종 승인\n\n2.', '최종 승인\n2.'), 'valid': False},
            {'name': 'article source link must exist',
             'message': message.replace('링크: https://example.com/grid-approval', ''), 'valid': False},
            {'name': 'article source link must use http scheme',
             'message': message.replace('https://example.com/grid-approval', 'file:///example.com/grid-approval'),
             'valid': False},
        ])


if __name__ == '__main__':
    unittest.main()
