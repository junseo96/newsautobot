"""Offline OpenDART watchlist regressions; synthetic key and API responses only."""
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from urllib.error import HTTPError, URLError
import zipfile

import collector
import v11_source_cache


def corp_archive():
    data = ('<result><list><corp_code>00123456</corp_code>'
            '<corp_name>엘에스일렉트릭</corp_name><stock_code>010120</stock_code>'
            '</list></result>').encode('utf-8')
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as archive:
        archive.writestr('CORPCODE.xml', data)
    return stream.getvalue()


def contract_archive():
    body = '<DOC><TABLE><TR><TD>계약금액</TD><TD>123억원</TD></TR></TABLE>'
    body += '<P>전력기기 공급계약 납품기간과 계약상대를 공시한 원문</P>' * 4
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as archive:
        archive.writestr('document.xml', (body + '</DOC>').encode('utf-8'))
    return stream.getvalue()


class DartCollectorTests(unittest.TestCase):
    def setUp(self):
        self.cfg = {'dart_watchlist': ['LS ELECTRIC'],
                    'dart_watchlist_stock_codes': ['010120']}

    def test_stock_code_resolves_korean_dart_issuer_name(self):
        self.assertEqual(collector.dart_companies(corp_archive(), self.cfg),
                         [('00123456', '엘에스일렉트릭')])

    def test_new_filing_uses_discovery_time_not_invented_midnight(self):
        filing = {'status': '000', 'list': [{
            'rcept_no': '20261001800099', 'rcept_dt': '20261001',
            'report_nm': '단일판매ㆍ공급계약체결'}]}
        urls = []

        def fake_urlopen(request, **_):
            urls.append(request.full_url)
            if 'corpCode.xml' in request.full_url: payload = corp_archive()
            elif 'document.xml' in request.full_url: payload = contract_archive()
            else: payload = json.dumps(filing).encode()
            return io.BytesIO(payload)

        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.dict(os.environ, {'NEWS_DART_KEY': 'x' * 40}), \
                mock.patch.object(collector.urllib.request, 'urlopen', side_effect=fake_urlopen):
            cache = Path(directory) / 'companies.json'
            first = collector.fetch_dart(self.cfg, cache)
            second = collector.fetch_dart(self.cfg, cache)
        self.assertTrue(first['ok'])
        self.assertTrue(second['ok'])
        self.assertEqual(sum('corpCode.xml' in url for url in urls), 1)
        self.assertEqual(len(first['items']), 1)
        article = first['items'][0]
        self.assertIn('엘에스일렉트릭', article['title'])
        self.assertIn('단일판매ㆍ공급계약체결', article['title'])
        self.assertIn('2026-10-01', article['summary'])
        self.assertEqual(collector.published_value(article), '2026-10-01')
        self.assertEqual(article['publication_precision'], 'date')
        self.assertTrue(article['must_review'])
        scoring = json.loads(Path(__file__).with_name('sources.json').read_text(encoding='utf-8'))
        self.assertGreaterEqual(collector.score_item(article, scoring)[0], 70)

    def test_contract_original_is_reused_by_review_cache(self):
        url = 'https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20261001800099'
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(collector.urllib.request, 'urlopen', return_value=io.BytesIO(contract_archive())):
            root = Path(directory)
            cache = root / 'work/v11/dart-corp-codes.json'
            self.assertTrue(collector.cache_dart_document(
                cache, url, '엘에스일렉트릭 | 단일판매ㆍ공급계약체결',
                '2026-10-01', 'x' * 40, '20261001800099', {}, None))
            with mock.patch.object(v11_source_cache, '_fetch', side_effect=AssertionError('cache miss')):
                original = v11_source_cache.get(root, url)
        self.assertTrue(original['usable'])
        self.assertTrue(original['from_cache'])
        self.assertIn('계약금액', original['text'])
        self.assertIn('123억원', original['text'])

    def test_extended_industry_watch_queues_material_filing_only(self):
        cfg=dict(self.cfg, dart_extended_watchlist=['엘에스일렉트릭'])
        filings={'status':'000','list':[
            {'rcept_no':'20261001800101','rcept_dt':'20261001','report_nm':'신규시설투자등'},
            {'rcept_no':'20261001800102','rcept_dt':'20261001','report_nm':'주주총회소집공고'}]}
        def fake_urlopen(request, **_):
            if 'corpCode.xml' in request.full_url: payload=corp_archive()
            elif 'document.xml' in request.full_url: payload=contract_archive()
            else: payload=json.dumps(filings).encode()
            return io.BytesIO(payload)
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.dict(os.environ, {'NEWS_DART_KEY':'x'*40}), \
                mock.patch.object(collector.urllib.request,'urlopen',side_effect=fake_urlopen):
            result=collector.fetch_dart(cfg,Path(directory)/'extended.json',extended=True)
        self.assertTrue(result['ok'])
        self.assertEqual(result['source']['name'],'OpenDART Extended')
        self.assertEqual(len(result['items']),1)
        self.assertTrue(result['items'][0]['must_review'])

    def test_transport_errors_never_persist_credential_urls(self):
        key='synthetic-dart-secret'
        url='https://opendart.fss.or.kr/api/corpCode.xml?crtfc_key='+key
        for error, expected in ((URLError(url), 'URLError'),
                                (HTTPError(url, 403, key, {}, io.BytesIO(key.encode())), 'HTTPError: HTTP 403')):
            with self.subTest(error=type(error).__name__), \
                    mock.patch.dict(os.environ, {'NEWS_DART_KEY':key}), \
                    mock.patch.object(collector.urllib.request, 'urlopen', side_effect=error):
                result=collector.fetch_dart(self.cfg)
            self.assertFalse(result['ok'])
            self.assertEqual(result['error'],expected)
            self.assertNotIn(key,json.dumps(result))
            self.assertNotIn('crtfc_key',json.dumps(result))

    def test_upstream_error_message_cannot_echo_credential(self):
        key='synthetic-dart-secret'
        def fake_urlopen(request, **_):
            if 'corpCode.xml' in request.full_url:
                return io.BytesIO(corp_archive())
            return io.BytesIO(json.dumps({'status':'010','message':key}).encode())
        with mock.patch.dict(os.environ, {'NEWS_DART_KEY':key}), \
                mock.patch.object(collector.urllib.request, 'urlopen', side_effect=fake_urlopen):
            result=collector.fetch_dart(self.cfg)
        self.assertFalse(result['ok'])
        self.assertEqual(result['error'],'RuntimeError')
        self.assertNotIn(key,json.dumps(result))


if __name__ == '__main__':
    unittest.main()
