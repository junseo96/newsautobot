import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
import delivery_guard as g

class GuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root/'work/runs/old').mkdir(parents=True)
        (self.root/'work/telegram-outbox').mkdir()
        with closing(sqlite3.connect(self.root/'work/rss-news-monitor.db')) as c:
            c.execute('CREATE TABLE delivery_history(url, message_text, message_sha256, receipt_file)')
            c.commit()
        self.old = 'MISO 90일 무역류 접속심사 제안과 Google 적용 범위 확대 요청. 링크: https://example.com/original'

    def record(self, text=None):
        text = text or self.old
        with closing(sqlite3.connect(self.root/'work/rss-news-monitor.db')) as c:
            c.execute('INSERT INTO delivery_history VALUES (?,?,?,?)',('https://google.example/rss',text,g.digest(text),'old-receipt'))
            c.commit()

    def review(self, report, kind='different_event'):
        return {'message_sha256':report['message_sha256'], 'new_facts':['새로 승인된 별도 발전 프로젝트의 확정 물량 600MW'],
                'comparisons':[{'id':m['id'],'classification':kind,'reason':'기존 사업과 다른 지역의 별도 프로젝트임을 원문에서 확인',
                                'material_delta':'기존에는 신청 단계였으나 새 규제기관 명령에서 최종 승인 확인'} for m in report['matches']]}

    def test_same_content_blocked_even_with_review(self):
        self.record()
        r=g.inspect(self.root,self.old.replace('MISO','**MISO**'))
        with self.assertRaises(ValueError): g.validate(r,self.review(r))

    def test_original_link_matches_google_candidate(self):
        self.record()
        r=g.inspect(self.root,'전혀 다른 제목과 문장. 링크: https://example.com/original?utm_source=mail')
        self.assertEqual(len(r['matches']),1)
        with self.assertRaises(ValueError): g.validate(r,{'message_sha256':r['message_sha256'],'new_facts':['전력 프로젝트 승인으로 600MW 공급능력 확정']})

    def test_syndicated_story_slug_matches_across_domains(self):
        slug='energy-department-will-spend-2-billion-to-squeeze-more-electricity-from-aging-power-grid'
        old='미국 송전망 사업에 관한 첫 번째 보도. 링크: https://publisher-one.example/news/'+slug
        new='연방 전력 부처 예산에 관한 완전히 다른 표현의 재배포 기사. 링크: https://publisher-two.example/article/'+slug
        self.record(old)
        self.assertLess(g.similarity(old,new),.28)
        r=g.inspect(self.root,new)
        self.assertEqual(len(r['matches']),1)
        self.assertEqual(r['matches'][0]['shared_story_keys'],[slug])
        with self.assertRaises(ValueError):
            g.validate(r,{'message_sha256':r['message_sha256'],'new_facts':['미국 송전망 사업에 관한 신규 산업 사실 확인'],'comparisons':[]})

    def test_near_threshold_shared_quantities_requires_review(self):
        old='DOE 19억 달러 지원, 26개 주의 31건 전력망 사업과 23GW 용량 확대. 송전 설비 재개발 계획을 발표.'
        new='연방정부는 19억 달러를 26개 주 31건에 배정하고 23GW 계통용량을 확보. 다른 매체의 지역 보도.'
        self.record(old)
        with patch.object(g,'similarity',return_value=.2776):
            r=g.inspect(self.root,new)
        self.assertEqual(len(r['matches']),1)
        self.assertGreaterEqual(len(r['matches'][0]['shared_quantities']),3)

    def test_paraphrased_project_with_one_shared_capacity_requires_review(self):
        old='오라클은 프로젝트 주피터 개발사에 불가항력을 통지. 2.45GW 단지와 계약상 임대료 유예 가능성에 관한 보도.'
        new='Oracle의 2.45GW 데이터센터는 에너지 공급 지연 위험에 직면. 투자 관계자의 별도 매체 설명.'
        self.record(old)
        with patch.object(g,'similarity',return_value=.1924):
            r=g.inspect(self.root,new)
        self.assertEqual(len(r['matches']),1)
        self.assertEqual(r['matches'][0]['shared_quantities'],['2.45gw'])

    def test_low_similarity_common_number_is_not_enough(self):
        self.record('서로 다른 프로젝트의 1GW 발전설비 검토 기사.')
        with patch.object(g,'similarity',return_value=.17):
            r=g.inspect(self.root,'별개 프로젝트의 1GW 송전사업 착공 기사.')
        self.assertEqual(r['matches'],[])

    def test_same_award_headline_matches_despite_different_rounded_amount(self):
        old='**[DOE, 인디애나 PJM·MISO 경계 송전망 개선사업 지원 대상 선정]**\n연방 지원 요청액 1억7,441만달러와 총사업비 3억4,883만달러.'
        new='**[미 DOE, 인디애나 PJM·MISO 접경 송전망 개선에 1억7500만 달러 지원 선정]**\n송전능력 2~4GW 확대 전망과 비용 절감 추산.'
        self.record(old)
        self.assertGreaterEqual(g.similarity(g.headline(old),g.headline(new)),.52)
        with patch.object(g,'similarity',side_effect=[.161,.556]):
            r=g.inspect(self.root,new)
        self.assertEqual(len(r['matches']),1)
        self.assertGreaterEqual(r['matches'][0]['headline_similarity'],.52)

    def test_followup_permitted_with_delta(self):
        self.record()
        r=g.inspect(self.root,self.old.replace('제안','최종 승인'))
        self.assertTrue(g.validate(r,self.review(r,'followup')))
        review=self.review(r,'followup'); review['comparisons'][0].pop('material_delta')
        with self.assertRaises(ValueError): g.validate(r,review)

    def test_stale_message_review_rejected(self):
        r=g.inspect(self.root,self.old)
        review=self.review(r); review['message_sha256']='wrong'
        with self.assertRaises(ValueError): g.validate(r,review)

    def test_complete_receipt_before_ack_included(self):
        path=self.root/'work/runs/old/receipt-one.json'
        path.write_text(json.dumps({'status':'complete','message_text':self.old,'message_sha256':g.digest(self.old),'telegram_message_ids':[99],'article_urls':[]}))
        r=g.inspect(self.root,self.old)
        self.assertEqual(r['matches'][0]['evidence_type'],'telegram_receipt')

    def test_no_hundred_record_cutoff(self):
        for i in range(130): self.record('MISO %s 90일 규제 심사 과거 자료'%i)
        self.assertEqual(len(g.history(self.root)),130)

    def test_old_outbox_requires_review_not_delivery_upgrade(self):
        path=self.root/'work/telegram-outbox/old.txt'
        path.write_text(self.old+' 이 내용은 과거 발송 초안이며 수신 확인 여부가 불명확한 기록',encoding='utf-8')
        r=g.inspect(self.root,self.old)
        self.assertEqual(r['matches'][0]['evidence_type'],'unverified_outbox')
        with self.assertRaises(ValueError): g.validate(r,{'message_sha256':r['message_sha256'],'new_facts':['전력 프로젝트 승인으로 600MW 공급능력 확정']})

    def test_current_draft_not_self_match(self):
        path=self.root/'work/telegram-outbox/new.txt'
        path.write_text(self.old+' 구체적인 계통 접속 검토 대상에 관한 새로운 기술적 설명',encoding='utf-8')
        r=g.inspect(self.root,path.read_text(encoding='utf-8'),path)
        self.assertEqual(r['matches'],[])

    def test_new_receipt_invalidates_prepared_review(self):
        r=g.inspect(self.root,self.old)
        review=self.review(r)
        self.record(self.old.replace('제안','계통 심사 제안'))
        with self.assertRaises(ValueError): g.validate(g.inspect(self.root,self.old),review)

    def test_uncertain_receipt_blocks_same_body(self):
        (self.root/'work/runs/old/receipt-one.json').write_text(json.dumps({'status':'uncertain','message_text':self.old}))
        r=g.inspect(self.root,self.old)
        with self.assertRaises(ValueError): g.validate(r,self.review(r))

    def test_no_new_facts_rejected(self):
        r=g.inspect(self.root,self.old)
        with self.assertRaises(ValueError): g.validate(r,{'message_sha256':r['message_sha256'],'new_facts':[]})

    def test_syndicated_identity_cannot_be_dismissed_as_different_event(self):
        slug='energy-department-will-spend-2-billion-to-squeeze-more-electricity-from-aging-power-grid'
        self.record('DOE funding announcement for its initial grid award. https://one.example/'+slug)
        report=g.inspect(self.root,'New outlet restates the DOE grid funding figure. https://two.example/'+slug)
        with self.assertRaisesRegex(ValueError,'syndicated article identity'):
            g.validate(report,self.review(report))
        review=self.review(report,'followup')
        with self.assertRaisesRegex(ValueError,'evidence of a later material change'):
            g.validate(report,review)
        review['comparisons'][0]['evidence']='The original was updated with the signed grant agreement dated today.'
        self.assertTrue(g.validate(report,review))

    def test_stale_extra_novelty_comparisons_rejected(self):
        report=g.inspect(self.root,'An entirely new construction contract with a verified timeline')
        review=self.review(report)
        review['comparisons']=[{'id':'stale-id','classification':'different_event','reason':'A previous unrelated event which is not in the current report'}]
        with self.assertRaisesRegex(ValueError,'every current guard match'):
            g.validate(report,review)

    def test_power_and_storage_energy_quantities_remain_distinct(self):
        self.assertEqual(g.quantities('2GW, 2GWh, 400MW, 400MWh, 500kV'),
                         {'2gw','2gwh','400mw','400mwh','500kv'})
        self.assertEqual(g.quantities('2GW급 설비와 4GWh의 배터리'),{'2gw','4gwh'})

    def test_tracking_and_query_order_do_not_create_new_source_identity(self):
        first='https://example.com/story?b=2&a=1&utm_source=mail&fbclid=tracking'
        second='https://example.com/story?a=1&b=2&mc_eid=tracking'
        self.assertEqual(g.canonical(first),g.canonical(second))

    def test_missing_legacy_outbox_is_empty_not_a_guard_failure(self):
        (self.root/'work/telegram-outbox').rmdir()
        self.assertEqual(g.history(self.root),{})

    def test_text_cache_does_not_hide_new_receipts(self):
        self.record()
        first=g.inspect(self.root,self.old)
        g.grams.cache_clear()
        g.inspect(self.root,self.old)
        before=g.grams.cache_info()
        g.inspect(self.root,self.old)
        self.assertGreater(g.grams.cache_info().hits,before.hits)
        self.record(self.old+' Additional 2GW signed contract update')
        self.assertEqual(g.inspect(self.root,self.old)['history_count'],first['history_count']+1)

if __name__ == '__main__': unittest.main()
