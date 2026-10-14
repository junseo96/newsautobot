"""Strict, side-effect-free V11 worker contract and publisher artifact rendering.

``verified`` means evidence sufficient for the *stated decision* was obtained.
Sending requires original-source review. Clearly irrelevant metadata can support
an explicit exclusion; reading a candidate title does not verify industrial news.
This module never fetches sources, sends messages, reads credentials or changes DBs.
Telegram noun-ending/format validation remains in Publish-Brief.ps1.
"""
from __future__ import annotations

import datetime as dt
import copy
import hashlib
import json
import re
from urllib.parse import urlsplit

from delivery_guard import canonical, validate as guard_validate


MIN_SEND_CONFIDENCE = 0.8


def _object(properties):
    return {"type": "object", "additionalProperties": False,
            "properties": properties, "required": list(properties)}


def _nullable(schema):
    return {"anyOf": [schema, {"type": "null"}]}


COMPARISON_SCHEMA = _object({
    "id": {"type": "string"},
    "classification": {"type": "string", "enum": ["followup", "different_event", "confirmed_unsent"]},
    "reason": {"type": "string"},
    "material_delta": {"type": "string"},
    "evidence": {"type": "string"},
})
NOVELTY_SCHEMA = _object({
    "new_facts": {"type": "array", "items": {"type": "string"}},
    "comparisons": {"type": "array", "items": COMPARISON_SCHEMA},
})
INDUSTRIAL_SIGNAL_SCHEMA = _object({
    "delivery_policy_revision": {"type": "string", "enum": ["8.3"]},
    "geography": {"type": "string"},
    "event_type": {"type": "string"},
    "maturity": {"type": "string"},
    "previous_fact": {"type": "string"},
    "new_fact": {"type": "string"},
    "affected_market_or_entity": {"type": "string"},
    "material_industry_effect": {"type": "string"},
    "evidence_urls": {"type": "array", "items": {"type": "string"}},
    "overseas_project": {"type": "boolean"},
    "verified_capacity_gw": _nullable({"type": "number"}),
    "major_company_research": {"type": "boolean"},
    "research_details": _nullable({"type": "string"}),
    "smp_tariff_driver": {"type": "boolean"},
    "tariff_details": _nullable({"type": "string"}),
    "rd_exception": {"type": "boolean"},
    "rd_details": _nullable({"type": "string"}),
})
DECISION_ITEM_SCHEMA = _object({
    "index": {"type": "integer"},
    "action": {"type": "string", "enum": ["send", "reviewed", "defer"]},
    "urgency": {"type": "string", "enum": ["immediate", "standard", "none"]},
    "urgency_reason": {"type": "string"},
    "sector": {"type": "string", "enum": ["market", "grid", "projects", "companies", "technology"]},
    "reason": {"type": "string"},
    "verified": {"type": "boolean"},
    "review_basis": {"type": "string", "enum": ["original", "metadata", "unavailable"]},
    "review_category": {"type": "string", "enum": [
        "industrial_news", "out_of_scope", "non_article", "event_notice",
        "historical", "duplicate", "access_gap", "unverified"]},
    "source_urls": {"type": "array", "items": {"type": "string"}},
    "source_published_at": _nullable({"type": "string"}),
    "confidence": {"type": "number"},
    "industrial_signal": _nullable(INDUSTRIAL_SIGNAL_SCHEMA),
    "message_text": _nullable({"type": "string"}),
    "duplicate_of": _nullable(_object({"url": {"type": "string"}, "receipt_id": {"type": "string"}})),
    "novelty": NOVELTY_SCHEMA,
})
DECISION_SCHEMA = _object({
    "schema_version": {"type": "integer", "enum": [1]},
    "run_id": {"type": "string"},
    "snapshot_sha256": {"type": "string"},
    "decisions": {"type": "array", "items": DECISION_ITEM_SCHEMA},
})
NOVELTY_REVIEW_SCHEMA = _object({
    "message_sha256": {"type": "string"},
    **NOVELTY_SCHEMA["properties"],
})


def _shape(value, schema, where="response"):
    """Enforce this small strict schema without an optional package dependency."""
    if "anyOf" in schema:
        for alternative in schema["anyOf"]:
            try:
                _shape(value, alternative, where)
                return
            except ValueError:
                pass
        raise ValueError(f"{where} has an invalid nullable value")
    checks = {"object": lambda x: type(x) is dict, "array": lambda x: type(x) is list,
              "string": lambda x: type(x) is str, "integer": lambda x: type(x) is int,
              "number": lambda x: type(x) in (int, float), "boolean": lambda x: type(x) is bool,
              "null": lambda x: x is None}
    if not checks[schema["type"]](value):
        raise ValueError(f"{where} must be {schema['type']}")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"{where} has an unsupported value")
    if schema["type"] == "object":
        expected = set(schema["properties"])
        if set(value) != expected:
            raise ValueError(f"{where} fields differ: missing={sorted(expected-set(value))}, unexpected={sorted(set(value)-expected)}")
        for key, child in schema["properties"].items():
            _shape(value[key], child, f"{where}.{key}")
    elif schema["type"] == "array":
        for index, item in enumerate(value):
            _shape(item, schema["items"], f"{where}[{index}]")


def _http_url(value):
    parsed = urlsplit(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.hostname) and not parsed.username and not parsed.password


def _date(value):
    if value is None:
        return
    if len(value) == 10:
        dt.date.fromisoformat(value)
        return
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("source_published_at timestamp requires timezone")


def _message(value, sources):
    """Reject empty/placeholder drafts before the canonical PowerShell checks."""
    message = value.strip() if isinstance(value, str) else ""
    headlines = re.findall(r"(?m)^\*\*\[[^\r\n]+\]\*\*\r?$", message)
    if len(headlines) != 1:
        raise ValueError("send requires exactly one bold bracketed article headline")
    summaries = re.findall(r"(?m)^\*\*- ([^\r\n]*)\*\*\r?$", message)
    if len(summaries) != 1:
        raise ValueError("send requires exactly one substantive bold summary")
    summary = re.sub(r"[\u200b-\u200f\ufeff]", "", summaries[0]).strip()
    summary = re.sub(r"^(?:요약|핵심\s*요약|한\s*줄\s*요약|summary|tl;?dr)\s*[:：]\s*", "", summary, flags=re.I)
    key = re.sub(r"[^\w가-힣]", "", summary).lower()
    if len(key) < 8 or re.fullmatch(r"(?:(?:핵심|한줄)?요약(?:문|내용)?|summary|tldr|todo|tbd|내용없음|미작성|작성(?:예정|필요)?|입력)(?:작성|예정|필요|입력|삽입)*", key):
        raise ValueError("send summary must contain actual facts, not a placeholder")
    if not re.search(r"(?m)^1\. .{8,}", message):
        raise ValueError("send requires substantive numbered details")
    links = re.findall(r"(?m)^링크: (https?://\S+)\s*$", message)
    links += re.findall(r"(?m)^\[원문보기\]\((https?://[^\r\n]+)\)\s*$", message)
    if not links or any(canonical(link) not in {canonical(url) for url in sources} for link in links):
        raise ValueError("message source link must be among the reviewed source_urls")
    if message.count("**") % 2:
        raise ValueError("unbalanced bold markers")
    return message


def _duplicate(decision, delivered_evidence):
    duplicate = decision["duplicate_of"]
    stated_duplicate = decision["review_category"] == "duplicate" or "duplicate" in decision["reason"].lower() or "중복" in decision["reason"] or "이전 보도와 유사" in decision["reason"]
    if duplicate is None:
        if stated_duplicate and decision["action"] == "reviewed":
            raise ValueError("duplicate exclusion needs a receipt-backed duplicate_of")
        return
    if decision["action"] != "reviewed" or decision["review_category"] != "duplicate":
        raise ValueError("duplicate_of is valid only on a reviewed duplicate")
    if not _http_url(duplicate["url"]):
        raise ValueError("duplicate URL is invalid")
    for record in delivered_evidence or []:
        if record.get("id") != duplicate["receipt_id"] or record.get("evidence_type") != "telegram_receipt":
            continue
        text = record.get("message_text", "")
        if hashlib.sha256(text.encode("utf-8")).hexdigest() != record["id"]:
            continue
        if canonical(duplicate["url"]) in {canonical(url) for url in record.get("urls", [])}:
            return
    raise ValueError("duplicate exclusion lacks matching verified delivery history")


def _signal(signal, sources):
    if signal is None:
        raise ValueError("send requires a structured industrial signal")
    for key in ("geography", "event_type", "maturity", "previous_fact", "new_fact",
                "affected_market_or_entity", "material_industry_effect"):
        if not signal[key].strip():
            raise ValueError(f"industrial_signal.{key} requires a concrete fact")
    if len(signal["new_fact"].strip()) < 12 or len(signal["material_industry_effect"].strip()) < 12:
        raise ValueError("industrial signal must state a concrete new fact and industry effect")
    evidence = signal["evidence_urls"]
    reviewed = {canonical(url) for url in sources}
    if not evidence or any(not _http_url(url) or canonical(url) not in reviewed for url in evidence):
        raise ValueError("industrial signal evidence must match reviewed source URLs")
    capacity = signal["verified_capacity_gw"]
    if capacity is not None and (not 0 < capacity < float("inf")):
        raise ValueError("verified capacity must be a positive finite number")
    # Geography/scale exceptions are editorial policy, not a blanket numeric
    # gate: official supply contracts may withhold total MW and still qualify.
    for flag, detail in (("major_company_research", "research_details"),
                         ("smp_tariff_driver", "tariff_details"), ("rd_exception", "rd_details")):
        if signal[flag] and (not signal[detail] or len(signal[detail].strip()) < 20):
            raise ValueError(f"{flag} requires concrete {detail}")


def validate_plan(plan, snapshot, expected_indices, snapshot_sha256=None, delivered_evidence=None):
    """Return decisions in assigned order, requiring exact coverage and evidence.

    ``snapshot_sha256`` must be the immutable file hash when loaded from disk.
    ``delivered_evidence`` is trusted read-only output of delivery_guard.history,
    passed as records (or dict.values()), never worker-specified arbitrary files.
    Missing/invalid decisions reject the entire worker result; no partial ACK.
    """
    _shape(plan, DECISION_SCHEMA)
    candidates = snapshot.get("candidates")
    if not isinstance(candidates, list):
        raise ValueError("snapshot candidates are required")
    indices = list(expected_indices)
    if any(type(i) is not int or i < 0 or i >= len(candidates) for i in indices) or len(set(indices)) != len(indices):
        raise ValueError("expected indices must be unique valid snapshot indices")
    if snapshot_sha256 is None:
        snapshot_sha256 = hashlib.sha256(json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()
    if plan["run_id"] != snapshot.get("run_id") or plan["snapshot_sha256"] != snapshot_sha256:
        raise ValueError("worker response belongs to a different immutable snapshot")
    decisions = plan["decisions"]
    actual = [item["index"] for item in decisions]
    if len(set(actual)) != len(actual) or set(actual) != set(indices):
        raise ValueError("worker decisions must cover every assigned index exactly once")
    evidence = list(delivered_evidence.values() if isinstance(delivered_evidence, dict) else delivered_evidence or [])
    for decision in decisions:
        if len(decision["reason"].strip()) < 20:
            raise ValueError("each decision requires a concrete reason of at least 20 characters")
        if not 0 <= decision["confidence"] <= 1:
            raise ValueError("confidence must be between zero and one")
        if any(not _http_url(url) for url in decision["source_urls"]):
            raise ValueError("source_urls must contain HTTP(S) evidence links")
        if len(set(decision["source_urls"])) != len(decision["source_urls"]):
            raise ValueError("source_urls must not repeat")
        _date(decision["source_published_at"])
        action, basis, category = decision["action"], decision["review_basis"], decision["review_category"]
        if action == "send":
            if decision["urgency"] not in {"immediate", "standard"}:
                raise ValueError("send urgency must be immediate or standard")
            if len(decision["urgency_reason"].strip()) < 20:
                raise ValueError("send needs a concrete urgency reason of at least 20 characters")
        elif decision["urgency"] != "none":
            raise ValueError("reviewed/defer urgency must be none")
        if action in {"send", "reviewed"} and not decision["verified"]:
            raise ValueError("send/reviewed requires verified decision evidence")
        if action in {"send", "reviewed"} and basis == "unavailable":
            raise ValueError("unavailable originals remain defer, not completed review")
        if basis == "original" and not decision["source_urls"]:
            raise ValueError("original review requires source URLs")
        if action == "reviewed" and basis == "metadata" and category not in {"out_of_scope", "non_article", "event_notice", "historical"}:
            raise ValueError("metadata cannot complete industrial or duplicate review")
        if action == "reviewed" and category in {"access_gap", "unverified"}:
            raise ValueError("access gaps and unverified facts must remain defer")
        if action == "reviewed" and category == "historical" and not decision["source_published_at"]:
            raise ValueError("historical exclusion requires an actual source date")
        _duplicate(decision, evidence)
        if action == "send":
            if basis != "original" or category != "industrial_news" or not decision["source_published_at"]:
                raise ValueError("send requires original industrial news and actual publication date")
            if decision["confidence"] < MIN_SEND_CONFIDENCE:
                raise ValueError("send requires high confidence")
            _signal(decision["industrial_signal"], decision["source_urls"])
            _message(decision["message_text"], decision["source_urls"])
            facts = decision["novelty"]["new_facts"]
            if not facts or any(len(fact.strip()) < 12 for fact in facts):
                raise ValueError("send requires concrete new industrial facts")
        elif decision["message_text"] is not None or decision["novelty"]["new_facts"] or decision["novelty"]["comparisons"]:
            raise ValueError("non-send decisions must not contain a draft or novelty claim")
    by_index = {item["index"]: item for item in decisions}
    return [by_index[index] for index in indices]


def validate_partial_plan(plan, snapshot, expected_indices, snapshot_sha256=None, delivered_evidence=None):
    """Isolate semantic failures after strict whole-assignment integrity checks.

    Malformed schema, wrong snapshot identity, or incomplete/duplicate coverage
    rejects the whole result. For a well-formed assignment every row still uses
    the unchanged ``validate_plan`` rules. Valid rows may progress; invalid rows
    retain their exact index and reason for retry, never becoming reviewed.
    """
    _shape(plan, DECISION_SCHEMA)
    candidates = snapshot.get("candidates")
    if not isinstance(candidates, list):
        raise ValueError("snapshot candidates are required")
    indices = list(expected_indices)
    if any(type(i) is not int or i < 0 or i >= len(candidates) for i in indices) or len(set(indices)) != len(indices):
        raise ValueError("expected indices must be unique valid snapshot indices")
    if snapshot_sha256 is None:
        snapshot_sha256 = hashlib.sha256(json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()
    if plan["run_id"] != snapshot.get("run_id") or plan["snapshot_sha256"] != snapshot_sha256:
        raise ValueError("worker response belongs to a different immutable snapshot")
    actual = [item["index"] for item in plan["decisions"]]
    if len(set(actual)) != len(actual) or set(actual) != set(indices):
        raise ValueError("worker decisions must cover every assigned index exactly once")
    evidence = list(delivered_evidence.values() if isinstance(delivered_evidence, dict) else delivered_evidence or [])
    by_index = {item["index"]: item for item in plan["decisions"]}
    valid, invalid = [], {}
    for index in indices:
        single = {**plan, "decisions": [by_index[index]]}
        try:
            valid.extend(validate_plan(single, snapshot, [index], snapshot_sha256, evidence))
        except ValueError as exc:
            invalid[index] = str(exc)
    return valid, invalid


def render_send(decision, candidate_url):
    """Render inputs for Publish-Brief; not an authorization to bypass its guard."""
    if decision.get("action") != "send" or not _http_url(candidate_url):
        raise ValueError("render_send requires a send decision and candidate URL")
    message = _message(decision["message_text"], decision["source_urls"])
    return {"message_text": message, "article_urls": [candidate_url], "novelty": {
        "message_sha256": hashlib.sha256(message.encode("utf-8")).hexdigest(),
        "new_facts": list(decision["novelty"]["new_facts"]),
        "comparisons": list(decision["novelty"]["comparisons"]),
        "industrial_signal": copy.deepcopy(decision["industrial_signal"]),
    }}


def validate_novelty(report, review):
    """Second pass must compare every guard match, bound to this exact text hash."""
    # The second worker returns only hash/facts/comparisons. The supervisor can
    # preserve the first-pass industrial signal when creating the final artifact.
    plain = {key: value for key, value in review.items() if key != "industrial_signal"}
    _shape(plain, NOVELTY_REVIEW_SCHEMA)
    if "industrial_signal" in review:
        _shape(review["industrial_signal"], INDUSTRIAL_SIGNAL_SCHEMA)
    actual = [comparison["id"] for comparison in review["comparisons"]]
    expected = [match["id"] for match in report.get("matches", [])]
    if len(set(actual)) != len(actual) or set(actual) != set(expected):
        raise ValueError("novelty comparisons must cover every current guard match exactly once")
    guard_validate(report, review)
    return review


def build_reviewed_document(plan, snapshot, expected_indices, snapshot_sha256=None, delivered_evidence=None):
    decisions = validate_plan(plan, snapshot, expected_indices, snapshot_sha256, delivered_evidence)
    rows = []
    for decision in decisions:
        if decision["action"] != "reviewed":
            continue
        row = {"url": snapshot["candidates"][decision["index"]]["url"],
               "status": "reviewed", "reason": decision["reason"].strip()}
        if decision["duplicate_of"]:
            row["duplicate_of"] = decision["duplicate_of"]["url"]
        rows.append(row)
    return {"run_id": snapshot["run_id"], "decisions": rows}
