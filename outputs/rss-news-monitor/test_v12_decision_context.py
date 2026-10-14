"""Context reduction must not silently narrow the authoritative guard."""
import copy
import unittest

from delivery_guard import digest
from v12_decision_context import compact_novelty_payload, shortlist_related


class DecisionContextTests(unittest.TestCase):
    def row(self, number, url=None, evidence="telegram_receipt"):
        text = f"PJM approval for 2GW power grid transmission project number {number}"
        return {"id": digest(text), "message_text": text,
                "evidence_type": evidence, "urls": {url or f"https://example.com/{number}"}}

    def test_lexical_discovery_is_bounded_per_candidate(self):
        rows = [self.row(i) for i in range(20)]
        related = shortlist_related([{"url": "https://example.com/new", "title": "PJM power grid transmission project approval"}], rows, {})
        self.assertEqual(len(related), 3)

    def test_exact_source_matches_survive_discovery_cap(self):
        url = "https://example.com/rolling-project"
        rows = [self.row(i, url) for i in range(8)]
        related = shortlist_related([{"url": url, "title": "Changed project"}], rows, {}, limit_per_candidate=1)
        self.assertEqual(len(related), 8)

    def test_syndicated_identity_survives_and_unverified_drafts_excluded(self):
        slug = "major-transmission-project-permitting-agreement-for-united-states-power-grid"
        rows = [self.row(1, "https://one.example/" + slug), self.row(2, evidence="unverified_outbox")]
        related = shortlist_related([{"url": "https://two.example/" + slug, "title": "Unrelated translated wording"}], rows, {}, 0)
        self.assertEqual([row["id"] for row in related], [rows[0]["id"]])

    def test_novelty_keeps_all_complete_bodies_and_exact_identity(self):
        rows = [dict(self.row(i), urls=[f"https://example.com/{i}"], locations=["local/path"], similarity=.4) for i in range(20)]
        report = {"message_sha256": "bound-sha", "history_count": 230, "matches": rows}
        rendered = {"message_text": "full new draft", "novelty": {"new_facts": ["material new fact"], "comparisons": []}, "industrial_signal": {"large": "repeated object"}}
        before = copy.deepcopy((rendered, report))
        compact = compact_novelty_payload(rendered, report)
        self.assertEqual([row["message_text"] for row in compact["guard"]["matches"]], [row["message_text"] for row in rows])
        self.assertEqual(compact["guard"]["message_sha256"], "bound-sha")
        self.assertNotIn("locations", compact["guard"]["matches"][0])
        self.assertEqual((rendered, report), before)


if __name__ == "__main__":
    unittest.main()
