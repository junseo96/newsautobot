"""Regression checks for the explicitly requested company screening scope."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import collector
import gmail_scan

HERE = Path(__file__).resolve().parent
CFG = json.loads((HERE / "sources.json").read_text(encoding="utf-8"))


class CompanyScopeTests(unittest.TestCase):
    def test_named_us_companies_have_individual_sec_routes(self):
        expected = {"GEV": 1996810, "FPS": 2080126, "PWR": 1050915,
                    "BE": 1664703, "FLNC": 1868941, "ETN": 1551182,
                    "VRT": 1674101, "NEE": 753308, "DUK": 1326160,
                    "AEP": 4904, "D": 715957, "PCG": 1004980, "XEL": 72903}
        sources = {s["name"]: s for s in CFG["sources"]}
        for ticker, cik in expected.items():
            with self.subTest(ticker=ticker):
                self.assertIn(ticker, CFG["sec_watchlist"])
                src = sources[f"SEC {ticker} Company Filings"]
                self.assertEqual(int(parse_qs(urlsplit(src["url"]).query)["CIK"][0]), cik)
                self.assertTrue(src["sec_watch"] and src["must_review"] and src["primary"])
                self.assertEqual(src["include_terms"], CFG["sec_forms"])

    def test_siemens_entities_remain_distinct(self):
        sources = {s["name"]: s for s in CFG["sources"]}
        self.assertIn("Siemens Energy Press Releases", sources)
        self.assertIn("Siemens AG Press Releases", sources)
        self.assertNotEqual(sources["Siemens Energy Press Releases"]["url"],
                            sources["Siemens AG Press Releases"]["url"])

    def test_company_aliases_do_not_include_ambiguous_short_tickers(self):
        aliases = CFG["keyword_groups"]["company_watchlist"]
        for term in ("BE", "D", "FPS", "SIE"):
            self.assertNotIn(term, aliases)
        for term in ("포전트", "포젠트", "Forgent Power Solutions", "PG&E", "넥스테라"):
            self.assertIn(term, aliases)

    def test_company_name_alone_does_not_make_stock_news_important(self):
        score, _ = collector.score_item({"title": "Eaton share price and analyst target update",
                                        "summary": "", "priority": 2}, CFG)
        self.assertLess(score, CFG["brief_score_threshold"])

    def test_company_industrial_fact_kept_despite_price_mention(self):
        score, _ = collector.score_item({"title": "Forgent share price rises after transformer factory expansion contract",
                                        "summary": "New production capacity and backlog", "priority": 1}, CFG)
        self.assertGreaterEqual(score, CFG["realtime_score_threshold"])

    def test_v11_continuous_schedule_and_historical_policy_compatibility(self):
        settings = json.loads((HERE / "runtime-v11.json").read_text(encoding="utf-8"))
        self.assertEqual(settings["version"], 11)
        self.assertEqual(settings["operation"], "continuous_incremental")
        self.assertEqual(CFG["poll_interval_minutes"] * 60, settings["collection_interval_seconds"])
        self.assertEqual(CFG["active_window_kst"], {"start": "00:00", "end": "23:59"})
        self.assertEqual(CFG["morning_brief_kst"], "06:00")
        self.assertEqual(CFG["selection_policy_version"], 8)
        self.assertEqual(CFG["revalidation_scope"], "all_previous_policy_reviews")

    def test_smp_and_tariff_drivers_are_core_screening_topics(self):
        for title in ("SMP 계통한계가격 변화", "전기요금 연료비조정단가 검토",
                      "환율 상승으로 구입전력비 증가", "Utility rate case fuel adjustment"):
            with self.subTest(title=title):
                _, reasons = collector.score_item({"title": title, "priority": 1}, CFG)
                self.assertTrue(any(r.startswith("grid_market:") for r in reasons))

    def test_major_company_early_stage_research_is_recognized(self):
        for title in ("ABB research report on hybrid AC/DC power distribution",
                      "NVIDIA 800V DC pilot roadmap", "효성중공업 변압기 연구 실증 보고서"):
            with self.subTest(title=title):
                _, reasons = collector.score_item({"title": title, "priority": 1}, CFG)
                self.assertTrue(any(r.startswith("company_watchlist:") for r in reasons))
                self.assertTrue(any(r.startswith("industrial_event:") for r in reasons))
                self.assertTrue(any(r.startswith(("grid_market:", "equipment:")) for r in reasons))

    def test_generic_fx_news_stays_outside_core_scope(self):
        score, reasons = collector.score_item({"title": "환율 상승 전망", "priority": 1}, CFG)
        self.assertEqual(score, 0)
        self.assertIn("매크로·가격 단독", reasons)

    def test_registered_source_names_and_urls_are_unique(self):
        for field in ("name", "url"):
            values = [s[field] for s in CFG["sources"]]
            self.assertEqual(len(values), len(set(values)))

    def test_new_press_feeds_are_official_review_candidates(self):
        names = {f"{prefix} Press Releases" for prefix in (
            "Forgent Power Solutions", "Quanta Services", "Bloom Energy", "Siemens AG", "PG&E")}
        names.add("NextEra Energy News Releases")
        selected = [s for s in CFG["sources"] if s["name"] in names]
        self.assertEqual(len(selected), 6)
        for src in selected:
            self.assertEqual(src["kind"], "rss")
            self.assertTrue(src["primary"] and src["must_review"])
            self.assertFalse(src.get("discovery", False))

    def test_cross_host_article_links_are_opt_in_and_exact(self):
        source = {"name": "Fluence", "url": "https://fluenceenergy.com/about/media-room/",
                  "include_path": "/news-releases/news-release-details/"}
        path = "/news-releases/news-release-details/new-project"
        markup = (f'<a href="https://ir.fluenceenergy.com{path}">New battery storage construction project</a>'
                  f'<a href="https://ir.fluenceenergy.com.evil.test{path}">Untrusted outside press release</a>'
                  '<a href="https://ir.fluenceenergy.com/shareholder-services">Investor subscription navigation</a>')
        self.assertEqual(collector.parse_html(markup.encode(), source), [])
        source["allowed_hosts"] = ["ir.fluenceenergy.com"]
        items = collector.parse_html(markup.encode(), source)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["url"], "https://ir.fluenceenergy.com" + path)
        self.assertIsNone(items[0]["published_at"])

    def test_same_host_default_still_works(self):
        source = {"name": "Xcel", "url": "https://newsroom.xcelenergy.com/news", "include_path": "/news/"}
        markup = '<a href="/news/new-transmission-line">September 8, 2026 New transmission line</a>'
        self.assertEqual(len(collector.parse_html(markup.encode(), source)), 1)

    def test_gap_discovery_sources_are_not_marked_primary(self):
        names = {"Google Discovery AEP Official Releases", "Google Discovery Eaton Official Releases"}
        selected = [s for s in CFG["sources"] if s["name"] in names]
        self.assertEqual(len(selected), 2)
        for src in selected:
            self.assertTrue(src["discovery"] and src["must_review"])
            self.assertFalse(src["primary"])
            self.assertNotIn("when", parse_qs(urlsplit(src["url"]).query)["q"][0])

    def test_core_grid_oem_order_discovery_has_dedicated_routes(self):
        sources = {s["name"]: s for s in CFG["sources"]}
        routes = {
            "Google Discovery GE Vernova Orders": "GE Vernova",
            "Google Discovery Siemens Energy Orders": "Siemens Energy",
            "Google Discovery Hitachi Energy Orders": "Hitachi Energy",
            "Google Discovery Eaton Orders": "Eaton",
            "Google Discovery Schneider Electric Orders": "Schneider Electric",
            "Google Discovery ABB Grid Orders": "ABB",
        }
        for name, company in routes.items():
            with self.subTest(company=company):
                source = sources[name]
                query = parse_qs(urlsplit(source["url"]).query)["q"][0]
                self.assertIn(company, query)
                for event in ("order", "award", "contract", "agreement", "framework",
                              "supply", "deal", "backlog", "factory", "expansion", "commissioning"):
                    self.assertIn(event, query)
                self.assertTrue(source["must_review"] and source["discovery"])
                self.assertFalse(source["primary"])

        secondary = sources["Google Discovery Secondary Grid OEM Orders"]
        query = parse_qs(urlsplit(secondary["url"]).query)["q"][0]
        for company in ("Vertiv", "nVent", "Hubbell", "Powell Industries", "TMEIC", "Mitsubishi Electric"):
            self.assertIn(company, query)

    def test_core_grid_oems_have_official_release_fallback(self):
        sources = {s["name"]: s for s in CFG["sources"]}
        routes = {
            "Google Discovery Hitachi Energy Official Releases": "hitachienergy.com",
            "Google Discovery Schneider Electric Official Releases": "se.com",
            "Google Discovery ABB Official Releases": "new.abb.com",
            "Google Discovery Eaton Official Releases": "eaton.com",
        }
        for name, domain in routes.items():
            with self.subTest(domain=domain):
                fallback = sources[name]
                query = parse_qs(urlsplit(fallback["url"]).query)["q"][0]
                self.assertIn(domain, query)
                self.assertTrue(fallback["must_review"] and fallback["discovery"])
                self.assertFalse(fallback["primary"])

    def test_xcel_has_both_newsroom_and_ir_paths(self):
        sources = {s["name"]: s for s in CFG["sources"]}
        self.assertEqual(sources["Xcel Energy Newsroom"]["include_path"], "/news/")
        self.assertEqual(sources["Xcel Energy Press Releases"]["kind"], "rss")
        self.assertIn("엑셀에너지", CFG["keyword_groups"]["company_watchlist"])

    def test_xcel_is_included_without_gmail_sender_or_label_restriction(self):
        protocol = (HERE / "PROTOCOL.md").read_text(encoding="utf-8")
        # V11 delegates Gmail ingestion and compact policy to dedicated workers;
        # the retained semantic guarantees are the actual unrestricted query
        # and Xcel in the policy the review worker reads.
        settings = json.loads((HERE / "runtime-v12.json").read_text(encoding="utf-8"))
        self.assertIn(settings["policy_file"], protocol)
        # Test the actual query, rather than requiring one Korean phrasing.
        with tempfile.TemporaryDirectory() as directory, patch.object(gmail_scan, 'processed_ids', return_value=set()):
            query = gmail_scan.begin(Path(directory), now=1000000, compact=True)['query']
        for restriction in ('label:', 'from:', 'is:unread', 'category:', 'in:inbox'):
            self.assertNotIn(restriction, query)
        policy = (HERE / settings["policy_file"]).read_text(encoding="utf-8")
        self.assertIn("Xcel", policy)
        self.assertNotIn('from:xcelenergy.com', protocol)

    def test_fluence_only_allows_verified_official_article_host(self):
        source = next(s for s in CFG["sources"] if s["name"] == "Fluence Official Media Room")
        self.assertEqual(source["allowed_hosts"], ["ir.fluenceenergy.com"])
        self.assertEqual(source["include_path"], "/news-releases/news-release-details/")

    def test_retired_recovery_format_does_not_remove_receipt_recovery(self):
        protocol = (HERE / "PROTOCOL.md").read_text(encoding="utf-8")
        self.assertRegex(protocol, r"복구[^\n]*묶음[^\n]*금지")
        # Publication still consolidates recovery into Publish-Brief; its tests
        # prove complete-receipt recovery without a second Telegram send.
        publisher = (HERE / "Publish-Brief.ps1").read_text(encoding="utf-8")
        self.assertIn('RecoverDeliveries', publisher)
        self.assertIn('Ack-Collector.ps1', publisher)
        settings = json.loads((HERE / 'runtime-v12.json').read_text(encoding='utf-8'))
        self.assertEqual(settings['standard_brief_times_kst'], ['06:00','10:00','14:00','18:00'])
        self.assertTrue(settings['urgent_delivery_24h'])
        self.assertEqual(settings['delivery_mode'], 'important_realtime_standard_scheduled_briefs')
        self.assertIn('ready_day', protocol)


if __name__ == "__main__":
    unittest.main()
