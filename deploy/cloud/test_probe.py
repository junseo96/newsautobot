"""Mocked authentication checks; no real provider request or model invocation."""
import contextlib
import io
import json
import os
from pathlib import Path
import ssl
import subprocess
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit
from urllib.request import HTTPSHandler

import probe
import gmail_api


class Response:
    status = 200

    def __init__(self, value):
        self.data = json.dumps(value).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self, size):
        return self.data[:size]


class Opener:
    def __init__(self, values):
        self.values = iter(values)
        self.requests = []

    def open(self, request, timeout):
        self.requests.append(request)
        assert 0 < timeout <= 30
        result = next(self.values)
        if isinstance(result, Exception):
            raise result
        return Response(result)


class CredentialProbeTests(unittest.TestCase):
    def setUp(self):
        self.environment = {name: "synthetic-secret-" + name for names in probe.REQUIREMENTS.values() for name in names}
        self.environment.update(NEWS_TELEGRAM_BOT_TOKEN="123456:private_bot_secret",
                                NEWS_TELEGRAM_CHAT_ID="-10012345", NEWS_GRID_URL="https://dashboard.example/project")
        self.addCleanup(patch.stopall)
        patch.dict(os.environ, self.environment, clear=True).start()
        patch("urllib.request.OpenerDirector.open", side_effect=AssertionError("Real network is forbidden in tests")).start()
        self.process = patch.object(subprocess, "run", side_effect=AssertionError("Real processes are forbidden in tests")).start()

    def run_check(self, name):
        output, errors = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            code = probe.main(["--check", name])
        for secret in self.environment.values():
            self.assertNotIn(secret, output.getvalue() + errors.getvalue())
        self.assertEqual(errors.getvalue(), "")
        return code, output.getvalue()

    def test_gmail_only_lists_ids_using_get_and_narrow_query(self):
        opener = Opener([{"access_token": "private_access_token", "expires_in": 3600},
                         {"messages": [{"id": "private_message_id"}], "resultSizeEstimate": 1}])
        with patch.object(gmail_api, "build_opener", return_value=opener), patch.object(probe.time, "time", return_value=2000000000):
            self.assertEqual(self.run_check("gmail"), (0, "gmail: passed\n"))
        self.assertEqual([request.get_method() for request in opener.requests], ["POST", "GET"])
        self.assertEqual(opener.requests[0].full_url, gmail_api.TOKEN_URL)
        listing = opener.requests[1]
        self.assertEqual(urlsplit(listing.full_url).path, "/gmail/v1/users/me/messages")
        query = parse_qs(urlsplit(listing.full_url).query)
        self.assertEqual(query["q"], ["after:1999996400 before:2000000000"])
        self.assertNotIn("format", query)
        self.assertIsNone(listing.data)

    def test_gmail_bad_credentials_fail_without_response_disclosure(self):
        error = HTTPError("https://example.invalid/private_token", 401, "private error body", {}, io.BytesIO(b"private refresh token"))
        with patch.object(gmail_api, "build_opener", return_value=Opener([error])):
            self.assertEqual(self.run_check("gmail"), (2, "gmail: failed (authentication or connectivity check)\n"))

    def test_telegram_only_reads_bot_and_chat_and_verifies_tls(self):
        opener = Opener([{"ok": True, "result": {"id": 123456, "is_bot": True, "username": "private_bot_name"}},
                         {"ok": True, "result": {"id": -10012345, "type": "channel", "title": "private channel title"}}])
        with patch.object(probe, "build_opener", return_value=opener) as factory:
            self.assertEqual(self.run_check("telegram"), (0, "telegram: passed\n"))
        self.assertEqual([request.get_method() for request in opener.requests], ["GET", "GET"])
        self.assertTrue(opener.requests[0].full_url.endswith("/getMe"))
        self.assertIn("/getChat?", opener.requests[1].full_url)
        self.assertTrue(all(request.data is None for request in opener.requests))
        for call in factory.call_args_list:
            handler = next(handler for handler in call.args if isinstance(handler, HTTPSHandler))
            self.assertEqual(handler._context.verify_mode, ssl.CERT_REQUIRED)
            self.assertTrue(handler._context.check_hostname)

    def test_telegram_wrong_chat_and_api_errors_fail(self):
        for reply in ({"ok": False, "description": "private token failure"},
                      {"ok": True, "result": {"id": -999, "type": "channel"}}):
            with self.subTest(reply=reply), patch.object(probe, "build_opener", return_value=Opener([
                    {"ok": True, "result": {"id": 123456, "is_bot": True}}, reply])):
                self.assertEqual(self.run_check("telegram")[0], 2)

    def test_dart_accepts_empty_today_result_and_limits_page(self):
        for status in ("000", "013"):
            opener = Opener([{"status": status}])
            with self.subTest(status=status), patch.object(probe, "build_opener", return_value=opener):
                self.assertEqual(self.run_check("dart"), (0, "dart: passed\n"))
            request = opener.requests[0]
            self.assertEqual(request.get_method(), "GET")
            query = parse_qs(urlsplit(request.full_url).query)
            self.assertEqual(query["bgn_de"], query["end_de"])
            self.assertEqual(query["page_count"], ["1"])

    def test_dart_rejected_key_fails_generically(self):
        with patch.object(probe, "build_opener", return_value=Opener([{"status": "010", "message": "private key"}])):
            self.assertEqual(self.run_check("dart"), (2, "dart: failed (authentication or connectivity check)\n"))

    def test_dashboard_uses_authenticated_get_and_checks_shape(self):
        opener = Opener([{"events": [{"id": "private_event_id"}], "total": 100}])
        with patch.object(probe, "build_opener", return_value=opener):
            self.assertEqual(self.run_check("dashboard"), (0, "dashboard: passed\n"))
        request = opener.requests[0]
        self.assertEqual(request.full_url, "https://dashboard.example/project/api/newsflow?limit=1")
        self.assertEqual(request.get_method(), "GET")
        self.assertIsNone(request.data)
        self.assertEqual(request.get_header("Oai-sites-authorization"), "Bearer " + self.environment["NEWS_GRID_TOKEN"])
        with patch.object(probe, "build_opener", return_value=Opener([{"events": "private malformed response"}])):
            self.assertEqual(self.run_check("dashboard")[0], 2)

    def test_http_redirects_never_follow_or_disclose_credentials(self):
        self.assertIsNone(probe._NoRedirect().redirect_request(None, None, 302, "", {}, "https://elsewhere.example"))
        error = HTTPError("https://example.invalid/private-secret", 302, "private-message", {}, io.BytesIO(b"private body"))
        with patch.object(probe, "build_opener", return_value=Opener([error])):
            self.assertEqual(self.run_check("dashboard"), (2, "dashboard: failed (authentication or connectivity check)\n"))

    def test_missing_environment_reports_only_names_and_skips_request(self):
        os.environ.pop("NEWS_GRID_TOKEN")
        with patch.object(probe, "build_opener") as factory:
            self.assertEqual(self.run_check("dashboard"), (2, "dashboard: failed (missing NEWS_GRID_TOKEN)\n"))
        factory.assert_not_called()

    def test_model_uses_normal_auth_and_no_tools_or_secret_environment(self):
        os.environ["NEWS_MODEL"] = "configured-model"
        invocations = []

        def simulate(command, **kwargs):
            invocations.append((command, kwargs))
            if command[1] == "login":
                self.assertEqual(kwargs["input"], self.environment["NEWS_CODEX_API_KEY"] + "\n")
                return subprocess.CompletedProcess(command, 0, "private login output", "private stderr")
            output = Path(command[command.index("-o") + 1])
            output.write_text('{"ok":true}')
            return subprocess.CompletedProcess(command, 0, '{"type":"turn.completed"}\n', "private stderr")

        self.process.side_effect = simulate
        self.assertEqual(self.run_check("model"), (0, "model: passed\n"))
        self.assertNotIn("CODEX_HOME", os.environ)
        self.assertEqual(len(invocations), 2)
        command, kwargs = invocations[1]
        self.assertFalse(Path(kwargs["cwd"]).exists())
        for setting in ("--ignore-user-config", "--ephemeral", "read-only", "--output-schema",
                        'web_search="disabled"', "features.shell_tool=false", "features.apps=false", "features.plugins=false"):
            self.assertIn(setting, command)
        self.assertIn("configured-model", command)
        self.assertFalse(any(name.startswith("NEWS_") for name in kwargs["env"]))
        self.assertEqual(kwargs["stdout"], subprocess.PIPE)
        self.assertEqual(kwargs["stderr"], subprocess.PIPE)
        self.assertEqual(kwargs["timeout"], 120)
        self.assertTrue(all(self.environment["NEWS_CODEX_API_KEY"] not in str(call[0]) for call in invocations))

    def test_model_login_failure_is_captured_without_environment_changes(self):
        self.process.return_value = subprocess.CompletedProcess(["codex"], 1, "private key echoed", "private secret")
        self.process.side_effect = None
        self.assertEqual(self.run_check("model"), (2, "model: failed (authentication or connectivity check)\n"))
        self.assertNotIn("CODEX_HOME", os.environ)
        self.assertEqual(self.process.call_count, 1)

    def test_model_tool_attempt_cannot_be_reported_as_success(self):
        def simulate(command, **kwargs):
            if command[1] == "login":
                return subprocess.CompletedProcess(command, 0, "", "")
            Path(command[command.index("-o") + 1]).write_text('{"ok":true}')
            events = [{"type": "item.started", "item": {"type": "command_execution"}}, {"type": "turn.completed"}]
            return subprocess.CompletedProcess(command, 0, "\n".join(map(json.dumps, events)), "")

        self.process.side_effect = simulate
        self.assertEqual(self.run_check("model")[0], 2)


if __name__ == "__main__":
    unittest.main()
