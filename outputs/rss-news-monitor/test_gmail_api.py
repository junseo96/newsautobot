import base64
import copy
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request

import gmail_api
import gmail_run_check
import gmail_scan
import v11_gmail
import v11_mail_worker
import v11_runtime


def message(message_id="new"):
    html = b'<a href="https://example.com/news/1">New transmission project</a>'
    return {"id": message_id, "internalDate": str(int(time.time() * 1000)), "payload": {
        "mimeType": "text/html", "headers": [{"name": "From", "value": "news@example.com"}],
        "body": {"data": base64.urlsafe_b64encode(html).decode().rstrip("="), "size": len(html)}}}


class Opener:
    def __init__(self, responses):
        self.responses, self.requests = list(responses), []

    def open(self, request, timeout):
        self.requests.append(request)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return io.BytesIO(json.dumps(response).encode())


def client(responses):
    opener = Opener([{"access_token": "access-secret", "expires_in": 3600}, *responses])
    return gmail_api.GmailApiClient("client-id", "client-secret", "refresh-secret", opener=opener), opener


class GmailApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)

    def test_paginates_every_result_without_labels_and_preserves_actual_evidence(self):
        api, opener = client([{"messages": [{"id": "new"}], "nextPageToken": "next"},
                              {"messages": [{"id": "second"}, {"id": "known"}]},
                              message("new"), message("second")])
        result = gmail_api.collect("after:100 before:200", {"known"}, set(), set(), self.directory, client=api)
        self.assertTrue(result["search"]["pagination_complete"])
        self.assertEqual(result["search"]["message_ids"], ["known", "new", "second"])
        self.assertEqual(set(result["captured"]), {"new", "second"})
        self.assertEqual(len(opener.requests), 5)
        parameters = parse_qs(urlsplit(opener.requests[2].full_url).query)
        self.assertEqual(parameters, {"q": ["after:100 before:200"], "maxResults": ["100"], "pageToken": ["next"]})
        evidence = [json.loads(Path(path).read_text()) for path in result["evidence_files"]]
        self.assertTrue(all(item["provider"] == "gmail_api" for item in evidence))
        serialized = json.dumps(evidence)
        for secret in ("access-secret", "refresh-secret", "client-secret"):
            self.assertNotIn(secret, serialized)
        self.assertEqual([r.method for r in opener.requests], ["POST", "GET", "GET", "GET", "GET"])
        self.assertEqual(opener.requests[0].full_url, gmail_api.TOKEN_URL)
        self.assertTrue(all(r.full_url.startswith(gmail_api.API_ROOT) for r in opener.requests[1:]))

    def test_empty_result_requires_valid_empty_response(self):
        api, _ = client([{"resultSizeEstimate": 0}])
        result = gmail_api.collect("q", set(), set(), set(), self.directory, client=api)
        self.assertTrue(result["search"]["pagination_complete"])
        api, _ = client([{}])
        result = gmail_api.collect("q", set(), set(), set(), self.directory, attempts=1, client=api)
        self.assertFalse(result["search"]["pagination_complete"])

    def test_failed_page_preserves_full_bodies_and_resumes_at_failed_page(self):
        api, opener = client([{"messages": [{"id": "new"}], "nextPageToken": "p2"},
            URLError("private error body"), message(), {"messages": [{"id": "second"}]}, message("second")])
        result = gmail_api.collect("q", set(), set(), set(), self.directory, client=api)
        self.assertTrue(result["search"]["pagination_complete"])
        self.assertEqual(result["search"]["page_count"], 2)
        self.assertEqual(set(result["captured"]), {"new", "second"})
        self.assertEqual(opener.requests[2].full_url, opener.requests[4].full_url)
        self.assertEqual(sum("/new?" in request.full_url for request in opener.requests), 1)
        self.assertNotIn("private error body", json.dumps(result))

    def test_failed_body_retries_only_body_after_complete_search(self):
        api, opener = client([{"messages": [{"id": "new"}]}, URLError("unavailable"), message()])
        result = gmail_api.collect("q", set(), set(), set(), self.directory, client=api)
        self.assertTrue(result["search"]["pagination_complete"])
        self.assertEqual(set(result["captured"]), {"new"})
        self.assertEqual(sum("maxResults=" in request.full_url for request in opener.requests), 1)

    def test_pagination_cycle_cannot_claim_complete_or_loop_forever(self):
        api, opener = client([{"messages": [{"id": "new"}], "nextPageToken": "same"},
                              {"messages": [], "nextPageToken": "same"}, message()])
        result = gmail_api.collect("q", set(), set(), set(), self.directory, client=api)
        self.assertFalse(result["search"]["pagination_complete"])
        self.assertEqual(len(opener.requests), 4)
        self.assertEqual(set(result["captured"]), {"new"})
        self.assertIn("GmailPaginationLoop", [error["error_type"] for error in result["failures"]])

    def test_unsafe_message_id_is_never_requested_or_written(self):
        api, opener = client([{"messages": [{"id": "../escape"}]}])
        result = gmail_api.collect("q", set(), set(), set(), self.directory, attempts=1, client=api)
        self.assertEqual(result["search"]["page_count"], 0)
        self.assertFalse(result["captured"])
        self.assertEqual(len(opener.requests), 2)

    def test_malformed_pagination_tokens_cannot_forge_a_final_page(self):
        for token in (False, 0, [], {}, 12):
            with self.subTest(token=token):
                api, _ = client([{"messages": [], "nextPageToken": token}])
                result = gmail_api.collect("q", set(), set(), set(), self.directory, attempts=1, client=api)
                self.assertFalse(result["search"]["pagination_complete"])
                self.assertEqual(result["search"]["page_count"], 0)

    def test_id_mismatch_and_snippets_are_not_full_mail(self):
        for response in (message("wrong"), {"id": "new", "snippet": "incomplete"},
                         {"id": "new", "payload": {"headers": [], "body": {}}}):
            with self.subTest(response=response):
                api, _ = client([{"messages": [{"id": "new"}]}, response])
                result = gmail_api.collect("q", set(), set(), set(), self.directory, attempts=1, client=api)
                self.assertTrue(result["search"]["pagination_complete"])
                self.assertEqual(result["captured"], {})

    def test_text_attachment_is_hydrated_and_binary_attachment_stays_reference(self):
        text = message()["payload"]
        attachment = copy.deepcopy(text["body"])
        text["body"] = {"attachmentId": "attachment-text", "size": attachment["size"]}
        mime = {"id": "new", "payload": {"mimeType": "multipart/mixed", "headers": [], "body": {"size": 0},
            "parts": [text, {"mimeType": "application/pdf", "headers": [],
                             "body": {"attachmentId": "attachment-binary", "size": 1024}}]}}
        api, opener = client([mime, attachment])
        result = api.get_message("new")
        hydrated = result["payload"]["parts"][0]["body"]
        self.assertNotIn("attachmentId", hydrated)
        self.assertEqual(hydrated["resolvedAttachmentId"], "attachment-text")
        self.assertIn("New transmission project", v11_gmail.mime_texts(result["payload"])[0][1])
        self.assertTrue(gmail_scan._full_mime_payload(result["payload"]))
        self.assertEqual(len(opener.requests), 3)
        self.assertTrue(opener.requests[-1].full_url.endswith("/new/attachments/attachment-text"))

    def test_missing_attachment_invalid_encoding_or_size_cannot_be_cached(self):
        source = message()
        size = source["payload"]["body"]["size"]
        source["payload"]["body"] = {"attachmentId": "text-attachment", "size": size}
        for attachment in ({"size": size}, {"data": "???", "size": size}, {"data": "YQ", "size": 1}):
            with self.subTest(attachment=attachment):
                api, _ = client([source, attachment])
                with self.assertRaises(gmail_api.GmailApiError):
                    api.get_message("new")
        invalid = message()
        invalid["payload"]["body"]["size"] += 1
        api, _ = client([invalid])
        with self.assertRaises(gmail_api.GmailApiError):
            api.get_message("new")

    def test_existing_queue_is_read_but_cached_and_ingested_mail_is_not(self):
        api, opener = client([{"messages": [{"id": "cached"}, {"id": "known"}]}, message("queued")])
        result = gmail_api.collect("q", {"known"}, {"cached"}, {"queued", "cached"}, self.directory, client=api)
        self.assertEqual(set(result["captured"]), {"queued"})
        self.assertEqual(len(opener.requests), 3)

    def test_expired_access_token_refreshes_once_without_dumping_credentials(self):
        denied = HTTPError(gmail_api.API_ROOT, 401, "private body", {}, io.BytesIO(b"access-secret"))
        api, opener = client([denied, {"access_token": "second-access-secret"}, {"resultSizeEstimate": 0}])
        self.assertEqual(api.list_messages("q"), {"resultSizeEstimate": 0})
        self.assertEqual([r.method for r in opener.requests], ["POST", "GET", "POST", "GET"])

    def test_oauth_errors_and_redirects_do_not_expose_or_forward_credentials(self):
        request = Request(gmail_api.TOKEN_URL, data=b"secret", method="POST")
        self.assertIsNone(gmail_api._NoRedirect().redirect_request(
            request, None, 302, "redirect", {}, "https://untrusted.example/"))
        opener = Opener([HTTPError(gmail_api.TOKEN_URL, 400, "refresh-secret", {}, io.BytesIO(b"refresh-secret"))])
        api = gmail_api.GmailApiClient("client-id", "client-secret", "refresh-secret", opener=opener)
        with self.assertRaises(gmail_api.GmailApiError) as failure:
            api.list_messages("q")
        self.assertEqual(str(failure.exception), "GmailHttpError (HTTP 400)")
        self.assertNotIn("secret", str(failure.exception))
        self.assertEqual(len(opener.requests), 1)

    def test_missing_credentials_report_safe_failure_without_network(self):
        with patch.dict(os.environ, {name: "" for name in gmail_api.REQUIRED_ENV}):
            result = gmail_api.collect("q", set(), set(), set(), self.directory)
        self.assertFalse(result["search"]["pagination_complete"])
        self.assertEqual(result["failures"][0]["error_type"], "MissingGmailOAuthCredentials")


class GmailApiWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "outputs/rss-news-monitor").mkdir(parents=True)
        (self.root / "work").mkdir()
        v11_runtime.save_json(self.root / "outputs/rss-news-monitor/runtime-v9.json", {
            "version": 9, "gmail_start_epoch": 100, "retired_message_ids": []})
        with sqlite3.connect(self.root / "work/rss-news-monitor.db") as connection:
            connection.execute("CREATE TABLE newsletter_messages(message_id TEXT PRIMARY KEY)")
        self.directory = self.root / "work/poll"

    def run_api(self, responses, directory=None):
        api, opener = client(responses)
        with patch.dict(os.environ, {"NEWS_GMAIL_TRANSPORT": "gmail_api"}), \
             patch.object(gmail_api.GmailApiClient, "from_env", return_value=api), \
             patch.object(v11_runtime, "codex", side_effect=AssertionError("API transport must not invoke Codex")):
            result = v11_mail_worker.run(self.root, {"gmail_evidence_attempts": 1}, directory or self.directory)
        return result, opener

    def test_env_selects_api_preserving_collector_only_ingestion_and_audit(self):
        result, _ = self.run_api([{"messages": [{"id": "new"}]}, message()])
        self.assertEqual(result["status"], "ready_for_collector")
        self.assertFalse(result["stats"]["ingestion_cursor_advanced"])
        self.assertIsNotNone(gmail_scan.cached_body_evidence(self.root, "new"))
        scan = json.loads(Path(result["scan_file"]).read_text())
        self.assertEqual(scan["search_tool"], "gmail_api_messages_list")
        self.assertTrue(scan["tool_evidence_files"])
        with sqlite3.connect(self.root / "work/rss-news-monitor.db") as connection:
            connection.execute("INSERT INTO newsletter_messages VALUES ('new')")
        self.assertTrue(v11_mail_worker.finalize(self.root, result["scan_file"])["advanced"])
        self.assertTrue(gmail_run_check.check(scan, int(time.time()), {"new"}, int(time.time()), self.root)
                        ["gmail_ingestion_evidence_complete"])

    def test_partial_pagination_keeps_body_but_never_advances_cursor(self):
        result, _ = self.run_api([{"messages": [{"id": "new"}], "nextPageToken": "p2"},
                                  URLError("page unavailable"), message()])
        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["stats"]["search_cursor_advanced"])
        self.assertFalse((self.root / "work/gmail-scan-state.json").exists())
        self.assertEqual(gmail_scan._queue(self.root)["searched_through_epoch"], 0)
        self.assertIsNotNone(gmail_scan.cached_body_evidence(self.root, "new"))
        next_result, opener = self.run_api([{"messages": [{"id": "new"}]}], self.root / "work/next-poll")
        self.assertEqual(next_result["status"], "ready_for_collector")
        self.assertEqual(next_result["stats"]["cached_body_reuse"], 1)
        self.assertEqual(len(opener.requests), 2)

    def test_complete_search_missing_body_queues_without_ingestion(self):
        result, _ = self.run_api([{"messages": [{"id": "new"}]}, URLError("body unavailable")])
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["stats"]["missing_full_bodies"], 1)
        self.assertFalse(result["stats"]["ingestion_cursor_advanced"])
        self.assertIn("new", gmail_scan._queue(self.root)["pending_messages"])
        self.assertFalse((self.root / "work/gmail-scan-state.json").exists())

    def test_windows_cache_and_pending_scan_resolve_without_rewriting_evidence(self):
        result, _ = self.run_api([{"messages": [{"id": "new"}]}, message()])
        body_file = self.root / "work/gmail-body-cache/new.json"
        body_before = body_file.read_bytes()
        scan_file = Path(result["scan_file"])
        scan_before = scan_file.read_bytes()
        queue_file = self.root / "work/gmail-staging-state.json"
        queue = json.loads(queue_file.read_text())
        queue["pending_messages"]["new"]["body_file"] = r"D:\News Bot\work\gmail-body-cache\new.json"
        queue_file.write_text(json.dumps(queue))
        queue_before = queue_file.read_bytes()
        with patch.dict(os.environ, {"NEWS_LEGACY_ROOT": r"D:\News Bot"}):
            evidence = gmail_scan.cached_body_evidence(self.root, "new")
            self.assertEqual(evidence["body_file"], str(body_file.resolve()))
            with sqlite3.connect(self.root / "work/rss-news-monitor.db") as connection:
                connection.execute("INSERT INTO newsletter_messages VALUES ('new')")
            final = v11_mail_worker.finalize(self.root, r"D:\News Bot\work\poll\scan.json")
        self.assertTrue(final["advanced"])
        self.assertEqual(body_file.read_bytes(), body_before)
        self.assertEqual(scan_file.read_bytes(), scan_before)
        self.assertEqual(queue_file.read_bytes(), queue_before)

    @unittest.skipIf(os.name == "nt", "Cloud persistent volume uses a Linux symlink")
    def test_migrated_cache_resolves_through_persistent_work_symlink(self):
        self.run_api([{"messages": [{"id": "new"}]}, message()])
        queue_file = self.root / "work/gmail-staging-state.json"
        queue = json.loads(queue_file.read_text())
        queue["pending_messages"]["new"]["body_file"] = r"D:\News Bot\work\gmail-body-cache\new.json"
        queue_file.write_text(json.dumps(queue))
        project = self.root / "container-app"
        project.mkdir()
        (project / "work").symlink_to(self.root / "work", target_is_directory=True)
        with patch.dict(os.environ, {"NEWS_LEGACY_ROOT": r"D:\News Bot", "NEWS_DATA_DIR": str(self.root)}):
            evidence = gmail_scan.cached_body_evidence(project, "new")
        self.assertIsNotNone(evidence)
        self.assertEqual(evidence["body_file"], str((self.root / "work/gmail-body-cache/new.json").resolve()))


if __name__ == "__main__":
    unittest.main()
