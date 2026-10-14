"""Read-only remote credential checks, independent of restored operational state.

Run ``python deploy/cloud/probe.py`` or select repeatable ``--check NAME``.
Only generic pass/fail results are printed. No mail bodies are retrieved and no
Telegram messages, dashboard events, or DART data are written. Gmail's OAuth
token exchange and a minimal billed model response are the only POST requests.
The model check logs in through the container's normal Codex credential store
and uses temporary output files. A successful Telegram check verifies access,
not permission to send.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import re
import ssl
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

import worker

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / "outputs/rss-news-monitor"))
from gmail_api import GmailApiClient, _page as gmail_page
from grid_bridge import _bridge_url

MAX_RESPONSE_BYTES = 2 * 1024 * 1024
REQUIREMENTS = {
    "gmail": ("NEWS_GMAIL_CLIENT_ID", "NEWS_GMAIL_CLIENT_SECRET", "NEWS_GMAIL_REFRESH_TOKEN"),
    "telegram": ("NEWS_TELEGRAM_BOT_TOKEN", "NEWS_TELEGRAM_CHAT_ID"),
    "dart": ("NEWS_DART_KEY",),
    "dashboard": ("NEWS_GRID_URL", "NEWS_GRID_TOKEN"),
    "model": ("NEWS_CODEX_API_KEY",),
}


class ProbeError(RuntimeError):
    """Never contains credential values, endpoint URLs, or upstream content."""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def _get_json(url, headers=None):
    opener = build_opener(_NoRedirect(), HTTPSHandler(context=ssl.create_default_context()))
    request = Request(url, method="GET", headers={"Accept": "application/json", **(headers or {})})
    try:
        with opener.open(request, timeout=30) as response:
            if response.status != 200:
                raise ProbeError("Unexpected response")
            raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ProbeError("Response too large")
        result = json.loads(raw.decode("utf-8"))
        if not isinstance(result, dict):
            raise ProbeError("Invalid response")
        return result
    except HTTPError as error:
        error.close()
        raise ProbeError("Request failed") from None
    except Exception:
        raise ProbeError("Request failed") from None


def probe_gmail():
    now = int(time.time())
    response = GmailApiClient.from_env().list_messages(f"after:{now - 3600} before:{now}")
    gmail_page(response)  # Validate IDs only; do not paginate or fetch bodies.


def probe_telegram():
    token, chat_id = (os.environ[name] for name in REQUIREMENTS["telegram"])
    if not re.fullmatch(r"[0-9]+:[A-Za-z0-9_-]+", token):
        raise ProbeError("Invalid credential format")
    base = "https://api.telegram.org/bot" + quote(token, safe=":")
    bot = _get_json(base + "/getMe")
    if (bot.get("ok") is not True or not isinstance(bot.get("result"), dict)
            or type(bot["result"].get("id")) is not int or bot["result"].get("is_bot") is not True):
        raise ProbeError("Bot access failed")
    chat = _get_json(base + "/getChat?" + urlencode({"chat_id": chat_id}))
    if (chat.get("ok") is not True or not isinstance(chat.get("result"), dict)
            or type(chat["result"].get("id")) is not int
            or chat["result"].get("type") not in {"private", "group", "supergroup", "channel"}):
        raise ProbeError("Chat access failed")
    if re.fullmatch(r"-?[0-9]+", chat_id) and int(chat_id) != chat["result"]["id"]:
        raise ProbeError("Chat identity mismatch")


def probe_dart():
    today = dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).strftime("%Y%m%d")
    query = urlencode({"crtfc_key": os.environ["NEWS_DART_KEY"], "bgn_de": today,
                       "end_de": today, "page_no": 1, "page_count": 1})
    response = _get_json("https://opendart.fss.or.kr/api/list.json?" + query)
    if response.get("status") not in {"000", "013"}:
        raise ProbeError("DART access failed")


def probe_dashboard():
    url = _bridge_url(os.environ["NEWS_GRID_URL"])
    token = os.environ["NEWS_GRID_TOKEN"]
    if any(character in token for character in "\r\n"):
        raise ProbeError("Invalid credential format")
    response = _get_json(url + "/api/newsflow?limit=1", {"OAI-Sites-Authorization": "Bearer " + token})
    events = response.get("events")
    if (not isinstance(events, list) or len(events) > 1
            or any(not isinstance(event, dict) or not isinstance(event.get("id"), str)
                   or not event["id"] for event in events)):
        raise ProbeError("Invalid dashboard response")


def probe_model():
    config = json.loads((PROJECT / "outputs/rss-news-monitor/runtime-v12.json").read_text(encoding="utf-8"))
    model = os.environ.get("NEWS_MODEL", "").strip() or config["model"]
    with tempfile.TemporaryDirectory(prefix="news-auth-probe-") as scratch:
        directory = Path(scratch)
        schema, output = directory / "schema.json", directory / "response.json"
        schema.write_text(json.dumps({"type": "object", "properties": {"ok": {"type": "boolean", "enum": [True]}},
                                      "required": ["ok"], "additionalProperties": False}), encoding="utf-8")
        worker.authenticate_model()
        command = ["codex", "exec", "--ignore-user-config", "--skip-git-repo-check", "--ephemeral",
                   "-C", str(directory), "-s", "read-only", "-m", model, "--json",
                   "--output-schema", str(schema), "-o", str(output)]
        settings = ["web_search=\"disabled\"", "project_doc_max_bytes=0", "model_reasoning_effort=\"low\""]
        settings.extend("features." + feature + "=false" for feature in (
            "shell_tool", "multi_agent", "browser_use", "computer_use", "image_generation",
            "plugins", "apps", "memories", "hooks", "daemon_auto_start", "code_mode", "code_mode_host"))
        for setting in settings:
            command.extend(["-c", setting])
        command.append("-")
        environment = {name: value for name, value in os.environ.items() if not name.startswith("NEWS_")}
        completed = subprocess.run(command, input='Return exactly {"ok":true}. Do not use any tools or access files or websites.',
                                   text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   cwd=directory, env=environment, timeout=120)
        if completed.returncode or not output.is_file() or output.stat().st_size > 1024:
            raise ProbeError("Model access failed")
        events = [json.loads(line) for line in completed.stdout.splitlines() if line.strip()]
        if not any(event.get("type") == "turn.completed" for event in events):
            raise ProbeError("Model request did not complete")
        if any(event.get("type") in {"item.started", "item.completed"}
               and event.get("item", {}).get("type") not in {"agent_message", "reasoning"} for event in events):
            raise ProbeError("Model attempted a tool call")
        if json.loads(output.read_text(encoding="utf-8")) != {"ok": True}:
            raise ProbeError("Invalid model response")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="append", choices=tuple(REQUIREMENTS), help="Check only the selected integration; repeatable")
    arguments = parser.parse_args(argv)
    checks = {"gmail": probe_gmail, "telegram": probe_telegram, "dart": probe_dart,
              "dashboard": probe_dashboard, "model": probe_model}
    failed = False
    for name in dict.fromkeys(arguments.check or REQUIREMENTS):
        missing = [variable for variable in REQUIREMENTS[name] if not os.environ.get(variable, "").strip()]
        if missing:
            print(name + ": failed (missing " + ", ".join(missing) + ")", flush=True)
            failed = True
            continue
        try:
            checks[name]()
        except Exception:
            # Never render exception text: requests/process errors can contain
            # authentication headers, URLs with tokens, or private response data.
            print(name + ": failed (authentication or connectivity check)", flush=True)
            failed = True
        else:
            print(name + ": passed", flush=True)
    return 2 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
