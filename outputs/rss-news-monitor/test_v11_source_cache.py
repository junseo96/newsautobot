from email.message import Message
import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest import mock
import urllib.request
import urllib.error

import v11_source_cache as cache


TEXT = "Verified utility approval of a 500 MW power project with construction beginning in 2027 and service planned for 2029. " * 2


def response(body, url="https://publisher.example/news/project", content_type="text/html; charset=utf-8", extra_headers=None):
    result = mock.MagicMock()
    result.__enter__.return_value = result
    result.geturl.return_value = url
    result.read.return_value = body
    result.headers = Message()
    result.headers["Content-Type"] = content_type
    for key, value in (extra_headers or {}).items():
        result.headers[key] = value
    return result


class PublicURLTests(unittest.TestCase):
    def test_only_public_article_get_paths_are_allowed(self):
        for url in (
            "file:///etc/passwd", "ftp://example.com/article", "https://user:password@example.com/article",
            "https://example.com:8443/news", "https://example.com/unsubscribe?id=123",
            "https://example.com/%2575nsubscribe", "https://example.com/view?action=unsubscribe",
            "https://example.com/account/change-email", "https://example.com/manage-preferences",
            "https://example.com/profile?email=changed",
            "https://example.com/admin/report", "https://example.com/news?access_token=secret",
            "https://example.com/news\nHeader: injected",
            "https://example.com/privacy-policy", "https://example.com/subscribe",
            "https://linkedin.com/sharing/share-offsite/?url=https://example.com/article",
        ):
            with self.subTest(url=url), self.assertRaises(cache.PublicSourceError):
                cache._validate_url(url)
        self.assertEqual(cache._validate_url("https://news.google.com/rss/articles/opaque?oc=5#section"),
                         "https://news.google.com/rss/articles/opaque?oc=5")

    def test_dns_rejects_private_reserved_loopback_and_mixed_answers(self):
        for addresses in (("127.0.0.1",), ("10.0.0.1",), ("169.254.169.254",), ("::1",),
                          ("::ffff:192.168.1.1",), ("100.64.0.1",), ("224.0.0.1",), ("ff02::1",),
                          ("93.184.216.34", "192.168.1.1")):
            answers = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443)) for ip in addresses]
            with self.subTest(addresses=addresses), mock.patch.object(cache.socket, "getaddrinfo", return_value=answers):
                with self.assertRaisesRegex(cache.PublicSourceError, "nonpublic"):
                    cache._public_addresses("publisher.example", 443)

    def test_connection_pins_prechecked_address_and_never_resolves_again(self):
        answer = (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
        connection = mock.MagicMock()
        with mock.patch.object(cache.socket, "getaddrinfo", return_value=[answer]) as dns, \
                mock.patch.object(cache.socket, "socket", return_value=connection):
            self.assertIs(cache._public_socket("publisher.example", 443, 15), connection)
        dns.assert_called_once_with("publisher.example", 443, type=socket.SOCK_STREAM)
        connection.connect.assert_called_once_with(("93.184.216.34", 443))
        connection.settimeout.assert_called_once_with(15)

    def test_redirected_private_connection_is_rejected_before_socket(self):
        request = urllib.request.Request("https://public.example/story")
        redirect = cache._PublicRedirectHandler().redirect_request(request, None, 302, "Found", {}, "http://127.0.0.1/private")
        self.assertEqual(redirect.get_method(), "GET")
        answers = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80))]
        with mock.patch.object(cache.socket, "getaddrinfo", return_value=answers), \
                mock.patch.object(cache.socket, "socket") as connection:
            with self.assertRaises(cache.PublicSourceError):
                cache._PublicHTTPConnection(redirect.host).connect()
        connection.assert_not_called()

    def test_redirect_to_account_action_is_rejected(self):
        request = urllib.request.Request("https://public.example/story")
        with self.assertRaises(cache.PublicSourceError):
            cache._PublicRedirectHandler().redirect_request(request, None, 302, "Found", {}, "https://example.com/unsubscribe")


class ArticleExtractionTests(unittest.TestCase):
    def test_main_story_wins_over_multiple_related_article_cards(self):
        actual = TEXT * 5
        body = ('<main><div><p>' + actual + '</p></div>'
                '<article><p>Related story card ' + 'other story '*10 + '</p></article>'
                '<article><p>Another card ' + 'other story '*10 + '</p></article></main>').encode()
        data = self.fetch_response(response(body))
        self.assertIn(actual.strip(), data['text'])

    def test_article_body_excludes_page_chrome_and_duplicate_mobile_paragraphs(self):
        body=("<title>Grid contract</title><p>Generic website links " + "menu "*100 + "</p><main><article><p>"+TEXT+"</p><p>"+TEXT+"</p></article><aside><p>Unrelated promotional sidebar</p></aside></main>").encode()
        data=self.fetch_response(response(body))
        self.assertEqual(data["text"],TEXT.strip())
        self.assertNotIn("menu",data["text"])

    def test_article_jsonld_supplies_published_date_not_generic_page_update(self):
        structured={"@graph":[{"@type":"WebPage","dateModified":"2026-09-28"},{"@type":"NewsArticle","datePublished":"2026-09-27T19:30:00Z","articleBody":TEXT}]}
        body=('<time datetime="1999-01-01"></time><script type="application/ld+json">'+json.dumps(structured)+'</script>').encode()
        data=self.fetch_response(response(body))
        self.assertTrue(data["usable"])
        self.assertEqual(data["published_at"],"2026-09-27T19:30:00Z")
        self.assertEqual(data["publication_precision"],"exact")
        self.assertEqual(data["text"],TEXT.strip())

    def test_date_only_metadata_and_malformed_jsonld_are_handled(self):
        body=('<meta property="article:published_time" content="2026-09-28"><script type="application/ld+json">broken</script><article><p>'+TEXT+'</p></article>').encode()
        data=self.fetch_response(response(body))
        self.assertEqual(data["publication_precision"],"date")
        self.assertEqual(data["published_at"],"2026-09-28")

    def test_timezone_missing_wall_clock_is_not_claimed_as_exact_utc(self):
        body=('<meta property="article:published_time" content="2026-09-24T07:55:47.132"><p>'+TEXT+'</p>').encode()
        data=self.fetch_response(response(body))
        self.assertEqual(data["publication_precision"],"date")
        self.assertEqual(data["published_at"],"2026-09-24")
        self.assertEqual(data["publication_raw"],"2026-09-24T07:55:47.132")

    def fetch_response(self, result, url="https://publisher.example/news/project"):
        opener = mock.MagicMock()
        opener.open.return_value = result
        with mock.patch.object(cache, "_opener", return_value=opener):
            data = cache._fetch(url)
        opener.open.assert_called_once()
        request = opener.open.call_args.args[0]
        self.assertEqual(request.get_method(), "GET")
        self.assertIsNone(request.get_header("Authorization"))
        self.assertIsNone(request.get_header("Cookie"))
        self.assertEqual(opener.open.call_args.kwargs["timeout"], 15)
        result.read.assert_called_once_with(cache.MAX_BYTES + 1)
        return data

    def test_extracts_title_paragraphs_headings_and_publication_metadata(self):
        body = ('<html><head><title>Utility approval</title><meta property="article:published_time" content="2026-09-24T09:00:00+09:00">'
                '<style>remove style</style><script>remove script</script></head><body>'
                '<nav><p>remove navigation</p></nav><h1>500 MW approved</h1><p>' + TEXT + '</p>'
                '<footer><p>remove footer</p></footer></body></html>').encode()
        data = self.fetch_response(response(body))
        self.assertTrue(data["ok"])
        self.assertTrue(data["usable"])
        self.assertEqual(data["title"], "Utility approval")
        self.assertEqual(data["published_at"], "2026-09-24T09:00:00+09:00")
        self.assertIn("500 MW approved", data["text"])
        self.assertIn(TEXT.strip(), data["text"])
        self.assertNotIn("remove", data["text"])

    def test_time_metadata_and_open_graph_title_are_preserved(self):
        body = ('<meta property="og:title" content="Grid project"><time datetime="2026-09-24"></time><p>' + TEXT + '</p>').encode()
        data = self.fetch_response(response(body))
        self.assertEqual(data["published_at"], "2026-09-24")
        self.assertEqual(data["title"], "Grid project")

    def test_google_news_intermediate_page_is_not_original_evidence(self):
        url = "https://news.google.com/rss/articles/opaque?oc=5"
        data = self.fetch_response(response(("<title>Google News</title><p>" + TEXT + "</p>").encode(), url=url), url=url)
        self.assertFalse(data["ok"])
        self.assertFalse(data["usable"])
        self.assertEqual(data["error"], "tracking_destination_unresolved")

    def test_google_news_http_redirect_to_publisher_can_be_cached(self):
        url = "https://news.google.com/rss/articles/opaque?oc=5"
        data = self.fetch_response(response(("<title>Original</title><p>" + TEXT + "</p>").encode()), url=url)
        self.assertTrue(data["usable"])
        self.assertEqual(data["final_url"], "https://publisher.example/news/project")

    def test_short_empty_or_access_challenge_is_not_usable(self):
        for body in (b"<p>Loading...</p>", ("<title>Access Denied</title><p>" + TEXT + "</p>").encode()):
            with self.subTest(body=body):
                self.assertFalse(self.fetch_response(response(body))["usable"])

    def test_oversized_and_nontext_bodies_fail(self):
        cases = [response(b"", extra_headers={"Content-Length": str(cache.MAX_BYTES + 1)}),
                 response(b"x" * (cache.MAX_BYTES + 1)),
                 response(b"%PDF-1.7", content_type="application/pdf")]
        for result in cases:
            opener = mock.MagicMock()
            opener.open.return_value = result
            with mock.patch.object(cache, "_opener", return_value=opener), self.assertRaises(cache.PublicSourceError):
                cache._fetch("https://publisher.example/article")


class TrackingResolutionTests(unittest.TestCase):
    tracker = 'https://hello.canarymedia.com/e3t/Ctc/example'
    fallback = tracker + '?_ud=example&_jss=0'

    def interstitial(self, target=None, extra=''):
        return ('<script>window.location="https://do-not-execute.example/"</script>'
                '<h1>You\'re being redirected</h1><p>If you\'re not redirected in a few seconds,</p>'
                '<a href="' + (target or self.fallback) + '">click here</a>' + extra).encode()

    def test_visible_fallback_resolves_original_and_preserves_provenance(self):
        opener = mock.MagicMock()
        opener.open.side_effect = [response(self.interstitial(), url=self.tracker),
                                   response(('<article><p>' + TEXT + '</p></article>').encode())]
        with mock.patch.object(cache, '_opener', return_value=opener):
            result = cache._fetch(self.tracker)
        self.assertTrue(result['usable'])
        self.assertEqual(result['final_url'], 'https://publisher.example/news/project')
        self.assertEqual(opener.open.call_args_list[1].args[0].full_url, self.fallback)
        self.assertEqual(result['redirect_provenance'][0]['from_url'], self.tracker)
        self.assertEqual(result['redirect_provenance'][0]['method'], 'visible_redirect_anchor')

    def test_access_failure_keeps_resolved_public_destination_without_body_claim(self):
        target = 'https://publisher.example/industry/project'
        opener = mock.MagicMock()
        opener.open.side_effect = [response(self.interstitial(), url=self.tracker),
                                   urllib.error.HTTPError(target, 403, 'Forbidden', Message(), None)]
        with mock.patch.object(cache, '_opener', return_value=opener):
            result = cache._fetch(self.tracker)
        self.assertFalse(result['usable'])
        self.assertEqual(result['error'], 'http_403')
        self.assertEqual(result['final_url'], target)
        self.assertEqual(len(result['redirect_provenance']), 1)

    def test_scripts_and_other_hosts_are_never_document_redirects(self):
        self.assertIsNone(cache._document_redirect(self.tracker, '<script>window.location="https://publisher.example"</script>'))
        self.assertIsNone(cache._document_redirect('https://unrelated.example/', self.interstitial().decode()))

    def test_ambiguous_or_action_destinations_never_open(self):
        for body in (self.interstitial(extra='<a href="https://other.example/">Other</a>'),
                     self.interstitial('https://publisher.example/unsubscribe'),
                     self.interstitial('https://publisher.example/privacy-policy'),
                     self.interstitial('https://x.com/intent/tweet'),
                     self.interstitial('javascript:alert(1)')):
            opener = mock.MagicMock()
            opener.open.return_value = response(body, url=self.tracker)
            with self.subTest(body=body), mock.patch.object(cache, '_opener', return_value=opener):
                with self.assertRaises(cache.PublicSourceError):
                    cache._fetch(self.tracker)
            opener.open.assert_called_once()

    def test_visible_fallback_still_checks_dns_and_bounded_hops(self):
        target = cache._document_redirect(self.tracker, self.interstitial('http://127.0.0.1/story').decode())
        request = urllib.request.Request(target)
        answers = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', 80))]
        with mock.patch.object(cache.socket, 'getaddrinfo', return_value=answers), mock.patch.object(cache.socket, 'socket') as sock:
            with self.assertRaises(cache.PublicSourceError):
                cache._PublicHTTPConnection(request.host).connect()
            sock.assert_not_called()
        opener = mock.MagicMock()
        opener.open.side_effect = [response(self.interstitial(self.tracker+'?hop='+str(i+1)),
                                           url=self.tracker if i == 0 else self.tracker+'?hop='+str(i))
                                   for i in range(cache.MAX_DOCUMENT_REDIRECTS+1)]
        with mock.patch.object(cache, '_opener', return_value=opener):
            with self.assertRaisesRegex(cache.PublicSourceError, 'tracking_redirect_limit'):
                cache._fetch(self.tracker)
        self.assertEqual(opener.open.call_count, cache.MAX_DOCUMENT_REDIRECTS+1)

    def test_self_redirect_stops_before_second_request(self):
        opener = mock.MagicMock()
        opener.open.return_value = response(self.interstitial(self.tracker), url=self.tracker)
        with mock.patch.object(cache, '_opener', return_value=opener):
            with self.assertRaisesRegex(cache.PublicSourceError, 'tracking_redirect_loop'):
                cache._fetch(self.tracker)
        opener.open.assert_called_once()


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.url = "https://publisher.example/article"
        self.good = {"final_url": self.url, "title": "Grid approval", "text": TEXT, "ok": True, "usable": True}

    def tearDown(self):
        self.temp.cleanup()

    def test_cache_avoids_repeat_fetch_and_expires_at_callers_ttl(self):
        with mock.patch.object(cache, "_fetch", return_value=self.good) as fetch, mock.patch.object(cache.time, "time", return_value=10000):
            first = cache.get(self.root, self.url, ttl_seconds=60)
        self.assertFalse(first["from_cache"])
        self.assertEqual(Path(first["cache_file"]).parent, self.root / "work" / "v11" / "source-cache")
        self.assertEqual(len(Path(first["cache_file"]).stem), 64)
        with mock.patch.object(cache, "_fetch", return_value=self.good) as fetch, mock.patch.object(cache.time, "time", return_value=10059):
            second = cache.get(self.root, self.url, ttl_seconds=60)
            fetch.assert_not_called()
        self.assertTrue(second["from_cache"])
        self.assertEqual(second["fetched_at"], first["fetched_at"])
        with mock.patch.object(cache, "_fetch", return_value=self.good) as fetch, mock.patch.object(cache.time, "time", return_value=10060):
            cache.get(self.root, self.url, ttl_seconds=60)
            fetch.assert_called_once()

    def test_network_failure_retries_after_at_most_fifteen_minutes(self):
        with mock.patch.object(cache, "_fetch", side_effect=TimeoutError("sensitive diagnostic must not leak")), mock.patch.object(cache.time, "time", return_value=10000):
            first = cache.get(self.root, self.url)
        self.assertEqual(first["error"], "network_timeout")
        self.assertNotIn("sensitive", json.dumps(first))
        with mock.patch.object(cache, "_fetch", return_value=self.good) as fetch, mock.patch.object(cache.time, "time", return_value=10899):
            second = cache.get(self.root, self.url)
            fetch.assert_not_called()
        self.assertFalse(second["usable"])
        with mock.patch.object(cache, "_fetch", return_value=self.good) as fetch, mock.patch.object(cache.time, "time", return_value=10900):
            self.assertTrue(cache.get(self.root, self.url)["ok"])
            fetch.assert_called_once()

    def test_unusable_tracking_result_uses_short_failure_ttl(self):
        unusable = dict(self.good, ok=False, usable=False, error="tracking_destination_unresolved")
        with mock.patch.object(cache, "_fetch", return_value=unusable), mock.patch.object(cache.time, "time", return_value=10000):
            cache.get(self.root, self.url)
        with mock.patch.object(cache, "_fetch", return_value=self.good) as fetch, mock.patch.object(cache.time, "time", return_value=10901):
            self.assertTrue(cache.get(self.root, self.url)["ok"])
            fetch.assert_called_once()

    def test_resolver_upgrade_retries_only_old_canary_cache(self):
        tracker = TrackingResolutionTests.tracker
        for url in (tracker, self.url):
            path = cache._cache_path(self.root, url)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({'version': cache._CACHE_VERSION, 'url': url,
                'stored_at': 10000, 'result': dict(self.good, final_url=url)}), encoding='utf-8')
        with mock.patch.object(cache, '_fetch', return_value=self.good) as fetch, mock.patch.object(cache.time, 'time', return_value=10001):
            self.assertTrue(cache.get(self.root, self.url)['from_cache'])
            fetch.assert_not_called()
            self.assertFalse(cache.get(self.root, tracker)['from_cache'])
            fetch.assert_called_once_with(tracker)

    def test_failed_upgraded_resolver_keeps_failure_backoff(self):
        tracker = TrackingResolutionTests.tracker
        with mock.patch.object(cache, '_fetch', side_effect=TimeoutError()), mock.patch.object(cache.time, 'time', return_value=10000):
            first = cache.get(self.root, tracker)
        self.assertEqual(first['tracking_resolver_version'], cache.TRACKING_RESOLVER_VERSION)
        with mock.patch.object(cache, '_fetch') as fetch, mock.patch.object(cache.time, 'time', return_value=10001):
            self.assertTrue(cache.get(self.root, tracker)['from_cache'])
            fetch.assert_not_called()

    def test_corrupt_cache_does_not_prevent_safe_refetch(self):
        path = cache._cache_path(self.root, self.url)
        path.parent.mkdir(parents=True)
        path.write_text("{incomplete", encoding="utf-8")
        with mock.patch.object(cache, "_fetch", return_value=self.good) as fetch:
            self.assertTrue(cache.get(self.root, self.url)["ok"])
        fetch.assert_called_once()
        self.assertEqual(list(path.parent.glob("*.tmp")), [])

    def test_unsafe_url_is_rejected_without_network_or_cache_write(self):
        with mock.patch.object(cache, "_fetch") as fetch:
            result = cache.get(self.root, "https://example.com/unsubscribe")
        self.assertFalse(result["ok"])
        fetch.assert_not_called()
        self.assertFalse((self.root / "work").exists())


if __name__ == "__main__":
    unittest.main()
