import json,sqlite3,tempfile,unittest
from pathlib import Path
from contextlib import closing
from grid_bridge import Bridge

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

if __name__=='__main__':unittest.main()
