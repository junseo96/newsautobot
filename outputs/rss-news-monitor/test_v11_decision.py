"""V11 contract tests; no network, production files, sending or DB mutations."""
import copy
import hashlib
import json
import unittest

from v11_decision import (DECISION_SCHEMA, NOVELTY_REVIEW_SCHEMA, build_reviewed_document,
                          render_send, validate_novelty, validate_plan, validate_partial_plan)


class DecisionContractTests(unittest.TestCase):
    def setUp(self):
        self.url = "https://example.com/grid-project"
        self.snapshot = {"run_id": "fixture-run", "candidates": [
            {"title": "New 2GW transmission approval", "url": self.url},
            {"title": "Football season results", "url": "https://example.com/sport"},
            {"title": "Potential utility capital increase", "url": "https://example.com/investment"},
        ]}
        self.sha = hashlib.sha256(json.dumps(self.snapshot, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
        self.message = ("**[2GW 송전망 최종 투자 승인]**\n\n"
                        "**- 2GW 신규 송전능력 확보와 2028년 준공 일정 확정**\n\n"
                        "1. 규제기관 최종 승인으로 기존 제안 단계에서 건설 준비 단계로 전환\n\n"
                        "링크: " + self.url)
        self.send = {"index": 0, "action": "send", "reason": "원문에서 2GW 송전망 최종 승인 및 준공일 확정 확인",
                     "urgency": "standard", "urgency_reason": "신규 송전투자 결정이지만 즉시 대응 필요한 공급중단 등 긴급상황은 없는 사안", "sector": "grid",
                     "verified": True, "review_basis": "original", "review_category": "industrial_news",
                     "source_urls": [self.url], "source_published_at": "2026-09-24",
                     "confidence": 0.95, "industrial_signal": {
                         "delivery_policy_revision": "8.3", "geography": "미국", "event_type": "규제승인", "maturity": "최종 승인",
                         "previous_fact": "2GW 송전망 투자 제안 단계", "new_fact": "최종 규제승인으로 2GW 송전망 투자 및 2028년 준공 확정",
                         "affected_market_or_entity": "지역 전력계통 및 대규모 수용가", "material_industry_effect": "2GW 송전용량 증설로 대규모 수용가의 계통접속 여력 확대",
                         "evidence_urls": [self.url], "overseas_project": False, "verified_capacity_gw": 2,
                         "major_company_research": False, "research_details": None,
                         "smp_tariff_driver": False, "tariff_details": None, "rd_exception": False, "rd_details": None},
                     "message_text": self.message, "duplicate_of": None,
                     "novelty": {"new_facts": ["규제기관 최종 승인으로 2GW 송전 증설 및 2028년 준공 일정 확정"], "comparisons": []}}
        self.reviewed = {"index": 1, "action": "reviewed", "reason": "제목에 명시된 축구 경기 결과로 전력 및 산업 범주와 무관",
                         "urgency": "none", "urgency_reason": "발송 대상 아님", "sector": "market",
                         "verified": True, "review_basis": "metadata", "review_category": "out_of_scope",
                         "source_urls": [], "source_published_at": None, "confidence": 1,
                         "industrial_signal": None, "message_text": None, "duplicate_of": None,
                         "novelty": {"new_facts": [], "comparisons": []}}
        self.defer = {"index": 2, "action": "defer", "reason": "공식 발표 원문 접속 403으로 투자규모 및 확정 여부 확인 불가",
                      "urgency": "none", "urgency_reason": "원문 확인 전 긴급 발송 판단 불가", "sector": "companies",
                      "verified": False, "review_basis": "unavailable", "review_category": "access_gap",
                      "source_urls": [], "source_published_at": None, "confidence": 0,
                      "industrial_signal": None, "message_text": None, "duplicate_of": None,
                      "novelty": {"new_facts": [], "comparisons": []}}
        self.plan = {"schema_version": 1, "run_id": "fixture-run", "snapshot_sha256": self.sha,
                     "decisions": [self.send, self.reviewed, self.defer]}

    def validate(self, **kwargs):
        return validate_plan(self.plan, self.snapshot, [0, 1, 2], self.sha, **kwargs)

    def test_complete_coverage_and_side_effect_free_rendering(self):
        before = copy.deepcopy(self.plan)
        self.assertEqual(len(self.validate()), 3)
        rendered = render_send(self.send, self.url)
        self.assertEqual(rendered["article_urls"], [self.url])
        self.assertEqual(rendered["novelty"]["message_sha256"], hashlib.sha256(self.message.encode()).hexdigest())
        self.assertEqual(rendered["novelty"]["industrial_signal"], self.send["industrial_signal"])
        self.assertEqual(validate_novelty({"message_sha256": rendered["novelty"]["message_sha256"], "matches": []}, rendered["novelty"]), rendered["novelty"])
        reviewed = build_reviewed_document(self.plan, self.snapshot, [0, 1, 2], self.sha)
        self.assertEqual(reviewed["decisions"], [{"url": self.snapshot["candidates"][1]["url"], "status": "reviewed", "reason": self.reviewed["reason"]}])
        self.assertEqual(self.plan, before)

    def test_schema_every_object_is_strict_with_all_properties_required(self):
        def check(node):
            if isinstance(node, dict):
                if node.get("type") == "object":
                    self.assertIs(node.get("additionalProperties"), False)
                    self.assertEqual(set(node["required"]), set(node["properties"]))
                for child in node.values():
                    check(child)
            elif isinstance(node, list):
                for child in node:
                    check(child)
        check(DECISION_SCHEMA)
        check(NOVELTY_REVIEW_SCHEMA)

    def test_missing_extra_duplicate_indices_rejected(self):
        for items in ([self.send, self.reviewed], [self.send, self.reviewed, self.reviewed], [self.send, self.reviewed, self.defer, self.defer]):
            with self.subTest(items=len(items)):
                self.plan["decisions"] = items
                with self.assertRaisesRegex(ValueError, "every assigned index"):
                    self.validate()

    def test_wrong_snapshot_hash_and_unknown_properties_rejected(self):
        self.plan["snapshot_sha256"] = "wrong"
        with self.assertRaisesRegex(ValueError, "different immutable snapshot"):
            self.validate()
        self.plan["snapshot_sha256"] = self.sha
        self.send["receipt_file"] = "untrusted-file"
        with self.assertRaisesRegex(ValueError, "fields differ"):
            self.validate()

    def test_unverified_or_metadata_send_never_accepted(self):
        self.send["verified"] = False
        with self.assertRaisesRegex(ValueError, "verified"):
            self.validate()
        self.send["verified"] = True
        self.send["review_basis"] = "metadata"
        with self.assertRaisesRegex(ValueError, "original industrial news"):
            self.validate()

    def test_inaccessible_source_cannot_be_completed(self):
        self.defer.update(action="reviewed", verified=True)
        with self.assertRaisesRegex(ValueError, "unavailable originals"):
            self.validate()

    def test_send_urgency_cannot_be_none_or_have_empty_reason(self):
        self.send["urgency"] = "none"
        with self.assertRaisesRegex(ValueError, "send urgency"):
            self.validate()
        self.send["urgency"] = "immediate"
        self.send["urgency_reason"] = "중요함"
        with self.assertRaisesRegex(ValueError, "concrete urgency reason"):
            self.validate()
        self.send["urgency_reason"] = "2GW 공급 차질을 해소하는 신규 승인으로 당일 대규모 수용가 전력공급 재개 확정"
        self.validate()

    def test_reviewed_and_defer_urgency_must_be_none(self):
        for item in (self.reviewed, self.defer):
            item["urgency"] = "immediate"
            with self.assertRaisesRegex(ValueError, "reviewed/defer urgency"):
                self.validate()
            item["urgency"] = "none"

    def test_metadata_industrial_or_duplicate_exclusion_rejected(self):
        for category in ("industrial_news", "duplicate"):
            self.reviewed["review_category"] = category
            with self.assertRaisesRegex(ValueError, "metadata cannot complete"):
                self.validate()

    def test_historical_exclusion_requires_date(self):
        self.reviewed["review_category"] = "historical"
        with self.assertRaisesRegex(ValueError, "actual source date"):
            self.validate()

    def test_industrial_signal_is_required_and_evidence_must_match(self):
        original = self.send["industrial_signal"]
        self.send["industrial_signal"] = None
        with self.assertRaisesRegex(ValueError, "structured industrial signal"):
            self.validate()
        self.send["industrial_signal"] = original
        original["evidence_urls"] = ["https://unreviewed.com/story"]
        with self.assertRaisesRegex(ValueError, "match reviewed source"):
            self.validate()

    def test_industrial_exceptions_need_evidence_details(self):
        signal = self.send["industrial_signal"]
        for flag in ("major_company_research", "smp_tariff_driver", "rd_exception"):
            signal[flag] = True
            with self.assertRaisesRegex(ValueError, "requires concrete"):
                self.validate()
            signal[flag] = False

    def test_bare_summary_and_foreign_source_link_rejected(self):
        self.send["message_text"] = self.message.replace("2GW 신규 송전능력 확보와 2028년 준공 일정 확정", "요약")
        with self.assertRaisesRegex(ValueError, "actual facts"):
            self.validate()
        self.send["message_text"] = self.message.replace(self.url, "https://unreviewed.com/story")
        with self.assertRaisesRegex(ValueError, "reviewed source_urls"):
            self.validate()

    def test_duplicate_requires_verified_actual_receipt_history(self):
        self.reviewed.update(review_basis="original", review_category="duplicate", source_urls=[self.url],
                             reason="이미 발송한 송전망 최종 승인과 동일한 사실이며 추가 산업 변화 없는 중복")
        with self.assertRaisesRegex(ValueError, "receipt-backed"):
            self.validate()
        record = {"id": hashlib.sha256(self.message.encode()).hexdigest(), "message_text": self.message,
                  "evidence_type": "unverified_outbox", "urls": [self.url]}
        self.reviewed["duplicate_of"] = {"url": self.url, "receipt_id": record["id"]}
        with self.assertRaisesRegex(ValueError, "verified delivery history"):
            self.validate(delivered_evidence=[record])
        record["evidence_type"] = "telegram_receipt"
        self.validate(delivered_evidence=[record])
        record["message_text"] = "tampered"
        with self.assertRaisesRegex(ValueError, "verified delivery history"):
            self.validate(delivered_evidence=[record])

    def test_defer_is_excluded_from_ack_and_never_fabricates_send(self):
        self.defer["message_text"] = self.message
        with self.assertRaisesRegex(ValueError, "non-send"):
            self.validate()

    def test_novelty_second_pass_requires_all_and_only_actual_matches(self):
        review = render_send(self.send, self.url)["novelty"]
        report = {"message_sha256": review["message_sha256"], "matches": [
            {"id": "old-id", "same_content": False, "evidence_type": "telegram_receipt"}]}
        with self.assertRaisesRegex(ValueError, "every current guard match"):
            validate_novelty(report, review)
        comparison = {"id": "old-id", "classification": "followup", "reason": "이전 제안 보도 이후 규제기관의 최종 승인 및 투자 착수 사실이 추가됨",
                      "material_delta": "기존 2GW 송전망 제안 단계에서 최종 규제승인 완료로 진행단계 변경", "evidence": ""}
        review["comparisons"] = [comparison]
        validate_novelty(report, review)
        report["matches"][0]["same_content"] = True
        with self.assertRaisesRegex(ValueError, "Same content already"):
            validate_novelty(report, review)

    def test_partial_validation_preserves_good_news_when_one_row_is_unverified(self):
        self.reviewed["verified"] = False
        valid, invalid = validate_partial_plan(self.plan, self.snapshot, [0, 1, 2], self.sha)
        self.assertEqual([row["index"] for row in valid], [0, 2])
        self.assertEqual(set(invalid), {1})
        self.assertIn("verified decision evidence", invalid[1])
        self.assertFalse(self.reviewed["verified"], "validation must not repair claims")
        with self.assertRaises(ValueError):
            self.validate()

    def test_partial_validation_rejects_non_send_novelty_without_blocking_valid_subset(self):
        self.reviewed["novelty"]["new_facts"] = ["확인했으나 발송하지 않을 내용이 잘못된 필드에 포함된 사례"]
        valid, invalid = validate_partial_plan(self.plan, self.snapshot, [2, 1, 0], self.sha)
        self.assertEqual([row["index"] for row in valid], [2, 0])
        self.assertEqual(set(invalid), {1})
        self.assertIn("non-send decisions", invalid[1])

    def test_partial_validation_rejects_wrong_global_hash(self):
        self.plan["snapshot_sha256"] = "wrong-hash"
        with self.assertRaisesRegex(ValueError, "different immutable snapshot"):
            validate_partial_plan(self.plan, self.snapshot, [0, 1, 2], self.sha)

    def test_partial_validation_rejects_missing_or_duplicate_indices_globally(self):
        for items in ([self.send, self.defer], [self.send, self.reviewed, self.reviewed]):
            self.plan["decisions"] = items
            with self.assertRaisesRegex(ValueError, "every assigned index"):
                validate_partial_plan(self.plan, self.snapshot, [0, 1, 2], self.sha)

    def test_partial_validation_rejects_malformed_schema_globally(self):
        self.reviewed["unknown_field"] = "cannot silently ignore"
        with self.assertRaisesRegex(ValueError, "fields differ"):
            validate_partial_plan(self.plan, self.snapshot, [0, 1, 2], self.sha)


if __name__ == "__main__":
    unittest.main()
