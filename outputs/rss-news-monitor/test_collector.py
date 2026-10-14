import importlib.util
import copy
import json
import sqlite3
import tempfile
import unittest
from argparse import Namespace
from unittest import mock
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("collector", HERE / "collector.py")
COLLECTOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(COLLECTOR)
CONFIG = json.loads((HERE / "sources.json").read_text(encoding="utf-8"))


def scored(title, summary="", primary=False, sec_watch=False):
    return COLLECTOR.score_item({
        "title": title,
        "summary": summary,
        "priority": 1,
        "primary": primary,
        "sec_watch": sec_watch,
    }, CONFIG)[0]


class SourceParserV11Tests(unittest.TestCase):
    def test_kpx_listing_badge_and_views_are_not_article_title_but_date_is_preserved(self):
        source={"name":"KPX","url":"https://new.kpx.or.kr/gallery.es?bid=0022","kind":"html","primary":True}
        url="https://new.kpx.or.kr/gallery.es?act=view&list_no=220"
        headline="[보도자료] 전력거래소, 추석 연휴 안정적 전력공급에 총력"
        for label in (f"새글 {headline} 작성일 2026/09/28 조회수 33",f"{headline} 작성일 2026/09/28 조회수 65",f"새글 {headline} 작성일: 2026/09/28 조회수: 1,072"):
            with self.subTest(label=label):
                article=COLLECTOR.item(source,url,label)
                self.assertEqual(article["title"],headline)
                self.assertEqual(COLLECTOR.iso(article["published_at"]),"2026-09-28T00:00:00+00:00")
                self.assertEqual(article["publication_precision"],"date")

    def test_kpx_metadata_cleanup_does_not_reopen_historical_collector_review(self):
        source={"name":"KPX","url":"https://new.kpx.or.kr/gallery.es","primary":True}
        url="https://new.kpx.or.kr/gallery.es?act=view&list_no=220"
        old={"title":"새글 [보도자료] 추석 연휴 안정적 전력공급에 총력 작성일 2026/09/28 조회수 33","summary":"","published_at":"2026-09-28T00:00:00+00:00"}
        incoming=COLLECTOR.item(source,url,"[보도자료] 추석 연휴 안정적 전력공급에 총력 작성일 2026/09/28 조회수 65")
        self.assertFalse(COLLECTOR.material_content_change(old,incoming,source))
        self.assertTrue(COLLECTOR.material_content_change(old,dict(incoming,title="[보도자료] 추석 연휴 전력공급 차질 발생"),source))
        self.assertTrue(COLLECTOR.material_content_change(old,dict(incoming,summary="접속 심사 중단 후 재개 결정"),source))
        self.assertTrue(COLLECTOR.material_content_change(old,dict(incoming,published_at=COLLECTOR.parse_date("2026-09-29T00:00:00Z")),source))

    def test_kpx_cleanup_requires_official_host_notice_route_and_complete_suffix(self):
        label="새글 [보도자료] 시장공지 작성일 2026/09/28 조회수 33"
        urls=("https://example.com/gallery.es?act=view&list_no=220",
              "https://new.kpx.or.kr.evil.example/gallery.es?act=view&list_no=220",
              "https://new.kpx.or.kr/gallery.es?bid=0022",
              "https://new.kpx.or.kr/news/article")
        for url in urls:
            self.assertEqual(COLLECTOR.source_normalization.article_title(url,label),label)
        url="https://new.kpx.or.kr/gallery.es?act=view&list_no=220"
        actual_headline="조회수 33 증가 원인과 공시 작성일 변경의 산업 영향"
        self.assertEqual(COLLECTOR.source_normalization.article_title(url,actual_headline),actual_headline)

    def test_google_publisher_rename_does_not_change_article_content(self):
        source={"name":"Google Discovery","url":"https://news.google.com/rss/search?q=grid","kind":"rss","discovery":True}
        template='<rss><channel><item><title>Utility signs 500 MW contract - {publisher}</title><link>https://news.google.com/rss/articles/same</link><description><![CDATA[<a href="https://news.google.com/rss/articles/same">Utility signs 500 MW contract</a>&nbsp;&nbsp;<font>{publisher}</font>]]></description><source>{publisher}</source><pubDate>Mon, 28 Sep 2026 03:00:00 GMT</pubDate></item></channel></rss>'
        rows=[COLLECTOR.parse_feed(template.format(publisher=name).encode(),source)[0] for name in ("Publisher News","publisher.example")]
        self.assertEqual(rows[0],rows[1])
        self.assertEqual(rows[0]["title"],"Utility signs 500 MW contract")
        self.assertEqual(rows[0]["summary"],"Utility signs 500 MW contract")

    def test_google_retains_actual_additional_summary_facts(self):
        source={"name":"Google","url":"https://news.google.com/rss/search?q=grid","kind":"rss"}
        markup='<rss><channel><item><title>Grid upgrade - News</title><link>https://example.com/story</link><description><![CDATA[<a href="https://example.com/story">Grid upgrade</a><p>The approved project adds 700 MW.</p>]]></description><source>News</source></item></channel></rss>'
        self.assertIn("700 MW",COLLECTOR.parse_feed(markup.encode(),source)[0]["summary"])

    def test_empty_rss_is_gap_but_valid_discovery_and_filtered_feeds_are_explicit(self):
        source={"name":"Official","url":"https://example.com/feed","kind":"rss"}
        response=mock.MagicMock()
        with mock.patch.object(COLLECTOR.urllib.request,"urlopen",return_value=response):
            for body in (b'<html><body>Login</body></html>',b'<rss/>',b'<rss><channel/></rss>',b'<rss><channel><item><title>No URL</title></item></channel></rss>'):
                response.__enter__.return_value.read.return_value=body
                self.assertFalse(COLLECTOR.fetch_once(source)["ok"])
            response.__enter__.return_value.read.return_value=b'<rss><channel/></rss>'
            result=COLLECTOR.fetch_once(dict(source,discovery=True))
            self.assertTrue(result["ok"])
            self.assertEqual(result["coverage_state"],"discovery_no_results")
            response.__enter__.return_value.read.return_value=b'<rss><channel><item><title>Unrelated filing</title><link>https://example.com/filing</link></item></channel></rss>'
            result=COLLECTOR.fetch_once(dict(source,include_terms=["8-K"]))
            self.assertTrue(result["ok"])
            self.assertEqual(result["coverage_state"],"filtered_no_matches")
            self.assertEqual(result["raw_item_count"],1)

    def test_configured_sources_reject_navigation_links(self):
        by_name={s["name"]:s for s in CONFIG["sources"]}
        cases=(
            ("T&D World",'<a href="/overhead-transmission">Overhead Transmission Category</a><a href="/utility-business/news/55402954/eaton-expands">Eaton expands factory capacity</a>'),
            ("CAISO News Releases",'<a href="/systems-applications">Systems and applications</a><a href="/about/news/topics/wem">Western Energy Markets</a><a href="/about/news/news-releases/market-starts">Extended day-ahead market starts</a>'),
            ("Siemens Energy Press Releases",'<a href="/global/en/home/products-services.html">Products and Services</a><a href="/global/en/home/press-releases/grid-contract.html">Siemens Energy signs grid contract</a>'),
        )
        for name,markup in cases:
            with self.subTest(source=name):self.assertEqual(len(COLLECTOR.parse_html(markup.encode(),by_name[name])),1)

    def test_hitachi_public_json_is_dated_and_does_not_import_private_or_foreign_links(self):
        source=next(s for s in CONFIG["sources"] if s["name"]=="Hitachi Energy Press Releases")
        row={"title":"Hitachi Energy and utility sign transformer supply agreement","url":"https://www.hitachienergy.com/news-and-events/press-releases/2026/09/grid-contract","date":"24.09.2026 15:00"}
        payload={"items":[row,row,dict(row,url="https://other.example/press-releases/x"),dict(row,webItemInsideIntranetContext=True),{"title":"No article URL"}]}
        items=COLLECTOR.parse_hitachi_news(json.dumps(payload).encode(),source)
        self.assertEqual(len(items),1)
        self.assertEqual(COLLECTOR.iso(items[0]["published_at"]),"2026-09-24T00:00:00+00:00")
        self.assertEqual(items[0]["publication_precision"],"date")
        with self.assertRaisesRegex(ValueError,"items list"):COLLECTOR.parse_hitachi_news(b'{"error":"maintenance"}',source)

    def test_date_only_metadata_is_not_marked_as_exact(self):
        source={"name":"Official","url":"https://example.com/feed","kind":"rss"}
        rows=COLLECTOR.parse_feed(b'<feed><entry><title>Grid approval announced</title><link href="https://example.com/news"/><published>2026-09-28</published></entry></feed>',source)
        self.assertEqual(rows[0]["publication_precision"],"date")
        self.assertEqual(COLLECTOR.item(source,"https://example.com/news","September 28, 2026 Grid approval")["publication_precision"],"date")
        self.assertEqual(COLLECTOR.item(source,"https://example.com/news","Grid approval",published=COLLECTOR.now_utc())["publication_precision"],"exact")

    def test_tdworld_exact_original_timestamp_not_date_only_label(self):
        page=(b'<meta name="date-pub" content="2026-09-23">'
              b'<script>{&quot;content&quot;:{&quot;published&quot;:&quot;2026-09-23T15:28:33.000Z&quot;}}</script>')
        self.assertEqual(COLLECTOR.iso(COLLECTOR.tdworld_publication_date(page)),"2026-09-23T15:28:33+00:00")
        self.assertIsNone(COLLECTOR.tdworld_publication_date(b'<meta name="date-pub" content="2026-09-23">'))

    def test_tdworld_opens_only_new_undated_article_urls(self):
        connection=sqlite3.connect(':memory:')
        self.addCleanup(connection.close)
        connection.row_factory=sqlite3.Row
        connection.execute('CREATE TABLE articles(url TEXT PRIMARY KEY,first_seen_at TEXT,published_at TEXT)')
        connection.execute('INSERT INTO articles(url,first_seen_at) VALUES(?,?)',('https://www.tdworld.com/known','2026-09-01T00:00:00+00:00'))
        source={'name':'T&D World','url':'https://www.tdworld.com/','kind':'html'}
        rows=[COLLECTOR.item(source,'https://www.tdworld.com/known','Known utility article'),
              COLLECTOR.item(source,'https://www.tdworld.com/new','New utility article')]
        results=[{'source':source,'ok':True,'items':rows}]
        exact=COLLECTOR.parse_date('2026-09-24T10:00:00Z')
        with mock.patch.object(COLLECTOR,'fetch_tdworld_publication',return_value=(exact,None)) as fetch:
            COLLECTOR.enrich_tdworld_new_articles(results,connection)
        fetch.assert_called_once_with('https://www.tdworld.com/new')
        self.assertIsNone(rows[0]['published_at'])
        self.assertEqual(rows[1]['published_at'],exact)
        self.assertEqual(results[0]['date_resolution']['exact_dates_found'],1)

    def test_tdworld_recent_date_failure_retries_with_backoff(self):
        connection=sqlite3.connect(':memory:')
        self.addCleanup(connection.close)
        connection.row_factory=sqlite3.Row
        connection.execute('CREATE TABLE articles(url TEXT PRIMARY KEY,first_seen_at TEXT,published_at TEXT)')
        source={'name':'T&D World','url':'https://www.tdworld.com/','kind':'html'}
        url='https://www.tdworld.com/recent'
        connection.execute('INSERT INTO articles(url,first_seen_at) VALUES(?,?)',(url,COLLECTOR.iso(COLLECTOR.now_utc())))
        result={'source':source,'ok':True,'items':[COLLECTOR.item(source,url,'New utility article')]}
        with mock.patch.object(COLLECTOR,'fetch_tdworld_publication',return_value=(None,'HTTP 503')) as fetch:
            COLLECTOR.enrich_tdworld_new_articles([result],connection)
            COLLECTOR.enrich_tdworld_new_articles([result],connection)
        fetch.assert_called_once_with(url)
        connection.execute('UPDATE source_date_checks SET checked_at=? WHERE url=?',
                           (COLLECTOR.iso(COLLECTOR.now_utc()-COLLECTOR.dt.timedelta(minutes=11)),url))
        exact=COLLECTOR.now_utc()
        with mock.patch.object(COLLECTOR,'fetch_tdworld_publication',return_value=(exact,None)) as fetch:
            COLLECTOR.enrich_tdworld_new_articles([result],connection)
        fetch.assert_called_once_with(url)
        self.assertEqual(result['items'][0]['published_at'],exact)

    def test_all_seven_iso_keyword_sources_are_separate_from_direct_coverage(self):
        sources = [s for s in CONFIG["sources"] if s.get("group") == "ISO_RTO_discovery"]
        self.assertEqual({s["organization"] for s in sources}, {"PJM", "MISO", "SPP", "ERCOT", "CAISO", "NYISO", "ISO-NE"})
        self.assertEqual(len(sources), 7)
        self.assertTrue(all(s["discovery"] and not s["primary"] and s["must_review"] for s in sources))
        by_name = {s["name"]: s for s in CONFIG["sources"]}
        self.assertEqual(by_name["NYISO Press Releases"]["url"], "https://www.nyiso.com/press")
        self.assertEqual(by_name["MISO Media Center"]["kind"], "miso_news_json")

    def test_miso_public_api_extracts_dated_articles_not_media_center_navigation(self):
        source = {"name": "MISO", "url": "https://www.misoenergy.org/api/News/GetNews", "kind": "miso_news_json", "primary": True}
        article = {"name": "MISO advances 7.3 GW of new generation", "linkURL": "/link/article.aspx", "releaseDate": "2026-09-08T13:00:00+09:00", "subheader": "15 proposed projects", "text": "<p>In service by 2029</p>"}
        payload = {"articles": [article, article, dict(article, linkURL="/link/draft.aspx", isPendingPublish=True), dict(article, linkURL="https://other.example/article"), {"name": "Corporate Fact Sheet"}]}
        rows = COLLECTOR.parse_miso_news(json.dumps(payload).encode(), source)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["url"], "https://www.misoenergy.org/link/article.aspx")
        self.assertEqual(rows[0]["title"], article["name"])
        self.assertEqual(COLLECTOR.iso(rows[0]["published_at"]), "2026-09-08T04:00:00+00:00")
        self.assertEqual(rows[0]["summary"], "15 proposed projects In service by 2029")
        with self.assertRaisesRegex(ValueError, "articles list"):
            COLLECTOR.parse_miso_news(b'{"error":"maintenance"}', source)

    def test_miso_api_dispatch_and_empty_response_remains_a_gap(self):
        source = {"name": "MISO", "url": "https://www.misoenergy.org/api/News/GetNews", "kind": "miso_news_json", "accept": "application/json", "critical": True}
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b'{"articles":[]}'
        with mock.patch.object(COLLECTOR.urllib.request, "urlopen", return_value=response) as request:
            result = COLLECTOR.fetch(source)
        self.assertFalse(result["ok"])
        self.assertIn("No article links parsed", result["error"])
        self.assertEqual(request.call_args.args[0].get_header("Accept"), "application/json")

    def test_html_chooses_headline_once_for_each_url_in_either_card_order(self):
        source = {"name": "T&D", "url": "https://example.com/", "kind": "html"}
        photo = '<a href="/article?utm_source=photo"><img src="photo.jpg"><span>Electrical transformer infrastructure at a 33-MW data center | Credit: Manufacturer</span></a>'
        title = '<a href="/article" class="title-wrapper"><h2>Hammond Power Solutions expands U.S. transformer capacity</h2></a>'
        for markup in (photo + title, title + photo):
            with self.subTest(markup=markup):
                rows = COLLECTOR.parse_html(markup.encode(), source)
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["title"], "Hammond Power Solutions expands U.S. transformer capacity")
        # A heading surrounding the anchor is also a semantic headline.
        outer_heading = '<h3><a href="/article">Hammond Power Solutions expands U.S. transformer capacity</a></h3>'
        self.assertEqual(COLLECTOR.parse_html((photo + outer_heading).encode(), source)[0]["title"], rows[0]["title"])

    def test_html_preserves_dated_label_and_source_path_filters(self):
        source = {"name": "NYISO", "url": "https://www.nyiso.com/press", "kind": "html", "include_path": "/-/"}
        markup = '<a href="/-/grid-update"><h4>Grid investment plan</h4><div>July 23, 2026 | New transmission assessment</div></a><a href="/about">Corporate background and contact information</a>'
        rows = COLLECTOR.parse_html(markup.encode(), source)
        self.assertEqual(len(rows), 1)
        self.assertIn("July 23, 2026", rows[0]["title"])
        self.assertEqual(rows[0]["published_at"].date().isoformat(), "2026-07-23")


class ImportanceScoringTests(unittest.TestCase):
    def test_date_parser_respects_explicit_offsets_and_only_defaults_naive_dates(self):
        cases = [
            ("Fri, 11 Sep 2026 08:57:36 +09:00", COLLECTOR.UTC, "2026-09-10T23:57:36+00:00"),
            ("Fri, 11 Sep 2026 08:57:36 +0900", COLLECTOR.UTC, "2026-09-10T23:57:36+00:00"),
            ("Fri, 11 Sep 2026 08:30:00 -05:30", COLLECTOR.UTC, "2026-09-11T14:00:00+00:00"),
            ("2026-09-11T08:17:22+09:00", COLLECTOR.UTC, "2026-09-10T23:17:22+00:00"),
            ("2026-09-11T08:17:22Z", "+09:00", "2026-09-11T08:17:22+00:00"),
            ("2026-09-11 08:17:22", "+09:00", "2026-09-10T23:17:22+00:00"),
            ("2026-09-11 08:17:22", COLLECTOR.UTC, "2026-09-11T08:17:22+00:00"),
        ]
        for value, zone, expected in cases:
            with self.subTest(value=value, zone=zone):
                self.assertEqual(COLLECTOR.iso(COLLECTOR.parse_date(value, zone)), expected)

    def test_date_embedded_in_press_release_title_is_parsed(self):
        parsed = COLLECTOR.parse_date_from_text("Press Release September 03, 2026 Major grid contract")
        self.assertEqual(parsed.date().isoformat(), "2026-09-03")

    def test_large_nuclear_build_is_realtime(self):
        self.assertGreaterEqual(scored("정부, 대형원전 8기 건설 계획 승인", primary=True), 50)

    def test_us_investment_gas_power_is_realtime(self):
        self.assertGreaterEqual(scored("대미투자 연계 10GW 가스발전 건설 계약"), 50)

    def test_grid_equipment_order_is_realtime(self):
        self.assertGreaterEqual(scored("765kV 변압기 2조원 공급계약 수주"), 50)

    def test_macro_only_is_discarded(self):
        self.assertLess(scored("기준금리와 환율 전망, 주가 변동 확대"), 25)

    def test_ai_compute_without_power_is_not_realtime(self):
        self.assertLess(scored("Hyperscaler signs $1bn AI compute contract at data center"), 50)

    def test_watched_sec_filing_reaches_review_lane(self):
        self.assertGreaterEqual(scored("8-K - VERTIV HOLDINGS CO", primary=True, sec_watch=True), 25)

    def test_ess_does_not_match_business_or_professors(self):
        self.assertFalse(COLLECTOR.term_matches("business professors discuss policy", "ess"))

    def test_ess_matches_standalone_bess(self):
        self.assertTrue(COLLECTOR.term_matches("850 mw bess commissioning", "bess"))

    def test_ai_power_demand_reaches_review_lane(self):
        self.assertGreaterEqual(scored("US electricity demand hits record as AI data center use surges"), 25)


class CandidateStateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "state.db"
        con = sqlite3.connect(self.db)
        COLLECTOR.ensure_db(con)
        base = (
            "hash", "normalized", "title", "summary", "source", "source-url",
            "2026-09-10T00:00:00+00:00", "2026-09-10T00:00:00+00:00",
            "2026-09-10T00:00:00+00:00", 35, "[]", "pending",
        )
        for url in ("https://example.com/send", "https://example.com/defer", "https://example.com/drop", "https://example.com/untouched"):
            con.execute("INSERT INTO articles(url,url_hash,normalized_title,title,summary,source,source_url,published_at,first_seen_at,last_seen_at,score,score_reasons,status) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", (url, *base))
        con.commit(); con.close()

    def tearDown(self):
        self.temp.cleanup()

    def test_acknowledge_updates_only_explicit_urls(self):
        batch = Path(self.temp.name) / "batch.json"
        message = "New 2GW grid approval"
        import hashlib
        receipt = Path(self.temp.name) / "receipt.json"
        receipt.write_text(json.dumps({
            "status": "complete", "message_file": None, "message_text": message,
            "message_sha256": hashlib.sha256(message.encode("utf-8")).hexdigest(),
            "article_urls": ["https://example.com/send"],
            "sent_at": COLLECTOR.iso(COLLECTOR.now_utc()), "telegram_message_ids": [501],
        }), encoding="utf-8")
        batch.write_text(json.dumps({
            "run_id": "test-run", "policy_version": CONFIG["selection_policy_version"],
            "generated_at_kst": COLLECTOR.iso(COLLECTOR.now_utc() - COLLECTOR.dt.timedelta(minutes=1)),
            "candidates": [{"url": "https://example.com/" + name} for name in ("send", "drop", "defer", "untouched")],
        }), encoding="utf-8")
        decisions = Path(self.temp.name) / "decisions.json"
        decisions.write_text(json.dumps({"run_id": "test-run", "decisions": [
            {"url": "https://example.com/send", "status": "delivered", "reason": "New capacity approval", "receipt_file": str(receipt)},
            {"url": "https://example.com/drop", "status": "reviewed", "reason": "No new industrial information"},
            {"url": "https://example.com/defer", "status": "brief", "reason": "Research appropriate for morning"},
        ]}), encoding="utf-8")
        args = Namespace(
            config=HERE / "sources.json", db=self.db, batch=batch, decision_file=decisions,
            delivered_url=[], reviewed_url=[], brief_url=[],
        )
        COLLECTOR.acknowledge(args)
        con = sqlite3.connect(self.db)
        states = dict(con.execute("SELECT url,status FROM articles"))
        con.close()
        self.assertEqual(states["https://example.com/send"], "delivered")
        self.assertEqual(states["https://example.com/defer"], "brief")
        self.assertEqual(states["https://example.com/drop"], "reviewed")
        self.assertEqual(states["https://example.com/untouched"], "pending")

    def test_brief_candidate_hidden_realtime_and_restored_morning(self):
        config_path = Path(self.temp.name) / "config.json"
        output_path = Path(self.temp.name) / "batch.json"
        cfg = copy.deepcopy(CONFIG)
        cfg["sources"] = [{"name": "Synthetic", "url": "https://example.com/feed", "kind": "rss", "priority": 1}]
        config_path.write_text(json.dumps(cfg), encoding="utf-8")
        source = cfg["sources"][0]
        article = COLLECTOR.item(source, "https://example.com/new", "Grid investment announced", "Transmission expansion", COLLECTOR.now_utc())
        result = {"source": source, "ok": True, "items": [article], "error": None, "started_at": COLLECTOR.iso(COLLECTOR.now_utc()), "finished_at": COLLECTOR.iso(COLLECTOR.now_utc())}
        args = Namespace(config=config_path, db=Path(self.temp.name) / "lane.db", output=output_path, lookback_hours=12, max_candidates=100, lane="realtime")
        with mock.patch.object(COLLECTOR, "fetch", return_value=result), mock.patch.object(COLLECTOR, "fetch_dart", return_value=None):
            COLLECTOR.collect(args)
            self.assertEqual(len(json.loads(output_path.read_text(encoding="utf-8"))["candidates"]), 1)
            COLLECTOR.acknowledge(Namespace(config=config_path, db=args.db, batch=output_path, delivered_url=[], reviewed_url=[], brief_url=["https://example.com/new"]))
            COLLECTOR.collect(args)
            self.assertEqual(len(json.loads(output_path.read_text(encoding="utf-8"))["candidates"]), 0)
            args.lane = "morning"
            COLLECTOR.collect(args)
            self.assertEqual(len(json.loads(output_path.read_text(encoding="utf-8"))["candidates"]), 1)

    def test_future_dated_article_waits_until_release_time(self):
        config_path = Path(self.temp.name) / "future-config.json"
        output_path = Path(self.temp.name) / "future-batch.json"
        cfg = copy.deepcopy(CONFIG)
        cfg["sources"] = [{"name": "Synthetic", "url": "https://example.com/feed", "kind": "rss", "priority": 1}]
        config_path.write_text(json.dumps(cfg), encoding="utf-8")
        source = cfg["sources"][0]
        published = COLLECTOR.now_utc() + COLLECTOR.dt.timedelta(hours=3)
        article = COLLECTOR.item(source, "https://example.com/scheduled", "Grid investment announced", "Transmission expansion", published)
        result = {"source": source, "ok": True, "items": [article], "error": None, "started_at": COLLECTOR.iso(COLLECTOR.now_utc()), "finished_at": COLLECTOR.iso(COLLECTOR.now_utc())}
        args = Namespace(config=config_path, db=Path(self.temp.name) / "future.db", output=output_path, lookback_hours=12, max_candidates=100, lane="realtime")
        with mock.patch.object(COLLECTOR, "fetch", return_value=result), mock.patch.object(COLLECTOR, "fetch_dart", return_value=None):
            COLLECTOR.collect(args)
        self.assertEqual(len(json.loads(output_path.read_text(encoding="utf-8"))["candidates"]), 0)

    def test_morning_revalidates_old_policy_review(self):
        config_path = Path(self.temp.name) / "audit-config.json"
        output_path = Path(self.temp.name) / "audit-batch.json"
        cfg = copy.deepcopy(CONFIG)
        cfg["selection_policy_version"] = 4
        cfg["revalidation_score_threshold"] = 70
        cfg["sources"] = [{"name": "Synthetic", "url": "https://example.com/feed", "kind": "rss", "priority": 1}]
        config_path.write_text(json.dumps(cfg), encoding="utf-8")
        con = sqlite3.connect(self.db)
        now = COLLECTOR.iso(COLLECTOR.now_utc())
        con.execute("UPDATE articles SET title='Major 765kV grid transformer contract', normalized_title='major grid transformer contract', score=90, published_at=?, status='reviewed', decision_policy_version=0 WHERE url='https://example.com/drop'", (now,))
        con.commit(); con.close()
        source = cfg["sources"][0]
        result = {"source": source, "ok": True, "items": [], "error": None, "started_at": now, "finished_at": now}
        args = Namespace(config=config_path, db=self.db, output=output_path, lookback_hours=12, max_candidates=100, lane="morning")
        with mock.patch.object(COLLECTOR, "fetch", return_value=result), mock.patch.object(COLLECTOR, "fetch_dart", return_value=None):
            COLLECTOR.collect(args)
        payload = json.loads(output_path.read_text(encoding="utf-8"))
        audited = next(x for x in payload["candidates"] if x["url"] == "https://example.com/drop")
        self.assertTrue(audited["policy_revalidation"])
        COLLECTOR.acknowledge(Namespace(config=config_path, db=self.db, batch=output_path, delivered_url=[], reviewed_url=[audited["url"]], brief_url=[]))
        con = sqlite3.connect(self.db)
        version = con.execute("SELECT decision_policy_version FROM articles WHERE url=?", (audited["url"],)).fetchone()[0]
        con.close()
        self.assertEqual(version, 4)


class ReliabilityRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.cfg = copy.deepcopy(CONFIG)
        self.cfg["sources"] = [{"name": "Synthetic", "url": "https://example.com/feed", "kind": "rss", "priority": 1}]
        self.args = Namespace(config=self.root / "config.json", db=self.root / "test.db", output=self.root / "page.json", lookback_hours=12, max_candidates=100, lane="realtime")

    def tearDown(self):
        self.temp.cleanup()

    def collect(self, articles=None):
        self.args.config.write_text(json.dumps(self.cfg), encoding="utf-8")
        def result(src):
            return {"source": src, "ok": True, "items": [x for x in (articles or []) if x["source"] == src["name"]], "error": None, "started_at": COLLECTOR.iso(COLLECTOR.now_utc()), "finished_at": COLLECTOR.iso(COLLECTOR.now_utc())}
        with mock.patch.object(COLLECTOR, "fetch", side_effect=result), mock.patch.object(COLLECTOR, "fetch_dart", return_value=None):
            COLLECTOR.collect(self.args)
        return json.loads(self.args.output.read_text(encoding="utf-8"))

    def article(self, path="new", title="765kV grid transformer contract", source=0, published=True, summary="Transmission construction"):
        return COLLECTOR.item(self.cfg["sources"][source], "https://example.com/" + path, title, summary, COLLECTOR.now_utc() if published else None)

    def test_date_only_dart_filing_discovered_in_afternoon_stays_current(self):
        now=COLLECTOR.dt.datetime(2026,10,1,6,0,tzinfo=COLLECTOR.UTC)  # 15:00 KST
        article=self.article(path="dart-contract",title="단일판매ㆍ공급계약체결")
        article["published_at"]=COLLECTOR.dt.datetime(2026,9,30,15,0,tzinfo=COLLECTOR.UTC)
        article["publication_precision"]="date"
        article["publication_calendar_date"]="2026-10-01"
        with mock.patch.object(COLLECTOR,"now_utc",return_value=now):
            page=self.collect([article])
        candidate=next(x for x in page["candidates"] if x["url"]==article["url"])
        self.assertEqual(candidate["published_at"],"2026-10-01")
        self.assertEqual(candidate["publication_precision"],"date")
        self.assertFalse(candidate["outside_lookback"])
        self.assertEqual(self.states()[article["url"]],"pending")

    def change(self, sql, values=()):
        con = sqlite3.connect(self.args.db)
        con.execute(sql, values)
        con.commit(); con.close()

    def states(self):
        con = sqlite3.connect(self.args.db)
        rows = dict(con.execute("SELECT url,status FROM articles"))
        con.close()
        return rows

    def test_fast_poll_fetches_only_selected_sources_but_retains_full_candidate_identity(self):
        self.cfg['sources']=[{'name':'Fast','url':'https://example.com/fast','kind':'rss','group':'industry_media'},
                             {'name':'Slow','url':'https://example.com/slow','kind':'rss','group':'US_utility'}]
        self.collect([self.article('slow',source=1)])
        self.args.fast_poll=True
        (self.root/'runtime-v11.json').write_text(json.dumps({'fast_poll_source_names':['Fast']}),encoding='utf-8')
        self.args.config.write_text(json.dumps(self.cfg),encoding='utf-8')
        now=COLLECTOR.iso(COLLECTOR.now_utc())
        def result(src):
            return {'source':src,'ok':True,'items':[], 'error':None,'started_at':now,'finished_at':now}
        with mock.patch.object(COLLECTOR,'fetch',side_effect=result) as fetch, mock.patch.object(COLLECTOR,'fetch_dart',return_value=None) as dart:
            COLLECTOR.collect(self.args)
        fetch.assert_called_once_with(self.cfg['sources'][0])
        dart.assert_called_once_with(self.cfg,self.args.db.parent/'v11'/'dart-corp-codes.json')
        snapshot=json.loads(Path(json.loads(self.args.output.read_text(encoding='utf-8'))['run_files']['snapshot']).read_text(encoding='utf-8'))
        self.assertEqual(snapshot['poll_scope'],'fast')
        self.assertEqual(snapshot['total_sources'],1)
        self.assertEqual(next(c for c in snapshot['candidates'] if c['source']=='Slow')['source_group'],'US_utility')

    def test_unreviewed_article_survives_lookback_and_refetch(self):
        article = self.article()
        self.collect([article])
        old = COLLECTOR.now_utc() - COLLECTOR.dt.timedelta(days=2)
        article["published_at"] = old
        self.change("UPDATE articles SET published_at=?,first_seen_at=?", (COLLECTOR.iso(old), COLLECTOR.iso(old)))
        payload = self.collect([article])
        self.assertEqual(self.states()[article["url"]], "pending")
        self.assertEqual(len(payload["candidates"]), 1)
        self.assertTrue(payload["candidates"][0]["outside_lookback"])

    def test_low_scoring_discovery_is_retained_not_reviewed(self):
        self.cfg["sources"][0]["discovery"] = True
        article = self.article(title="Unknown industrial development", summary="")
        first = self.collect([article])
        self.assertEqual(self.states()[article["url"]], "brief")
        self.assertEqual(len(first["candidates"]), 1)
        self.args.lane = "morning"
        payload = self.collect()
        self.assertEqual(payload["candidates"][0]["recommended_lane"], "brief")

    def test_same_title_different_urls_both_reach_review(self):
        payload = self.collect([self.article("one"), self.article("two")])
        self.assertEqual(len(payload["candidates"]), 2)

    def test_critical_article_has_review_priority_without_keyword_hit(self):
        self.cfg["sources"][0].update(critical=True, discovery=True, group="regulators")
        payload = self.collect([self.article(title="Notice number 2026-001", summary="")])
        self.assertTrue(payload["candidates"][0]["must_review"])
        self.assertEqual(payload["candidates"][0]["recommended_lane"], "realtime")
        self.assertEqual(payload["coverage_by_group"]["regulators"]["successful"], 1)

    def test_pagination_is_complete_stable_and_does_not_refetch(self):
        self.args.max_candidates = 3
        articles = [self.article(str(n)) for n in range(8)]
        page = self.collect(articles)
        self.assertTrue(page["pagination"]["has_more"])
        self.assertEqual(page["pagination"]["total_candidates"], 8)
        index = json.loads(Path(page["run_files"]["screening_index"]).read_text(encoding="utf-8"))
        self.assertEqual(len(index["candidates"]), 8)
        urls = [x["url"] for x in page["candidates"]]
        self.change("UPDATE articles SET status='reviewed' WHERE url=?", (urls[0],))
        for offset in (3, 6):
            args = Namespace(batch=Path(page["pagination"]["snapshot_path"]), db=self.args.db, offset=offset, max_candidates=3, output=self.root / f"page-{offset}.json")
            with mock.patch.object(COLLECTOR, "fetch") as fetch:
                COLLECTOR.export_batch(args)
                fetch.assert_not_called()
            exported = json.loads(args.output.read_text(encoding="utf-8"))
            urls.extend(x["url"] for x in exported["candidates"])
        self.assertEqual(set(urls), {x["url"] for x in articles})
        self.assertEqual(len(urls), 8)

    def test_source_diversity_in_small_first_page(self):
        self.args.max_candidates = 4
        self.cfg["sources"].append({"name": "Another", "url": "https://second.example/feed", "kind": "rss", "priority": 1})
        payload = self.collect([self.article(str(n)) for n in range(12)] + [self.article("second", source=1)])
        self.assertEqual({x["source"] for x in payload["candidates"]}, {"Synthetic", "Another"})

    def test_presented_candidates_do_not_starve_unseen_candidates(self):
        self.args.max_candidates = 2
        first = self.collect([self.article(str(n)) for n in range(6)])
        second = self.collect()
        self.assertFalse({x["url"] for x in first["candidates"]} & {x["url"] for x in second["candidates"]})

    def test_legacy_seen_urls_do_not_become_delivered(self):
        article = self.article()
        (self.root / "rss-news-monitor-state.json").write_text(json.dumps({"seen_urls": [article["url"]]}), encoding="utf-8")
        self.collect([article])
        self.assertEqual(self.states()[article["url"]], "pending")

    def test_same_url_changed_capacity_is_reviewed_again(self):
        article = self.article(title="Grid contract 200MW")
        self.collect([article])
        self.change("UPDATE articles SET status='delivered', delivered_at=?", (COLLECTOR.iso(COLLECTOR.now_utc()),))
        unchanged = self.collect([article])
        self.assertEqual(unchanged["candidates"], [])
        article["title"] = "Grid contract 400MW"
        changed = self.collect([article])
        self.assertEqual(changed["candidates"][0]["title"], "Grid contract 400MW")
        self.assertIsNotNone(changed["candidates"][0]["content_updated_at"])
        self.assertEqual(self.states()[article["url"]], "pending")

    def test_cosmetic_feed_rewrite_cannot_reopen_delivered_article(self):
        article = self.article(title="Grid contract 200MW", summary="Transmission construction")
        self.collect([article])
        self.change("UPDATE articles SET status='delivered', delivered_at=?", (COLLECTOR.iso(COLLECTOR.now_utc()),))
        cosmetic = dict(article, title="Latest: Grid contract (200 MW)", summary="Transmission construction — updated format")
        payload = self.collect([cosmetic])
        self.assertEqual(payload["candidates"], [])
        self.assertEqual(self.states()[article["url"]], "delivered")
        con = sqlite3.connect(self.args.db)
        updated = con.execute("SELECT content_updated_at FROM articles WHERE url=?", (article["url"],)).fetchone()[0]
        con.close()
        self.assertIsNone(updated)

    def test_html_photo_caption_cannot_reopen_decision_but_changed_headline_can(self):
        source = {"name": "T&D World", "url": "https://www.tdworld.com/", "kind": "html", "priority": 1}
        self.cfg["sources"] = [source]
        headline = "Santee Cooper Taps Google's Cloud AI Weather Predictive Modeling to Guide $10B Grid Expansion"
        for state in ("reviewed", "delivered"):
            path = "/smart-utility/news/55406701/" + state
            caption = f'<a href="{path}"><img src="photo.jpg"><span>Santee Cooper leadership touring its energy control center with Google Cloud executives. | Credit: Santee Cooper</span></a>'
            title_link = f'<a href="{path}" class="title-wrapper"><h2>{headline}</h2></a>'
            rows = COLLECTOR.parse_html((caption + title_link).encode(), source)
            self.collect(rows)
            self.change("UPDATE articles SET status=?,decision_policy_version=? WHERE url=?", (state, self.cfg["selection_policy_version"], rows[0]["url"]))
            if state == "delivered":
                self.change("INSERT INTO delivery_history(url,receipt_file,message_sha256,message_text,sent_at,telegram_message_ids,run_id) VALUES(?,?,?,?,?,?,?)", (rows[0]["url"], "existing-receipt.json", "existing-hash", headline, COLLECTOR.iso(COLLECTOR.now_utc()), "[10]", "existing-run"))
            unchanged = self.collect(COLLECTOR.parse_html((caption + title_link).encode(), source))
            self.assertEqual(self.states()[rows[0]["url"]], state)
            self.assertNotIn(rows[0]["url"], {x["url"] for x in unchanged["candidates"]})
            changed = self.collect(COLLECTOR.parse_html((caption + title_link.replace("$10B", "$12B")).encode(), source))
            self.assertEqual(self.states()[rows[0]["url"]], "pending")
            self.assertIn(rows[0]["url"], {x["url"] for x in changed["candidates"]})
            if state == "delivered":
                self.assertEqual(changed["delivered_messages"]["existing-hash"], headline)

    def test_unverified_legacy_delivery_never_in_duplicate_evidence(self):
        self.collect([self.article()])
        self.change("UPDATE articles SET status='delivered', delivered_at=?", (COLLECTOR.iso(COLLECTOR.now_utc()),))
        payload = self.collect()
        self.assertEqual(payload["recent_delivered"], [])
        self.assertEqual(len(payload["legacy_unverified_deliveries"]), 1)

    def test_unknown_date_old_policy_review_is_revalidated(self):
        self.cfg["sources"][0]["must_review"] = True
        self.collect([self.article(published=False)])
        self.change("UPDATE articles SET status='reviewed',decision_policy_version=0")
        self.args.lane = "morning"
        payload = self.collect()
        self.assertTrue(payload["candidates"][0]["policy_revalidation"])

    def test_all_old_policy_reviews_revalidated_regardless_of_score_age_or_missing_date(self):
        current = COLLECTOR.now_utc()
        rows = [self.article("low-score", title="Uncategorized technical note", summary=""), self.article("old", title="Uncategorized technical note", summary=""), self.article("undated", title="Uncategorized technical note", summary="", published=False), self.article("current-policy"), self.article("future")]
        rows[1]["published_at"] = current - COLLECTOR.dt.timedelta(days=30)
        rows[4]["published_at"] = current + COLLECTOR.dt.timedelta(days=2)
        self.collect(rows)
        self.change("UPDATE articles SET status='reviewed',decision_policy_version=0")
        self.change("UPDATE articles SET decision_policy_version=? WHERE url=?", (self.cfg["selection_policy_version"], rows[3]["url"]))
        self.args.lane = "morning"
        payload = self.collect()
        self.assertEqual({row["url"] for row in payload["candidates"]}, {row["url"] for row in rows[:3]})
        self.assertTrue(all(row["policy_revalidation"] for row in payload["candidates"]))
        self.assertTrue(all(row["score"] < 25 for row in payload["candidates"]))
        self.assertEqual(payload["revalidation_scope"], "all_previous_policy_reviews")
        self.assertNotIn("revalidation", payload["thresholds"])

    def test_undecided_policy_revalidation_survives_next_morning_until_current_policy_ack(self):
        article = self.article(title="Uncategorized technical note", summary="")
        article["published_at"] = COLLECTOR.now_utc() - COLLECTOR.dt.timedelta(days=30)
        self.collect([article])
        self.change("UPDATE articles SET status='reviewed',decision_policy_version=0")
        self.args.lane = "morning"
        first = self.collect()
        self.assertEqual(len(first["candidates"]), 1)
        tomorrow = COLLECTOR.now_utc() + COLLECTOR.dt.timedelta(days=1)
        with mock.patch.object(COLLECTOR, "now_utc", return_value=tomorrow):
            second = self.collect()
            self.assertEqual(len(second["candidates"]), 1)
            decisions = Path(second["run_files"]["decisions"])
            decisions.write_text(json.dumps({"run_id": second["run_id"], "decisions": [{"url": article["url"], "status": "reviewed", "reason": "Original content reviewed: no industrial facts"}]}), encoding="utf-8")
            COLLECTOR.acknowledge(Namespace(config=self.args.config, db=self.args.db, batch=self.args.output, decision_file=decisions, delivered_url=[], reviewed_url=[], brief_url=[]))
            third = self.collect()
        self.assertEqual(third["candidates"], [])

    def test_atom_uses_alternate_link_even_after_urn_and_self(self):
        xml = b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>urn:example:1</id><title>Grid contract</title><link rel="self" href="https://example.com/self"/><link rel="alternate" href="https://example.com/article"/></entry></feed>'
        self.assertEqual(COLLECTOR.parse_feed(xml, self.cfg["sources"][0])[0]["url"], "https://example.com/article")

    def test_filter_is_applied_before_feed_limit(self):
        self.cfg["sources"][0]["include_terms"] = ["765kV"]
        xml = '<rss><channel>' + ''.join(f'<item><title>unrelated {n}</title><link>https://example.com/{n}</link></item>' for n in range(110)) + '<item><title>765kV contract</title><link>https://example.com/match</link></item></channel></rss>'
        self.assertEqual(COLLECTOR.parse_feed(xml.encode(), self.cfg["sources"][0])[0]["url"], "https://example.com/match")

    def test_numeric_press_release_dates(self):
        self.assertEqual(COLLECTOR.parse_date_from_text("09/09/2026 Delta Electronics investment").date().isoformat(), "2026-09-09")
        self.assertEqual(COLLECTOR.parse_date_from_text("2026-09-10 HVDC release").date().isoformat(), "2026-09-10")

    def test_source_scoped_dmy_title_dates_preserve_default_mdy_and_iso(self):
        cases = [("10/08/2026 3 mins AEMO governance", "DMY", "2026-08-10"), ("25/08/2026 2026 ESOO", "DMY", "2026-08-25"), ("28/07/2026 QED", "DMY", "2026-07-28"), ("10/08/2026 American release", "MDY", "2026-10-08"), ("2026-10-08 ISO date", "DMY", "2026-10-08")]
        for title, order, expected in cases:
            with self.subTest(title=title, order=order):
                self.assertEqual(COLLECTOR.iso(COLLECTOR.parse_date_from_text(title, order)), expected + "T00:00:00+00:00")
        self.assertEqual(COLLECTOR.parse_date_from_text("10/08/2026 default").date().isoformat(), "2026-10-08")
        source = dict(self.cfg["sources"][0], title_date_order="DMY")
        self.assertEqual(COLLECTOR.item(source, "https://example.com/aemo", "10/08/2026 AEMO governance")["published_at"].date().isoformat(), "2026-08-10")

    def test_legacy_mdy_to_dmy_correction_restores_review_without_changing_delivery(self):
        current = COLLECTOR.now_utc().replace(microsecond=0)
        cutoff = current - COLLECTOR.dt.timedelta(hours=1)
        source = self.cfg["sources"][0]
        source.update(title_date_order="DMY", legacy_title_date_order="MDY", timestamp_correction_before=COLLECTOR.iso(cutoff))
        title = "10/08/2026 3 mins Outcome of ECMC review of AEMO's governance arrangements"
        old_date = COLLECTOR.parse_date_from_text(title, "MDY")
        new_date = COLLECTOR.parse_date_from_text(title, "DMY")
        rows = [COLLECTOR.item(source, "https://example.com/aemo-review", title, "Same official content", old_date), COLLECTOR.item(source, "https://example.com/aemo-sent", title, "Same official content", old_date), COLLECTOR.item(source, "https://example.com/aemo-changed", title, "Previous content", old_date)]
        self.collect(rows)
        self.change("UPDATE articles SET status='reviewed',decision_policy_version=0,first_seen_at=?", (COLLECTOR.iso(cutoff - COLLECTOR.dt.timedelta(days=1)),))
        self.change("UPDATE articles SET status='delivered' WHERE url=?", (rows[1]["url"],))
        self.change("INSERT INTO delivery_history(url,receipt_file,message_sha256,message_text,sent_at,telegram_message_ids,run_id) VALUES(?,?,?,?,?,?,?)", (rows[1]["url"], "aemo-receipt.json", "aemo-hash", "Original delivered governance update", COLLECTOR.iso(current), "[22]", "prior-aemo-run"))
        corrected_rows = [COLLECTOR.item(source, row["url"], title, "Same official content") for row in rows]
        self.args.lane = "morning"
        payload = self.collect(corrected_rows)
        candidate = next(row for row in payload["candidates"] if row["url"] == rows[0]["url"])
        self.assertEqual(candidate["published_at"], "2026-08-10T00:00:00+00:00")
        self.assertTrue(candidate["policy_revalidation"])
        self.assertEqual(self.states()[rows[1]["url"]], "delivered")
        self.assertEqual(payload["delivered_messages"]["aemo-hash"], "Original delivered governance update")
        con = sqlite3.connect(self.args.db)
        stored = {row[0]: row[1:] for row in con.execute("SELECT url,published_at,timestamp_corrected_at,summary FROM articles")}
        con.close()
        self.assertEqual(stored[rows[1]["url"]][0], COLLECTOR.iso(new_date))
        self.assertIsNotNone(stored[rows[1]["url"]][1])
        # A changed article is not eligible for this date-only repair.
        self.assertEqual(stored[rows[2]["url"]], (COLLECTOR.iso(old_date), None, "Previous content"))

    def test_naive_feed_timezone_is_scoped_and_real_future_release_remains_hidden(self):
        xml = b'<rss><channel><item><title>Grid contract</title><link>https://example.com/date</link><pubDate>2026-09-11 08:17:22</pubDate></item></channel></rss>'
        source = self.cfg["sources"][0]
        unconfigured = COLLECTOR.parse_feed(xml, source)[0]
        source["date_timezone"] = "+09:00"
        configured = COLLECTOR.parse_feed(xml, source)[0]
        self.assertEqual(COLLECTOR.iso(unconfigured["published_at"]), "2026-09-11T08:17:22+00:00")
        self.assertEqual(COLLECTOR.iso(configured["published_at"]), "2026-09-10T23:17:22+00:00")
        future = COLLECTOR.now_utc() + COLLECTOR.dt.timedelta(hours=3)
        xml = f'<rss><channel><item><title>Grid contract</title><link>https://example.com/future</link><pubDate>{COLLECTOR.iso(future)}</pubDate></item></channel></rss>'.encode()
        future_article = COLLECTOR.parse_feed(xml, source)[0]
        self.assertEqual(COLLECTOR.iso(future_article["published_at"]), COLLECTOR.iso(future))
        self.assertEqual(self.collect([future_article])["candidates"], [])

    def test_one_time_legacy_timestamp_correction_preserves_delivery_and_receipt(self):
        current = COLLECTOR.now_utc().replace(microsecond=0)
        cutoff = current - COLLECTOR.dt.timedelta(hours=1)
        source = self.cfg["sources"][0]
        source.update(timestamp_correction_hours=9, timestamp_correction_before=COLLECTOR.iso(cutoff))
        rows = [self.article("already-sent"), self.article("pending-correction")]
        corrected = current - COLLECTOR.dt.timedelta(minutes=10)
        for row in rows: row["published_at"] = corrected + COLLECTOR.dt.timedelta(hours=9)
        self.collect(rows)
        self.change("UPDATE articles SET first_seen_at=?", (COLLECTOR.iso(cutoff - COLLECTOR.dt.timedelta(days=1)),))
        self.change("UPDATE articles SET status='delivered' WHERE url=?", (rows[0]["url"],))
        self.change("INSERT INTO delivery_history(url,receipt_file,message_sha256,message_text,sent_at,telegram_message_ids,run_id) VALUES(?,?,?,?,?,?,?)", (rows[0]["url"], "preserved-receipt.json", "preserved-hash", "Actually delivered original text", COLLECTOR.iso(current), "[10]", "prior-run"))
        for row in rows: row["published_at"] = corrected
        payload = self.collect(rows)
        self.assertEqual({x["url"] for x in payload["candidates"]}, {rows[1]["url"]})
        self.assertEqual(self.states()[rows[0]["url"]], "delivered")
        self.assertEqual(payload["delivered_messages"]["preserved-hash"], "Actually delivered original text")
        con = sqlite3.connect(self.args.db)
        stored = con.execute("SELECT published_at,timestamp_corrected_at,content_updated_at FROM articles WHERE url=?", (rows[0]["url"],)).fetchone()
        con.close()
        self.assertEqual(stored[0], COLLECTOR.iso(corrected))
        self.assertIsNotNone(stored[1])
        self.assertIsNone(stored[2])
        # An actual older edition cannot reuse the migration exception twice.
        rows[0]["published_at"] = corrected - COLLECTOR.dt.timedelta(hours=9)
        self.collect([rows[0]])
        con = sqlite3.connect(self.args.db)
        published = con.execute("SELECT published_at FROM articles WHERE url=?", (rows[0]["url"],)).fetchone()[0]
        con.close()
        self.assertEqual(published, COLLECTOR.iso(corrected))

    def test_timestamp_migration_requires_exact_predeployment_unchanged_owner_record(self):
        current = COLLECTOR.now_utc().replace(microsecond=0)
        cutoff = current - COLLECTOR.dt.timedelta(hours=1)
        src = dict(self.cfg["sources"][0], timestamp_correction_hours=9, timestamp_correction_before=COLLECTOR.iso(cutoff))
        item = COLLECTOR.item(src, "https://example.com/guard", "Same grid title", "Same summary", current)
        previous = {"source": src["name"], "content_source": None, "title": item["title"], "summary": item["summary"], "published_at": COLLECTOR.iso(current + COLLECTOR.dt.timedelta(hours=9)), "first_seen_at": COLLECTOR.iso(cutoff - COLLECTOR.dt.timedelta(days=1)), "content_updated_at": None, "timestamp_corrected_at": None}
        self.assertTrue(COLLECTOR.is_legacy_timestamp_correction(previous, item, src))
        rejected = [
            {"first_seen_at": COLLECTOR.iso(cutoff)},
            {"content_updated_at": COLLECTOR.iso(cutoff + COLLECTOR.dt.timedelta(seconds=1))},
            {"content_source": "Gmail:EIA"},
            {"source": "Another source"},
            {"title": "Different edition title"},
            {"summary": "Different edition summary"},
            {"published_at": COLLECTOR.iso(current + COLLECTOR.dt.timedelta(hours=8))},
            {"timestamp_corrected_at": COLLECTOR.iso(current)},
        ]
        for changes in rejected:
            with self.subTest(changes=changes):
                self.assertFalse(COLLECTOR.is_legacy_timestamp_correction(dict(previous, **changes), item, src))
        self.assertFalse(COLLECTOR.is_legacy_timestamp_correction(previous, item, self.cfg["sources"][0]))
        genuinely_new = dict(previous, first_seen_at=COLLECTOR.iso(current))
        self.assertFalse(COLLECTOR.is_legacy_timestamp_correction(genuinely_new, item, src))
        self.assertFalse(COLLECTOR.may_update_content(genuinely_new, item, src))

    def test_empty_critical_html_is_a_coverage_gap(self):
        source = {"name": "Official", "url": "https://example.com/news", "kind": "html", "critical": True}
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b"<html><body>Site unavailable</body></html>"
        with mock.patch.object(COLLECTOR.urllib.request, "urlopen", return_value=response):
            fetched = COLLECTOR.fetch(source)
        self.assertFalse(fetched["ok"])
        self.assertIn("No article links parsed", fetched["error"])

    def test_secondary_feed_summary_cannot_reopen_delivered_url(self):
        self.cfg["sources"].append({"name": "Another", "url": "https://second.example/feed", "kind": "rss", "priority": 1})
        article = self.article()
        self.collect([article])
        self.change("UPDATE articles SET status='delivered'")
        alternate = self.article(source=1, summary="Different feed excerpt about the same announcement")
        payload = self.collect([article, alternate])
        self.assertEqual(payload["candidates"], [])
        self.assertEqual(self.states()[article["url"]], "delivered")

    def test_new_historical_filing_is_archived_not_dismissed(self):
        article = self.article()
        article["published_at"] = COLLECTOR.now_utc() - COLLECTOR.dt.timedelta(days=90)
        self.args.lane = "morning"
        payload = self.collect([article])
        self.assertEqual(self.states()[article["url"]], "archive")
        self.assertEqual(payload["queue"]["unreviewed_archive_count"], 1)
        self.assertEqual(payload["candidates"], [])
        self.args.include_archive = True
        backfill = self.collect()
        self.assertEqual(len(backfill["candidates"]), 1)
        self.assertEqual(backfill["candidates"][0]["review_status"], "archive")

    def test_existing_very_old_pending_is_never_auto_archived(self):
        article = self.article()
        self.collect([article])
        old = COLLECTOR.now_utc() - COLLECTOR.dt.timedelta(days=90)
        article["published_at"] = old
        self.change("UPDATE articles SET published_at=?", (COLLECTOR.iso(old),))
        payload = self.collect([article])
        self.assertEqual(self.states()[article["url"]], "pending")
        self.assertEqual(len(payload["candidates"]), 1)

    def test_official_recurring_report_new_edition_reopens_same_url(self):
        self.cfg["sources"][0]["primary"] = True
        article = self.article(title="Electric Power Monthly")
        article["published_at"] = COLLECTOR.now_utc() - COLLECTOR.dt.timedelta(days=2)
        self.collect([article])
        self.change("UPDATE articles SET status='delivered'")
        article["published_at"] = COLLECTOR.now_utc()
        payload = self.collect([article])
        self.assertEqual(self.states()[article["url"]], "pending")
        self.assertEqual(len(payload["candidates"]), 1)

    def test_newsletter_ingestion_joins_candidate_queue_idempotently(self):
        self.args.newsletter_file = self.root / "newsletter.json"
        received_at=COLLECTOR.iso(COLLECTOR.now_utc())
        doc = {"schema_version": 1, "messages": [{"message_id": "eia-final860", "source": "EIA", "source_url": "https://www.eia.gov/", "received_at":received_at, "articles": [{"url": "https://www.eia.gov/electricity/data/eia860/", "title": "Final 2025 Form EIA-860 data", "summary": "Generator capacity data release", "published_at": COLLECTOR.iso(COLLECTOR.now_utc())}]}]}
        self.args.newsletter_file.write_text(json.dumps(doc), encoding="utf-8")
        payload = self.collect()
        self.assertEqual(payload["newsletter_ingestion"]["confirmed_message_ids"], ["eia-final860"])
        self.assertEqual(payload["integrations"]["gmail_processed_message_ids"], ["eia-final860"])
        self.assertEqual(payload["newsletter_ingestion"]["imported_messages"], 1)
        self.assertTrue(payload["candidates"][0]["must_review"])
        self.assertEqual(payload["candidates"][0]["newsletter_received_at"],received_at)
        self.assertEqual(payload["candidates"][0]["newsletter_message_id"],"eia-final860")
        again = self.collect()
        self.assertEqual(again["newsletter_ingestion"]["already_imported_messages"], 1)
        self.assertEqual(len(self.states()), 1)

    def test_reimported_old_newsletter_cannot_roll_back_new_report(self):
        self.args.newsletter_file = self.root / "newsletter.json"
        doc = {"schema_version": 1, "messages": [{"message_id": "old-eia-release", "source": "EIA", "source_url": "https://www.eia.gov/", "articles": [{"url": "https://www.eia.gov/electricity/monthly/", "title": "July Electric Power Monthly", "summary": "July capacity data release", "published_at": COLLECTOR.iso(COLLECTOR.now_utc())}]}]}
        self.args.newsletter_file.write_text(json.dumps(doc), encoding="utf-8")
        self.collect()
        self.change("UPDATE articles SET title='August Electric Power Monthly',summary='August capacity data release'")
        payload = self.collect()
        self.assertEqual(payload["candidates"][0]["title"], "August Electric Power Monthly")
        self.assertEqual(payload["newsletter_ingestion"]["already_imported_messages"], 1)

    def test_durable_gmail_ids_survive_rss_only_runs_and_old_snapshot_exports(self):
        self.args.newsletter_file = self.root / "newsletter.json"
        doc = {"schema_version": 1, "messages": [{"message_id": "first-mail", "source": "EIA", "source_url": "https://www.eia.gov/", "articles": [{"url": "https://www.eia.gov/first", "title": "First grid capacity release", "published_at": COLLECTOR.iso(COLLECTOR.now_utc())}]}]}
        self.args.newsletter_file.write_text(json.dumps(doc), encoding="utf-8")
        first = self.collect()
        old_snapshot = Path(first["run_files"]["snapshot"])
        doc["messages"].append({"message_id": "second-mail", "source": "EIA", "source_url": "https://www.eia.gov/", "articles": [{"url": "https://www.eia.gov/second", "title": "Second grid capacity release", "published_at": COLLECTOR.iso(COLLECTOR.now_utc())}]})
        self.args.newsletter_file.write_text(json.dumps(doc), encoding="utf-8")
        self.collect()
        self.args.newsletter_file = None
        rss_only = self.collect()
        self.assertEqual(set(rss_only["integrations"]["gmail_processed_message_ids"]), {"first-mail", "second-mail"})
        args = Namespace(batch=old_snapshot, db=self.args.db, offset=0, max_candidates=100, output=self.root / "old-page.json")
        COLLECTOR.export_batch(args)
        exported = json.loads(args.output.read_text(encoding="utf-8"))
        self.assertEqual(set(exported["integrations"]["gmail_processed_message_ids"]), {"first-mail", "second-mail"})
        # Refreshing processing IDs on export does not mutate the old snapshot.
        self.assertEqual(json.loads(old_snapshot.read_text(encoding="utf-8"))["integrations"]["gmail_processed_message_ids"], ["first-mail"])

    def official_collision(self, rss_date, mail_date):
        self.cfg["sources"][0] = {"name": "EIA RSS", "url": "https://www.eia.gov/rss/feed.xml", "kind": "rss", "priority": 1, "primary": True, "must_review": True}
        url = "https://www.eia.gov/electricity/monthly/"
        rss = COLLECTOR.item(self.cfg["sources"][0], url, "RSS edition", "RSS capacity data", rss_date)
        self.collect([rss])
        self.change("UPDATE articles SET status='delivered'")
        self.change("INSERT INTO delivery_history(url,receipt_file,message_sha256,message_text,sent_at,telegram_message_ids,run_id) VALUES(?,?,?,?,?,?,?)", (url, "historical-receipt.json", "historical-hash", "Actually delivered RSS edition", COLLECTOR.iso(COLLECTOR.now_utc()), "[10]", "historical-run"))
        self.args.newsletter_file = self.root / "official-newsletter.json"
        doc = {"schema_version": 1, "messages": [{"message_id": "eia-collision", "source": "EIA", "source_url": "https://www.eia.gov/", "articles": [{"url": url, "title": "Newsletter edition", "summary": "Newsletter capacity data", "published_at": COLLECTOR.iso(mail_date)}]}]}
        self.args.newsletter_file.write_text(json.dumps(doc), encoding="utf-8")
        return rss, self.collect([rss])

    def test_newer_official_newsletter_reopens_delivered_rss_url_without_pingpong(self):
        current = COLLECTOR.now_utc()
        rss, payload = self.official_collision(current - COLLECTOR.dt.timedelta(days=2), current)
        candidate = payload["candidates"][0]
        self.assertEqual(candidate["title"], "Newsletter edition")
        self.assertEqual(candidate["source"], "EIA RSS")
        self.assertEqual(candidate["content_source"], "Gmail:EIA")
        self.assertEqual(self.states()[rss["url"]], "pending")
        self.assertEqual(payload["delivered_messages"]["historical-hash"], "Actually delivered RSS edition")
        self.args.newsletter_file = None
        older_rss = self.collect([rss])
        self.assertEqual(older_rss["candidates"][0]["title"], "Newsletter edition")
        rss["published_at"] = current
        same_date_excerpt = self.collect([rss])
        self.assertEqual(same_date_excerpt["candidates"][0]["title"], "Newsletter edition")
        rss["published_at"] = None
        undated_excerpt = self.collect([rss])
        self.assertEqual(undated_excerpt["candidates"][0]["title"], "Newsletter edition")

    def test_older_official_newsletter_cannot_downgrade_delivered_rss_url(self):
        current = COLLECTOR.now_utc()
        rss, payload = self.official_collision(current, current - COLLECTOR.dt.timedelta(days=2))
        self.assertEqual(payload["candidates"], [])
        self.assertEqual(self.states()[rss["url"]], "delivered")
        con = sqlite3.connect(self.args.db)
        stored = con.execute("SELECT title,summary,published_at FROM articles WHERE url=?", (rss["url"],)).fetchone()
        con.close()
        self.assertEqual(stored, ("RSS edition", "RSS capacity data", COLLECTOR.iso(current)))
        self.assertEqual(payload["integrations"]["gmail_processed_message_ids"], ["eia-collision"])

    def test_malformed_newsletter_does_not_block_rss_or_mark_processed(self):
        self.args.newsletter_file = self.root / "newsletter.json"
        self.args.newsletter_file.write_text('{"schema_version":1,"messages":[{}]}', encoding="utf-8")
        payload = self.collect([self.article()])
        self.assertEqual(len(payload["candidates"]), 1)
        self.assertIsNotNone(payload["newsletter_ingestion"]["error"])
        self.assertEqual(payload["newsletter_ingestion"]["confirmed_message_ids"], [])

    def test_transient_source_failure_gets_only_one_retry(self):
        bad = {"ok": False, "retryable": True}
        good = {"ok": True}
        with mock.patch.object(COLLECTOR, "fetch_once", side_effect=[bad, good]) as once:
            result = COLLECTOR.fetch(self.cfg["sources"][0])
        self.assertTrue(result["ok"])
        self.assertEqual(result["attempts"], 2)
        self.assertEqual(once.call_count, 2)

    def test_blocked_or_parse_failure_is_not_retried(self):
        with mock.patch.object(COLLECTOR, "fetch_once", return_value={"ok": False, "retryable": False}) as once:
            COLLECTOR.fetch(self.cfg["sources"][0])
        once.assert_called_once()


if __name__ == "__main__":
    unittest.main()
