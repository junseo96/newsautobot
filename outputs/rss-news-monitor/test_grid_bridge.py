import io,json,os,sqlite3,tempfile,unittest,urllib.request,urllib.error
from email.message import Message
from unittest.mock import patch
from urllib.response import addinfourl
from pathlib import Path
from contextlib import closing
from grid_bridge import Bridge, _NoBridgeRedirect

class GridBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='newsflow-grid-test-');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.bridge=Bridge(self.root)
        self.job={'url':'https://example.com/original','fingerprint':'revision1'}
        self.event={'asset_name':'Test solar','asset_kind':'generation','region':'MISO','state':'IN','queue_id':'J1234','official_project_id':None,'utility':None,'gate':'permit','status':'approved','certainty':'confirmed','direction':'improved','previous_fact':'승인 신청 단계','new_fact':'주 규제기관의 건설허가 승인 결정 확인','effective_date':'2026-10-05','capacity':{'mw':100,'basis':'generation','qualifier':'DC 용량'},'remaining_requirements':['망보강·접속계약 별도 확인 필요'],'source_urls':[self.job['url']]}
        self.decision={'index':1,'action':'reviewed','verified':True,'review_basis':'original','confidence':.95,'source_urls':[self.job['url']],'source_published_at':'2026-10-05','dashboard_events':[self.event]}
    def rows(self):
        with self.bridge.connect() as c:return c.execute('SELECT * FROM observations').fetchall()
    def test_non_sent_fact_is_independently_pending(self):
        self.assertEqual(self.bridge.record(self.job,self.decision)['included'],1)
        r=self.rows()[0];self.assertEqual(r['dashboard_status'],'pending');self.assertEqual(r['telegram_status'],'not_sent')
        self.assertEqual(json.loads(r['payload'])['status'],'approved')
    def test_idempotent_and_preserves_new_stage(self):
        self.bridge.record(self.job,self.decision);self.bridge.record(self.job,self.decision)
        self.assertEqual(len(self.rows()),1)
        self.bridge.record(self.job,{**self.decision,'dashboard_events':[{**self.event,'gate':'construction','status':'under_construction','new_fact':'건설공사 착수 및 기기 설치 일정 확인'}]})
        self.assertEqual(len(self.rows()),2);self.assertEqual(len({r['asset_id'] for r in self.rows()}),1)
    def test_metadata_cannot_change_project_state(self):
        r=self.bridge.record(self.job,{**self.decision,'review_basis':'metadata'})
        self.assertTrue(r['invalid']);self.assertFalse(self.rows())
    def test_unreviewed_link_cannot_be_evidence(self):
        r=self.bridge.record(self.job,{**self.decision,'dashboard_events':[{**self.event,'source_urls':['https://example.com/unread']}]})
        self.assertTrue(r['invalid']);self.assertFalse(self.rows())
    def test_low_confidence_and_infinite_capacity_rejected(self):
        self.assertTrue(self.bridge.record(self.job,{**self.decision,'confidence':.5})['invalid'])
        event={**self.event,'capacity':{**self.event['capacity'],'mw':float('inf')}}
        self.assertTrue(self.bridge.record(self.job,{**self.decision,'dashboard_events':[event]})['invalid'])
    def test_ack_not_decision_marks_delivery(self):
        db=self.root/'work/rss-news-monitor.db'
        with closing(sqlite3.connect(db)) as c:
            c.execute('CREATE TABLE delivery_history(url TEXT,receipt_file TEXT,message_sha256 TEXT)');c.commit()
        self.bridge.record(self.job,{**self.decision,'action':'send'});self.bridge.refresh_deliveries()
        self.assertEqual(self.rows()[0]['telegram_status'],'not_sent')
        with closing(sqlite3.connect(db)) as c:
            c.execute('INSERT INTO delivery_history VALUES(?,?,?)',(self.job['url'],'verified-receipt.json','verified-body-sha'));c.commit()
        self.bridge.refresh_deliveries();r=self.rows()[0]
        self.assertEqual(r['telegram_status'],'delivered_ack');self.assertEqual(r['dashboard_status'],'pending')
    def test_missing_gate_not_completed(self):
        self.bridge.record(self.job,self.decision)
        p=json.loads(self.rows()[0]['payload']);self.assertEqual(p['gate'],'permit');self.assertIn('별도 확인',p['remaining_requirements'][0])
    def test_no_event_records_explicit_no_dashboard_decision(self):
        self.bridge.record(self.job,{**self.decision,'dashboard_events':[]})
        self.assertEqual(self.bridge.status()['review_audit'],{'not_applicable':1})

class GridBridgeCloudTests(unittest.TestCase):
    rows=GridBridgeTests.rows
    def setUp(self):
        GridBridgeTests.setUp(self)
        self.environment=patch.dict(os.environ,{},clear=True)
        self.environment.start();self.addCleanup(self.environment.stop)
        with closing(sqlite3.connect(self.root/'work/rss-news-monitor.db')) as c:
            c.execute('CREATE TABLE delivery_history(url TEXT,receipt_file TEXT,message_sha256 TEXT)');c.commit()
        self.bridge.record(self.job,self.decision)
        self.credentials={'NEWS_GRID_URL':'https://dashboard.example/base/', 'NEWS_GRID_TOKEN':'synthetic-platform-credential'}

    def test_environment_bypasses_unreadable_windows_config_and_keeps_base_path(self):
        config=self.root/'work/grid-bridge/connection.json'
        config.write_text('not valid JSON or DPAPI',encoding='utf-8')
        event_id=self.rows()[0]['id']
        with patch.dict(os.environ,self.credentials),patch('grid_bridge.urllib.request.build_opener') as build:
            build.return_value.open.return_value=io.BytesIO(json.dumps({'accepted_ids':[event_id]}).encode())
            result=self.bridge.sync()
        request=build.return_value.open.call_args.args[0]
        self.assertIsInstance(build.call_args.args[0],_NoBridgeRedirect)
        self.assertEqual(request.full_url,'https://dashboard.example/base/api/newsflow')
        self.assertEqual(request.get_header('Oai-sites-authorization'),'Bearer synthetic-platform-credential')
        self.assertEqual(request.method,'POST')
        self.assertEqual(json.loads(request.data)['events'][0]['id'],event_id)
        self.assertEqual(result['uploaded'],1)
        self.assertEqual(self.rows()[0]['dashboard_status'],'synced')
        self.assertEqual(self.rows()[0]['telegram_status'],'not_sent')
        self.assertEqual(config.read_text(encoding='utf-8'),'not valid JSON or DPAPI')

    def test_environment_never_writes_connection_file(self):
        with patch.dict(os.environ,self.credentials),patch('grid_bridge.urllib.request.build_opener') as build:
            build.return_value.open.return_value=io.BytesIO(b'{"accepted_ids":[]}')
            result=self.bridge.sync()
        self.assertEqual(result['status'],'partial')
        self.assertEqual(self.rows()[0]['dashboard_status'],'pending')
        self.assertFalse((self.root/'work/grid-bridge/connection.json').exists())

    def test_incomplete_environment_does_not_fall_back_or_send(self):
        (self.root/'work/grid-bridge/connection.json').write_text('not valid JSON',encoding='utf-8')
        for values in ({'NEWS_GRID_URL':self.credentials['NEWS_GRID_URL']},
                       {'NEWS_GRID_TOKEN':self.credentials['NEWS_GRID_TOKEN']},
                       {**self.credentials,'NEWS_GRID_TOKEN':' '},
                       {**self.credentials,'NEWS_GRID_URL':''}):
            with self.subTest(names=sorted(values)),patch.dict(os.environ,values),patch('grid_bridge.urllib.request.build_opener') as build:
                with self.assertRaisesRegex(ValueError,'must be configured together'):
                    self.bridge.sync()
                build.assert_not_called()

    def test_endpoint_validation_never_includes_bad_url_or_secret(self):
        urls=['http://dashboard.example','https://user:secret@dashboard.example',
              'https://dashboard.example?secret=value','https://dashboard.example#fragment',
              'https://dashboard.example:bad','https://dashboard.example\\@attacker.example',
              ' https://dashboard.example','https://dashboard.example\n/path','//dashboard.example']
        for url in urls:
            with self.subTest(url=url),patch.dict(os.environ,{**self.credentials,'NEWS_GRID_URL':url}),patch('grid_bridge.urllib.request.build_opener') as build:
                with self.assertRaisesRegex(ValueError,'Expected HTTPS dashboard base URL') as failure:
                    self.bridge.sync()
                self.assertNotIn(url,str(failure.exception));build.assert_not_called()

    def test_bad_ack_remains_pending_and_does_not_disclose_transport_error(self):
        for response in (io.BytesIO(b'{"accepted_ids":["not-this-event"]}'),
                         urllib.error.URLError('secret https://bad.example/private-token')):
            with patch.dict(os.environ,self.credentials),patch('grid_bridge.urllib.request.build_opener') as build:
                if isinstance(response,Exception):build.return_value.open.side_effect=response
                else:build.return_value.open.return_value=response
                with self.assertRaisesRegex(RuntimeError,'Dashboard sync failed:') as failure:
                    self.bridge.sync()
                self.assertNotIn('secret',str(failure.exception));self.assertNotIn('https://',str(failure.exception))
                row=self.rows()[0];self.assertEqual(row['dashboard_status'],'pending')
                self.assertNotIn('https://',row['last_error'])
        self.assertEqual(self.rows()[0]['attempts'],2)

    def test_redirect_cannot_forward_credential_to_another_url(self):
        seen=[]
        class FakeHTTPS(urllib.request.HTTPSHandler):
            def https_open(self,request):
                seen.append(request.full_url)
                headers=Message();headers['Location']='https://attacker.example/private-token'
                response=addinfourl(io.BytesIO(b''),headers,request.full_url,302)
                response.msg='Found'
                return response
        opener=urllib.request.build_opener(FakeHTTPS(),_NoBridgeRedirect())
        with patch.dict(os.environ,self.credentials),patch('grid_bridge.urllib.request.build_opener',return_value=opener):
            with self.assertRaisesRegex(RuntimeError,'Dashboard sync failed: HTTPError: HTTP 302'):
                self.bridge.sync()
        self.assertEqual(seen,['https://dashboard.example/base/api/newsflow'])
        self.assertEqual(self.rows()[0]['dashboard_status'],'pending')

if __name__=='__main__':unittest.main()
