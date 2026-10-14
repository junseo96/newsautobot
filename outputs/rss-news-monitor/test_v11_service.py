"""Mocked supervisor safety tests. No real workers, network or Telegram calls."""
import hashlib
import copy
import datetime as dt
import json
import sqlite3
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from v11_runtime import read_json, save_json
from v11_service import Service, normalize_simple_headline
from run_packet import RunPacket


class SupervisorSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="newsflow-v11-service-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        scripts = self.root / "outputs/rss-news-monitor"
        save_json(scripts / "runtime-v11.json", {
            "normal_delivery_window_kst": {"start": "06:00", "end": "21:00"},
            "urgent_delivery_24h": True, "review_batch_size": 1,
        })
        self.service = Service(self.root)
        self.url = "https://example.com/grid"
        self.candidate = {"url": self.url, "title": "New grid approval", "summary": "2GW connection approved",
                          "published_at": "2026-09-24T06:00:00+09:00"}
        self.snapshot("run-1", self.candidate)
        self.job = self.service.queue.take(1)[0]
        self.message = "**[2GW 송전망 최종 승인]**\n\n**- 규제기관의 최종 승인으로 2GW 증설과 2028년 준공 확정**\n\n1. 기존 제안 단계에서 확정 승인 단계로 전환\n\n링크: " + self.url
        self.decision = {"index": 0, "action": "send", "urgency": "immediate", "urgency_reason": "대규모 전력공급 차질을 해소하는 최종 승인으로 당일 연결 일정 확정",
            "sector": "grid", "reason": "원문에서 2GW 신규 송전망의 최종 승인 및 준공일 확정 확인",
            "verified": True, "review_basis": "original", "review_category": "industrial_news",
            "source_urls": [self.url], "source_published_at": "2026-09-24", "confidence": 0.99,
            "message_text": self.message, "duplicate_of": None,
            "industrial_signal": {"delivery_policy_revision": "8.3", "geography": "미국", "event_type": "송전망 투자 승인", "maturity": "최종 승인",
                "previous_fact": "송전망 증설 제안 단계", "new_fact": "규제기관의 최종 승인으로 2GW 송전망 증설 확정",
                "affected_market_or_entity": "지역 계통 및 대규모 수용가", "material_industry_effect": "2GW 신규 송전용량 확보로 대규모 수용가 계통접속 확대",
                "evidence_urls": [self.url], "overseas_project": False, "verified_capacity_gw": 2,
                "major_company_research": False, "research_details": None, "smp_tariff_driver": False, "tariff_details": None,
                "rd_exception": False, "rd_details": None},
            "novelty": {"new_facts": ["최종 승인으로 2GW 송전망 증설과 2028년 준공 일정 확정"], "comparisons": []}}
        self.guard = {"message_sha256": hashlib.sha256(self.message.encode()).hexdigest(), "history_count": 0, "matches": []}
        self.network = patch("v11_service.codex", side_effect=AssertionError("A real worker must not run in unit tests"))
        self.network.start()
        self.addCleanup(self.network.stop)

    def snapshot(self, name, candidate):
        path = self.root / "work/runs" / name / "snapshot.json"
        document = {"run_id": name, "generated_at_kst": "2026-09-24T06:00:00+09:00", "run_files": {"snapshot": str(path)}, "candidates": [candidate]}
        save_json(path, document)
        self.service.queue.enqueue(document, path)
        return path

    def test_dashboard_fact_survives_invalid_telegram_format(self):
        decision=copy.deepcopy(self.decision)
        decision['message_text']='invalid Telegram draft'
        decision['dashboard_events']=[{'asset_name':'Grid expansion','asset_kind':'transmission','region':'PJM','state':None,'queue_id':None,'official_project_id':None,'utility':None,'gate':'permit','status':'approved','certainty':'confirmed','direction':'improved','previous_fact':'승인 신청 단계','new_fact':'규제기관의 최종 승인으로 2GW 송전망 증설 확정','effective_date':None,'capacity':None,'remaining_requirements':['건설·통전 개별 확인 필요'],'source_urls':[self.url]}]
        packet=RunPacket.load(self.service.queue.get('latest_snapshot'))
        plan={'schema_version':1,**packet.identity(),'decisions':[decision]}
        with patch('v11_service.delivery_guard.history',return_value=[]):
            result=self.service.process_plan(plan,packet,[(self.job,0)],self.service.work/'reviews/dashboard-independent',evidence=[])
        self.assertTrue(result['invalid_decisions'])
        self.assertEqual(self.service.grid_bridge.status()['observations'],1)
        self.assertEqual(self.stored()['status'],'deferred')

    def stored(self, url=None):
        with self.service.queue.connect() as con:
            return dict(con.execute("SELECT * FROM jobs WHERE url=?", (url or self.url,)).fetchone())

    def manifest(self, *, status="attempted", receipt_status=None, name="existing"):
        run = self.root / "work/runs/run-1"
        paths = {"BatchFile": str(run / "snapshot.json"), "MessageFile": str(run / "message-existing.txt"),
                 "ArticleUrlsFile": str(run / "urls-existing.txt"), "NoveltyReviewFile": str(run / "novelty-existing.json"),
                 "ReceiptFile": str(run / "receipt-existing.json"), "DecisionFile": str(run / "decisions-existing.json"),
                 "Reason": self.decision["reason"]}
        path = self.service.work / "publications" / (name + ".json")
        save_json(path, {"status": status, "job": self.job, "decision": self.decision, "arguments": paths})
        if receipt_status:
            save_json(paths["ReceiptFile"], {"status": receipt_status, "telegram_message_ids": [999] if receipt_status == "complete" else []})
        return path

    def fake_publish(self, root, name, *arguments, **kwargs):
        self.assertEqual(name, "Publish-Brief.ps1")
        if "-ValidateOnly" in arguments:
            return {"valid": True, "novelty_checked": True}
        args = dict(zip(arguments[::2], arguments[1::2]))
        save_json(args["-ReceiptFile"], {"status": "complete", "telegram_message_ids": [999]})
        return {"status": "delivered", "telegram_message_ids": [999], "ack": {"delivered": 1}}

    def test_attempted_without_receipt_cannot_be_retried(self):
        manifest = self.manifest()
        with patch("v11_service.powershell") as publish:
            with self.assertRaisesRegex(RuntimeError, "automatic resend blocked"):
                self.service.publish_manifest(manifest)
            publish.assert_not_called()

    def test_ambiguous_newsletter_link_uses_no_model_or_network(self):
        self.service.queue.finish(self.job,'queued','test')
        with patch('v12_newsletter_context.candidate_link_evidence',return_value={'allowed':None,'reason':'missing_mime'}), \
             patch.object(self.service,'_history_for',return_value=({},[])), \
             patch('v11_source_cache.get') as fetch, patch('v11_service.powershell') as send:
            self.service.review()
            fetch.assert_not_called();send.assert_not_called()
        self.assertEqual(self.stored()['status'],'deferred')
        self.assertGreater(self.stored()['not_before'],time.time()+21590)
        self.assertEqual(self.service.health['stages']['review']['local_deferred'],1)

    def test_metadata_link_exclusion_preserves_uncertain_delivery(self):
        self.service.queue.finish(self.job,'queued','test')
        def fail(job,decision,directory):
            self.service.queue.finish(job,'delivery_uncertain','Existing receipt uncertainty')
            raise RuntimeError('Existing receipt uncertainty')
        with patch('v12_newsletter_context.candidate_link_evidence',return_value={'allowed':False,'reason':'subscription_or_account_action'}), \
             patch.object(self.service,'_history_for',return_value=({},[])), \
             patch.object(self.service,'apply',side_effect=fail),patch('v11_source_cache.get') as fetch:
            self.service.review();fetch.assert_not_called()
        self.assertEqual(self.stored()['status'],'delivery_uncertain')
        self.assertIn('publication',self.service.health['failures'])

    def test_metadata_link_exclusion_records_actual_apply_outcome(self):
        self.service.queue.finish(self.job,'queued','test')
        def requeue(job,decision,directory):self.service.queue.finish(job,'queued','Candidate changed')
        with patch('v12_newsletter_context.candidate_link_evidence',return_value={'allowed':False,'reason':'navigation_or_social_share'}), \
             patch.object(self.service,'_history_for',return_value=({},[])), \
             patch.object(self.service,'apply',side_effect=requeue),patch('v11_source_cache.get') as fetch:
            self.service.review();fetch.assert_not_called()
        self.assertEqual(self.stored()['status'],'queued')
        checks=list((self.service.work/'reviews').glob('*/newsletter-link-prechecks.json'))
        self.assertEqual(read_json(checks[0])['decisions'][0]['action'],'queued')

    def test_allowed_newsletter_passes_human_label_to_worker_without_changing_identity(self):
        self.service.queue.finish(self.job,'deferred','Old validation retry',self.decision)
        self.service.queue.finish(self.job,'queued','New source evidence',self.decision)
        (self.service.scripts/'V11-POLICY.md').write_text('Test editorial policy',encoding='utf-8')
        context={'allowed':True,'label':'Real article headline','context':'Publisher article context','reason':'html_article_candidate'}
        with patch('v12_newsletter_context.candidate_link_evidence',return_value=context), \
             patch.object(self.service,'_history_for',return_value=({},[])), \
             patch.object(self.service,'process_plan') as process, \
             patch('v11_source_cache.get',return_value={'url':self.url,'usable':False}) as fetch, \
             patch('v11_service.codex',return_value=({},[])) as worker:
            self.service.review()
        fetch.assert_called_once_with(self.root,self.url)
        assignment=json.loads(worker.call_args.args[2].split('\nASSIGNMENT\n')[1])
        self.assertEqual(assignment['candidates'][0]['title'],'Real article headline')
        self.assertEqual(assignment['candidates'][0]['url'],self.url)
        self.assertEqual(json.loads(self.stored()['candidate'])['title'],self.candidate['title'])
        process.assert_called_once()

    def test_explicit_preflight_failure_is_retryable_without_claiming_send(self):
        manifest=self.manifest(status='prepared')
        def failed(root,name,*args,**kwargs):
            if '-ValidateOnly' in args:return {'valid':True,'novelty_checked':True}
            raise RuntimeError('PREFLIGHT_FAILED_NO_SEND: database is locked')
        with patch('v11_service.powershell',side_effect=failed):
            with self.assertRaisesRegex(RuntimeError,'PREFLIGHT_FAILED_NO_SEND'):
                self.service.publish_manifest(manifest)
        self.assertEqual(read_json(manifest)['status'],'failed_before_send')
        self.assertEqual(self.stored()['status'],'deferred')

    def test_retry_delay_survives_all_three_publication_callers(self):
        packet=RunPacket.load(self.root/'work/runs/run-1/snapshot.json')
        for error,delay in ((RuntimeError('PREFLIGHT_FAILED_NO_SEND: database is locked'),60),
                            (RuntimeError('ordinary publication validation failure'),1800)):
            for caller in ('cached_review','fresh_review','scheduled_brief'):
                with self.subTest(error=str(error),caller=caller):
                    decision=copy.deepcopy(self.decision)
                    if caller=='scheduled_brief':decision['urgency']='standard'
                    state='ready_day' if caller=='scheduled_brief' else 'deferred'
                    self.service.queue.finish(self.job,state,'Retained validated decision',decision)
                    started=time.time()
                    with patch.object(self.service,'apply',side_effect=error), \
                         patch.object(self.service,'_history_for',return_value=({},[])), \
                         patch('v11_service.delivery_guard.history',return_value={}):
                        if caller=='cached_review':
                            self.service.review()
                        elif caller=='fresh_review':
                            plan={'schema_version':1,**packet.identity(),'decisions':[decision]}
                            self.service.process_plan(plan,packet,[(self.job,0)],self.service.work/'reviews/retry-delay')
                        else:
                            self.service.deliver_scheduled_brief('2026-09-24T10:00+09:00')
                    saved=self.stored()
                    self.assertEqual(saved['status'],'deferred')
                    self.assertGreaterEqual(saved['not_before']-started,delay)
                    self.assertLess(saved['not_before']-started,delay+5)

    def test_preflight_marker_with_existing_receipt_never_becomes_retryable(self):
        for receipt_status in ('partial','uncertain','complete'):
            with self.subTest(receipt_status=receipt_status):
                manifest=self.manifest(status='prepared')
                def failure_with_receipt(root,name,*args,**kwargs):
                    if '-ValidateOnly' in args:return {'valid':True,'novelty_checked':True}
                    save_json(read_json(manifest)['arguments']['ReceiptFile'],{'status':receipt_status})
                    raise RuntimeError('PREFLIGHT_FAILED_NO_SEND: injected receipt race')
                with patch('v11_service.powershell',side_effect=failure_with_receipt):
                    with self.assertRaises(RuntimeError):self.service.publish_manifest(manifest)
                self.assertEqual(read_json(manifest)['status'],'attempted')
                self.assertEqual(self.stored()['status'],'delivery_uncertain')

    def test_attempted_uncertain_or_partial_receipt_cannot_be_retried(self):
        for status in ("uncertain", "partial"):
            with self.subTest(status=status):
                manifest = self.manifest(receipt_status=status)
                with patch("v11_service.powershell") as publish:
                    with self.assertRaisesRegex(RuntimeError, "automatic resend blocked"):
                        self.service.publish_manifest(manifest)
                    publish.assert_not_called()

    def test_complete_receipt_reuses_original_manifest_for_ack(self):
        manifest = self.manifest(receipt_status="complete")
        before = read_json(manifest)["arguments"]
        with patch("v11_service.powershell", side_effect=self.fake_publish) as publish:
            self.service.publish_manifest(manifest)
        self.assertEqual(publish.call_count, 1)
        after = read_json(manifest)
        self.assertEqual(after["status"], "complete")
        self.assertEqual(after["arguments"], before)
        self.assertEqual(self.stored()["status"], "delivered")
        self.assertEqual(self.service.queue.get("last_delivery")["message_ids"], [999])

    def test_complete_manifest_does_not_publish_again(self):
        manifest = self.manifest(status="complete", receipt_status="complete")
        with patch("v11_service.powershell") as publish:
            self.service.publish_manifest(manifest)
            publish.assert_not_called()

    def test_restart_recovery_holds_uncertain_and_reports_failure(self):
        self.manifest(receipt_status="uncertain")
        with patch("v11_service.powershell") as publish:
            self.service.recover()
            publish.assert_not_called()
        self.assertEqual(self.stored()["status"], "delivery_uncertain")
        self.assertIn("publication", read_json(self.service.work / "health.json")["failures"])

    def test_same_process_retry_does_not_create_new_receipt_for_uncertain_send(self):
        self.manifest(receipt_status="uncertain")
        with patch("v11_service.powershell") as publish, patch("v11_service.delivery_guard.inspect", return_value=self.guard):
            self.service.apply(self.job, self.decision, self.service.work / "reviews/test")
            publish.assert_not_called()
        self.assertEqual(self.stored()["status"], "delivery_uncertain")
        self.assertEqual(len(list((self.service.work / "publications").glob("*.json"))), 1)

    def test_changed_candidate_cannot_be_sent_using_old_review(self):
        self.snapshot("run-2", dict(self.candidate, summary="Revised 3GW capacity instead of 2GW"))
        with patch("v11_service.powershell") as publish, patch("v11_service.delivery_guard.inspect", return_value=self.guard):
            self.service.apply(self.job, self.decision, self.service.work / "reviews/test")
            publish.assert_not_called()
        self.assertEqual(self.stored()["status"], "queued")
        self.assertFalse(list((self.service.work / "publications").glob("*.json")))

    def test_unchanged_candidate_rebases_to_latest_snapshot_before_send(self):
        latest = self.snapshot("run-2", dict(self.candidate))
        with patch("v11_service.powershell", side_effect=self.fake_publish) as publish, patch("v11_service.delivery_guard.inspect", return_value=self.guard):
            self.service.apply(self.job, self.decision, self.service.work / "reviews/test")
        args = publish.call_args.args
        self.assertEqual(args[args.index("-BatchFile") + 1], str(latest))
        self.assertEqual(self.stored()["status"], "delivered")

    def test_publication_waits_for_collection_commit_and_snapshot_handoff(self):
        gate = threading.Lock()
        gate.acquire()
        requested = threading.Event()
        failures = []

        class ObservedCollectionLock:
            def __enter__(self):
                requested.set()
                gate.acquire()

            def __exit__(self, *args):
                gate.release()

        self.service.collection_lock = ObservedCollectionLock()

        def publish_job():
            try:
                self.service.apply(self.job, self.decision, self.service.work / "reviews/race")
            except BaseException as error:
                failures.append(error)

        with patch("v11_service.powershell", side_effect=self.fake_publish) as publish, patch("v11_service.delivery_guard.inspect", return_value=self.guard):
            thread = threading.Thread(target=publish_job, daemon=True)
            thread.start()
            try:
                self.assertTrue(requested.wait(3), "Publication must fence the in-progress collection")
                publish.assert_not_called()
                # The collector already owns the collection lock and must still
                # acquire the state lock to publish its newly committed snapshot.
                with self.service.lock:
                    latest = self.snapshot("run-committed", dict(self.candidate))
            finally:
                gate.release()
                thread.join(5)
            self.assertFalse(thread.is_alive(), "Collector/publication lock order must not deadlock")
            self.assertEqual(failures, [])
            args = publish.call_args.args
            self.assertEqual(args[args.index("-BatchFile") + 1], str(latest))
        self.assertEqual(self.stored()["status"], "delivered")

    def test_multiline_message_bytes_match_novelty_hash_without_windows_newline_translation(self):
        observed = []
        def inspect_real_artifacts(root, name, *arguments, **kwargs):
            pairs = arguments[:-1] if arguments[-1:] == ("-ValidateOnly",) else arguments
            args = dict(zip(pairs[::2], pairs[1::2]))
            raw = Path(args["-MessageFile"]).read_bytes()
            novelty = read_json(args["-NoveltyReviewFile"])
            self.assertEqual(raw, self.message.encode("utf-8"))
            self.assertIn(b"\n\n", raw)
            self.assertNotIn(b"\r\n", raw)
            digest = hashlib.sha256(raw).hexdigest()
            self.assertEqual(digest, novelty["message_sha256"])
            observed.append(digest)
            return self.fake_publish(root, name, *arguments, **kwargs)
        with patch("v11_service.powershell", side_effect=inspect_real_artifacts), patch("v11_service.delivery_guard.inspect", return_value=self.guard):
            self.service.apply(self.job, self.decision, self.service.work / "reviews/byte-regression")
        self.assertEqual(observed, [self.guard["message_sha256"], self.guard["message_sha256"]])
        self.assertEqual(self.stored()["status"], "delivered")

    def test_plain_bold_headline_is_normalized_before_validation(self):
        raw=copy.deepcopy(self.decision)
        raw['message_text']=self.message.replace('**[','**',1).replace(']**','**',1)
        fixed,indices=normalize_simple_headline({'decisions':[raw]})
        self.assertEqual(indices,[0])
        self.assertEqual(fixed['decisions'][0]['message_text'],self.message)
        self.assertEqual(raw['message_text'].count('**['),0)

    def test_verified_first_pass_comparison_outside_guard_does_not_block_send(self):
        receipt_id=hashlib.sha256(b'prior related report').hexdigest()
        decision=copy.deepcopy(self.decision)
        decision['novelty']['comparisons']=[{'id':receipt_id,'classification':'followup',
            'reason':'Earlier model report versus newly verified physical test',
            'material_delta':'Prior report was a cost model; this report contains a physical rack test'}]
        record={receipt_id:{'id':receipt_id,'evidence_type':'telegram_receipt'}}
        with patch('v11_service.delivery_guard.inspect',return_value=self.guard), \
             patch('v11_service.delivery_guard.history',return_value=record), \
             patch('v11_service.powershell',side_effect=self.fake_publish) as publish:
            self.service.apply(self.job,decision,self.service.work/'reviews/extra-comparison')
        args=publish.call_args.args
        novelty=read_json(args[args.index('-NoveltyReviewFile')+1])
        self.assertEqual(novelty['comparisons'],[])
        self.assertEqual(self.stored()['status'],'delivered')

    def test_standard_news_waits_and_resumes_from_ready_day(self):
        self.decision["urgency"] = "standard"
        with patch("v11_service.powershell") as publish, patch("v11_service.delivery_guard.inspect", return_value=self.guard), patch("v11_service.may_send", return_value=False):
            self.service.apply(self.job, self.decision, self.service.work / "reviews/test")
            publish.assert_not_called()
        ready = self.service.queue.ready()
        self.assertEqual(len(ready), 1)
        with patch("v11_service.powershell", side_effect=self.fake_publish) as publish, patch("v11_service.delivery_guard.inspect", return_value=self.guard):
            self.service.apply(ready[0], json.loads(ready[0]["result"]), self.service.work / "reviews/resume", force_standard=True)
            self.assertEqual(publish.call_count, 2)
        self.assertEqual(self.stored()["status"], "delivered")

    def test_old_original_is_acknowledged_before_waiting_for_next_brief(self):
        self.service.config['version']=12
        now=dt.datetime.now(dt.timezone.utc)
        path=self.snapshot('run-fresh-feed',dict(self.candidate,published_at=now.isoformat()))
        job=self.service.queue.take(1)[0]
        packet=RunPacket.load(path)
        decision=copy.deepcopy(self.decision)
        decision.update(urgency='standard',source_published_at=(now-dt.timedelta(days=5)).date().isoformat())
        plan={'schema_version':1,**packet.identity(),'decisions':[decision]}
        ack={'run_id':'run-fresh-feed','reviewed':1,'already_recorded':0}
        with patch('v11_service.delivery_guard.history',return_value={}), \
             patch('v11_service.delivery_guard.inspect') as guard, \
             patch('v11_service.may_send',return_value=False), \
             patch('v11_service.powershell',return_value=ack) as command:
            result=self.service.process_plan(plan,packet,[(job,0)],self.service.work/'reviews/stale-original')
        self.assertEqual(self.stored()['status'],'reviewed')
        self.assertEqual(json.loads(self.stored()['result'])['review_category'],'historical')
        self.assertEqual(result['actions'],{'reviewed':1})
        self.assertEqual(command.call_args.args[1],'Ack-Collector.ps1')
        guard.assert_not_called()
        self.assertEqual(plan['decisions'][0]['action'],'send','Raw worker evidence remains unchanged')

    def test_fresh_original_still_waits_for_scheduled_brief(self):
        self.service.config['version']=12
        now=dt.datetime.now(dt.timezone.utc)
        path=self.snapshot('run-current-original',dict(self.candidate,published_at=now.isoformat()))
        job=self.service.queue.take(1)[0]
        packet=RunPacket.load(path)
        decision=copy.deepcopy(self.decision)
        decision.update(urgency='standard',source_published_at=now.isoformat())
        plan={'schema_version':1,**packet.identity(),'decisions':[decision]}
        with patch('v11_service.delivery_guard.history',return_value={}), \
             patch('v11_service.may_send',return_value=False), \
             patch('v11_service.powershell') as command:
            result=self.service.process_plan(plan,packet,[(job,0)],self.service.work/'reviews/current-original')
        self.assertEqual(self.stored()['status'],'ready_day')
        self.assertEqual(result['actions'],{'send':1})
        command.assert_not_called()

    def test_scheduled_brief_slot_is_claimed_once(self):
        self.decision["urgency"] = "standard"
        with patch("v11_service.may_send", return_value=False), patch("v11_service.delivery_guard.inspect", return_value=self.guard):
            self.service.apply(self.job, self.decision, self.service.work / "reviews/hold")
        slot="2026-09-24T10:00+09:00"
        with patch("v11_service.powershell", side_effect=self.fake_publish), patch("v11_service.delivery_guard.inspect", return_value=self.guard):
            self.assertTrue(self.service.deliver_scheduled_brief(slot))
            self.assertFalse(self.service.deliver_scheduled_brief(slot))
        self.assertEqual(self.service.queue.get('last_standard_brief_slot'),slot)
        self.assertEqual(self.stored()["status"], "delivered")

    def test_recovery_of_older_revision_does_not_strand_current_job_inflight(self):
        self.manifest(receipt_status="complete")
        self.snapshot("run-2", dict(self.candidate, summary="Separate newly approved 3GW extension"))
        current = self.service.queue.take(1)[0]
        with patch("v11_service.powershell", side_effect=self.fake_publish), patch("v11_service.delivery_guard.inspect", return_value=self.guard):
            self.service.apply(current, self.decision, self.service.work / "reviews/new")
        self.assertNotEqual(self.stored()["status"], "inflight", "Recovering the old receipt must not abandon the current fingerprint")

    def test_late_verified_article_can_join_already_started_brief_slot(self):
        slot='2026-09-24T10:00+09:00'
        self.service.deliver_scheduled_brief(slot)
        self.decision['urgency']='standard'
        self.service.queue.finish(self.job,'ready_day','Validated after the slot started',self.decision)
        with patch('v11_service.powershell',side_effect=self.fake_publish), patch('v11_service.delivery_guard.inspect',return_value=self.guard):
            self.assertTrue(self.service.deliver_scheduled_brief(slot))
        self.assertEqual(self.stored()['status'],'delivered')

    def test_failed_brief_is_not_reported_complete_and_keeps_draft(self):
        self.decision['urgency']='standard'
        self.service.queue.finish(self.job,'ready_day','Verified draft',self.decision)
        with patch.object(self.service,'apply',side_effect=RuntimeError('preflight unavailable')):
            self.service.deliver_scheduled_brief('2026-09-24T10:00+09:00')
        self.assertEqual(self.service.health['stages']['scheduled_brief']['status'],'failed')
        self.assertEqual(json.loads(self.stored()['result'])['action'],'send')

    def test_guard_change_during_review_blocks_send(self):
        changed = dict(self.guard, matches=[{"id": "new-concurrent-delivery", "same_content": False, "evidence_type": "telegram_receipt"}])
        with patch("v11_service.powershell") as publish, patch("v11_service.delivery_guard.inspect", side_effect=[self.guard, changed]):
            with self.assertRaisesRegex(ValueError, "every current guard match"):
                self.service.apply(self.job, self.decision, self.service.work / "reviews/test")
            publish.assert_not_called()

    def test_reviewed_queue_state_requires_matching_ack_confirmation(self):
        decision = dict(self.decision, action="reviewed", urgency="none", message_text=None)
        for ack in ({"run_id": "wrong-run", "reviewed": 1, "already_recorded": 0},
                    {"run_id": "run-1", "reviewed": 0, "already_recorded": 0}):
            with self.subTest(ack=ack), patch("v11_service.powershell", return_value=ack):
                with self.assertRaises(ValueError):
                    self.service.apply(self.job, decision, self.service.work / "reviews/test")
                self.assertNotEqual(self.stored()["status"], "reviewed")

    def test_valid_reviewed_ack_records_completion(self):
        decision = dict(self.decision, action="reviewed", urgency="none", message_text=None)
        ack = {"run_id": "run-1", "reviewed": 1, "already_recorded": 0}
        with patch("v11_service.powershell", return_value=ack) as command:
            self.service.apply(self.job, decision, self.service.work / "reviews/test")
        self.assertEqual(command.call_args.args[1], "Ack-Collector.ps1")
        self.assertEqual(self.stored()["status"], "reviewed")

    def test_preflight_failure_does_not_become_uncertain_send(self):
        manifest = self.manifest(status="prepared")
        with patch("v11_service.powershell", return_value={"valid": False, "novelty_checked": False}) as publish:
            with self.assertRaisesRegex(ValueError, "preflight failed"):
                self.service.publish_manifest(manifest)
        self.assertEqual(publish.call_count, 1)
        self.assertIn("-ValidateOnly", publish.call_args.args)
        self.assertEqual(read_json(manifest)["status"], "prepared")
        self.assertNotEqual(self.stored()["status"], "delivery_uncertain")

    def test_interrupted_real_publish_preserves_uncertainty(self):
        manifest = self.manifest(status="prepared")
        with patch("v11_service.powershell", side_effect=[{"valid": True, "novelty_checked": True}, TimeoutError("transport interrupted")]):
            with self.assertRaises(TimeoutError):
                self.service.publish_manifest(manifest)
        self.assertEqual(read_json(manifest)["status"], "attempted")
        self.assertEqual(self.stored()["status"], "delivery_uncertain")

    def test_semantic_duplicate_is_receipt_backed_reviewed_ack_without_news_send(self):
        old_url = "https://example.com/previous-grid-report"
        prior_text = "Previously delivered final 2GW grid approval"
        receipt_id = hashlib.sha256(prior_text.encode()).hexdigest()
        report = dict(self.guard, matches=[{"id": receipt_id, "same_content": False,
            "evidence_type": "telegram_receipt", "message_text": prior_text,
            "urls": ["https://example.com/body-link-not-in-delivery-history", old_url]}])
        # A guard receipt may retain extra body links. Only URLs in actual
        # delivery_history can be the duplicate_of target accepted by ACK.
        con = sqlite3.connect(self.root / "work/rss-news-monitor.db")
        try:
            con.execute("CREATE TABLE delivery_history(id INTEGER PRIMARY KEY,url TEXT,message_sha256 TEXT)")
            con.execute("INSERT INTO delivery_history(url,message_sha256) VALUES(?,?)", (old_url, receipt_id))
            con.commit()
        finally:
            con.close()
        second = {"action": "duplicate", "reason": "이전 실제 발송본문과 동일한 2GW 최종 승인 사실이며 새 공사 및 계약 변화 없는 중복", "duplicate_receipt_id": receipt_id, "review": None}
        ack = {"run_id": "run-1", "reviewed": 1, "already_recorded": 0}
        with patch("v11_service.codex", return_value=(second, [])), patch("v11_service.delivery_guard.inspect", return_value=report), patch("v11_service.powershell", return_value=ack) as command:
            self.service.apply(self.job, self.decision, self.service.work / "reviews/duplicate")
        self.assertEqual(command.call_count, 1)
        self.assertEqual(command.call_args.args[1], "Ack-Collector.ps1")
        args = command.call_args.args
        decision_file = args[args.index("-DecisionFile") + 1]
        self.assertEqual(read_json(decision_file)["decisions"][0]["duplicate_of"], old_url)
        self.assertEqual(self.stored()["status"], "reviewed")
        self.assertFalse(list((self.service.work / "publications").glob("*.json")))

    def test_duplicate_body_link_is_replaced_with_actual_receipt_url_before_ack(self):
        receipt_id = hashlib.sha256(b"previous delivery").hexdigest()
        actual_url = "https://example.com/delivered-candidate"
        body_url = "https://example.com/link-only-in-telegram-body"
        database = self.root / "work/rss-news-monitor.db"
        con = sqlite3.connect(database)
        try:
            con.execute("CREATE TABLE delivery_history(id INTEGER PRIMARY KEY,url TEXT,message_sha256 TEXT)")
            con.execute("INSERT INTO delivery_history(url,message_sha256) VALUES(?,?)", (actual_url, receipt_id))
            con.commit()
        finally:
            con.close()
        reviewed = dict(self.decision, action="reviewed", urgency="none", message_text=None,
                        industrial_signal=None, novelty={"new_facts": [], "comparisons": []},
                        review_category="duplicate", duplicate_of={"url": body_url, "receipt_id": receipt_id})
        with patch("v11_service.powershell", return_value={"run_id": "run-1", "reviewed": 1, "already_recorded": 0}) as command:
            self.service.apply(self.job, reviewed, self.service.work / "reviews/duplicate-alias")
        args = command.call_args.args
        saved = read_json(args[args.index("-DecisionFile") + 1])
        self.assertEqual(saved["decisions"][0]["duplicate_of"], actual_url)
        self.assertEqual(self.stored()["status"], "reviewed")

    def test_first_pass_history_uses_short_excerpt_and_ack_url(self):
        receipt_id = hashlib.sha256(b"old message").hexdigest()
        actual_url = "https://example.com/receipt-candidate"
        con = sqlite3.connect(self.root / "work/rss-news-monitor.db")
        try:
            con.execute("CREATE TABLE delivery_history(id INTEGER PRIMARY KEY,url TEXT,message_sha256 TEXT)")
            con.execute("INSERT INTO delivery_history(url,message_sha256) VALUES(?,?)", (actual_url, receipt_id))
            con.commit()
        finally:
            con.close()
        record = {"id": receipt_id, "message_text": "Past grid project " * 500,
                  "urls": {self.url, actual_url}, "evidence_type": "telegram_receipt", "locations": ["receipt"]}
        packet = RunPacket.load(self.root / "work/runs/run-1/snapshot.json")
        with patch("v11_service.delivery_guard.history", return_value={receipt_id: record}):
            full, rows = self.service._history_for(packet, [0])
        self.assertIs(full[receipt_id], record)
        self.assertEqual(rows[0]["delivery_history_urls"], [actual_url])
        self.assertEqual(len(rows[0]["message_excerpt"]), 480)
        self.assertNotIn("message_text", rows[0])

    def test_recent_validated_decision_is_reused_after_publication_failure(self):
        self.service.queue.finish(self.job, "deferred", "ACK failed", self.decision)
        packet = RunPacket.load(self.root / "work/runs/run-1/snapshot.json")
        with patch.object(self.service, "_history_for", return_value=({}, [])), \
             patch.object(self.service, "apply") as apply:
            self.assertTrue(self.service.review())
        apply.assert_called_once()
        self.assertEqual(apply.call_args.args[1]["index"], 0)
        self.assertTrue(list((self.service.work / "reviews").glob("*/cached-retry.json")))

    def test_semantic_duplicate_cannot_use_unverified_outbox(self):
        report = dict(self.guard, matches=[{"id": "draft-only", "same_content": False,
            "evidence_type": "unverified_outbox", "urls": ["https://example.com/unverified"]}])
        second = {"action": "duplicate", "reason": "과거 초안의 문구는 유사하지만 실제 발송한 영수증 증거가 확보되지 않은 상태", "duplicate_receipt_id": "draft-only", "review": None}
        with patch("v11_service.codex", return_value=(second, [])), patch("v11_service.delivery_guard.inspect", return_value=report), patch("v11_service.powershell") as command:
            with self.assertRaisesRegex(ValueError, "lacks verified receipt"):
                self.service.apply(self.job, self.decision, self.service.work / "reviews/duplicate")
            command.assert_not_called()

    def test_novelty_uncertainty_remains_deferred_without_publish_or_ack(self):
        report = dict(self.guard, matches=[{"id": "ambiguous", "same_content": False,
            "evidence_type": "telegram_receipt", "urls": [self.url]}])
        second = {"action": "defer", "reason": "기존 계약과 이번 증설 발표가 동일 범위인지 공식 자료의 추가 확인이 필요한 상태", "duplicate_receipt_id": None, "review": None}
        with patch("v11_service.codex", return_value=(second, [])), patch("v11_service.delivery_guard.inspect", return_value=report), patch("v11_service.powershell") as command:
            self.service.apply(self.job, self.decision, self.service.work / "reviews/defer")
            command.assert_not_called()
        self.assertEqual(self.stored()["status"], "deferred")

    def test_partial_plan_maps_valid_news_by_index_after_invalid_row(self):
        path = self.root / "work/runs/run-2/snapshot.json"
        other = dict(self.candidate, url="https://example.com/second-grid-story")
        snapshot = {"run_id": "run-2", "candidates": [self.candidate, other]}
        save_json(path, snapshot)
        self.service.queue.enqueue(snapshot, path)
        second_job = self.service.queue.take(1)[0]
        packet = RunPacket.load(path)
        invalid = copy.deepcopy(self.decision)
        invalid.update(action="reviewed", urgency="none", verified=False, message_text=None,
                       industrial_signal=None, novelty={"new_facts": [], "comparisons": []})
        valid = copy.deepcopy(self.decision)
        valid["index"] = 1
        plan = {"schema_version": 1, **packet.identity(), "decisions": [invalid, valid]}
        with patch("v11_service.delivery_guard.history", return_value={}), patch.object(self.service, "apply") as apply:
            result = self.service.process_plan(plan, packet, [(self.job, 0), (second_job, 1)], self.service.work / "reviews/partial", evidence={})
        self.assertEqual(apply.call_count, 1)
        self.assertEqual(apply.call_args.args[0]["url"], other["url"])
        self.assertEqual(apply.call_args.args[1]["index"], 1)
        self.assertEqual(self.stored()["status"], "deferred")
        self.assertEqual(result["actual_decisions"], 1)
        self.assertEqual(set(result["invalid_decisions"]), {0})


if __name__ == "__main__":
    unittest.main()
