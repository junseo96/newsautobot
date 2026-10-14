"""Deterministic, read-only Gmail transport for an unattended cloud worker.

Use a Google OAuth refresh token authorized with gmail.readonly. Credentials are
read only from NEWS_GMAIL_CLIENT_ID, NEWS_GMAIL_CLIENT_SECRET and
NEWS_GMAIL_REFRESH_TOKEN; they are never included in evidence or error messages.
OAuth uses a POST to Google's fixed token endpoint. Mail access is GET-only.
"""
from __future__ import annotations

import base64
import copy
from http.client import HTTPException
import json
import os
from pathlib import Path
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

import gmail_scan
import v11_runtime

SEARCH_SOURCE = "gmail_api_messages_list"
API_ROOT = "https://gmail.googleapis.com/gmail/v1/users/me/messages"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REQUIRED_ENV = ("NEWS_GMAIL_CLIENT_ID", "NEWS_GMAIL_CLIENT_SECRET", "NEWS_GMAIL_REFRESH_TOKEN")
MESSAGE_ID = re.compile(r"[A-Za-z0-9_-]{1,256}\Z")
MAX_RESPONSE_BYTES = 32 * 1024 * 1024


class GmailApiError(RuntimeError):
    """A fixed diagnostic code, never upstream content, URLs, or credentials."""

    def __init__(self, code, status=None):
        self.code, self.status = code, status
        super().__init__(code + (f" (HTTP {status})" if status is not None else ""))


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def _valid_id(value):
    return isinstance(value, str) and MESSAGE_ID.fullmatch(value) is not None


class GmailApiClient:
    def __init__(self, client_id, client_secret, refresh_token, *, opener=None, timeout=30):
        if any(not isinstance(value, str) or not value.strip()
               for value in (client_id, client_secret, refresh_token)):
            raise GmailApiError("MissingGmailOAuthCredentials")
        self._client_id, self._client_secret, self._refresh_token = client_id, client_secret, refresh_token
        # urllib's default HTTPS handler verifies certificates and hostnames.
        # Do not allow any redirects, including same-origin credential forwarding.
        self._opener = opener if opener is not None else build_opener(_NoRedirect())
        self._timeout = timeout
        self._access_token, self._expires_at = None, 0

    @classmethod
    def from_env(cls):
        return cls(*(os.environ.get(name, "") for name in REQUIRED_ENV))

    def _request(self, request):
        try:
            with self._opener.open(request, timeout=self._timeout) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise GmailApiError("GmailResponseTooLarge")
            result = json.loads(raw.decode("utf-8"))
        except HTTPError as error:
            # Never read or stringify HTTP error bodies: OAuth errors may echo
            # credentials and Gmail errors may include private message content.
            status = error.code
            error.close()
            raise GmailApiError("GmailHttpError", status) from None
        except (URLError, OSError, TimeoutError, HTTPException):
            raise GmailApiError("GmailConnectionFailed") from None
        except (UnicodeError, ValueError, RecursionError):
            raise GmailApiError("InvalidGmailJsonResponse") from None
        if not isinstance(result, dict):
            raise GmailApiError("InvalidGmailResponse")
        return result

    def _token(self):
        if self._access_token and time.monotonic() < self._expires_at:
            return self._access_token
        body = urlencode({"grant_type": "refresh_token", "client_id": self._client_id,
                          "client_secret": self._client_secret, "refresh_token": self._refresh_token}).encode()
        response = self._request(Request(TOKEN_URL, data=body, method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"}))
        token = response.get("access_token")
        token_type = response.get("token_type", "Bearer")
        expiry = response.get("expires_in", 3600)
        if (not isinstance(token, str) or not token or "\n" in token or "\r" in token
                or not isinstance(token_type, str) or token_type.lower() != "bearer"
                or not isinstance(expiry, (int, float)) or isinstance(expiry, bool) or expiry <= 0):
            raise GmailApiError("InvalidGmailOAuthResponse")
        self._access_token = token
        self._expires_at = time.monotonic() + max(0, min(expiry, 86400) - 30)
        return token

    def _get(self, suffix="", parameters=None):
        url = API_ROOT + suffix
        if parameters:
            url += "?" + urlencode(parameters)
        for attempt in range(2):
            request = Request(url, method="GET", headers={
                "Authorization": "Bearer " + self._token(), "Accept": "application/json"})
            try:
                return self._request(request)
            except GmailApiError as error:
                if error.status != 401 or attempt:
                    raise
                self._access_token, self._expires_at = None, 0
        raise GmailApiError("GmailAuthenticationFailed")

    def list_messages(self, query, page_token=None):
        parameters = {"q": query, "maxResults": 100}
        if page_token is not None:
            parameters["pageToken"] = page_token
        return self._get(parameters=parameters)

    def get_message(self, message_id):
        if not _valid_id(message_id):
            raise GmailApiError("InvalidGmailMessageId")
        message = self._get("/" + quote(message_id, safe=""), {"format": "full"})
        if message.get("id") != message_id or not isinstance(message.get("payload"), dict):
            raise GmailApiError("GmailMessageIdentityMismatch")
        message = copy.deepcopy(message)
        self._hydrate(message_id, message["payload"])
        if not gmail_scan._full_mime_payload(message["payload"]):
            raise GmailApiError("MissingFullGmailMime")
        return message

    def _hydrate(self, message_id, part):
        if not isinstance(part, dict):
            raise GmailApiError("InvalidGmailMime")
        body = part.get("body")
        mime = part.get("mimeType", "")
        if not isinstance(mime, str):
            raise GmailApiError("InvalidGmailMime")
        if isinstance(body, dict):
            if "size" in body and (type(body["size"]) is not int or body["size"] < 0):
                raise GmailApiError("InvalidGmailMimeSize")
            attachment_id = body.get("attachmentId")
            if mime.lower().startswith("text/") and attachment_id:
                if not _valid_id(attachment_id):
                    # Gmail attachment IDs can be longer than message IDs.
                    if (not isinstance(attachment_id, str) or len(attachment_id) > 4096
                            or re.fullmatch(r"[A-Za-z0-9_-]+", attachment_id) is None):
                        raise GmailApiError("InvalidGmailAttachmentId")
                attachment = self._get("/" + quote(message_id, safe="") + "/attachments/"
                                       + quote(attachment_id, safe=""))
                if not isinstance(attachment.get("data"), str):
                    raise GmailApiError("MissingGmailTextAttachment")
                if (isinstance(body.get("size"), int) and isinstance(attachment.get("size"), int)
                        and body["size"] != attachment["size"]):
                    raise GmailApiError("GmailAttachmentSizeMismatch")
                body.update(data=attachment["data"], size=attachment.get("size", body.get("size")),
                            resolvedAttachmentId=attachment_id)
                del body["attachmentId"]
            if "data" in body:
                data = body["data"]
                if not isinstance(data, str):
                    raise GmailApiError("InvalidGmailMimeEncoding")
                try:
                    raw = base64.b64decode(data + "=" * (-len(data) % 4), altchars=b"-_", validate=True)
                except (ValueError, UnicodeError):
                    raise GmailApiError("InvalidGmailMimeEncoding") from None
                if type(body.get("size")) is int and len(raw) != body["size"]:
                    raise GmailApiError("GmailMimeSizeMismatch")
        parts = part.get("parts")
        if parts is not None:
            if not isinstance(parts, list):
                raise GmailApiError("InvalidGmailMime")
            for child in parts:
                self._hydrate(message_id, child)


def _page(response):
    messages = response.get("messages")
    # Gmail omits `messages` for an empty mailbox result, but returns an estimate.
    if (messages is None and type(response.get("resultSizeEstimate")) is int
            and response["resultSizeEstimate"] == 0 and not response.get("nextPageToken")):
        messages = []
    if (not isinstance(messages, list)
            or any(not isinstance(message, dict) or not _valid_id(message.get("id")) for message in messages)):
        raise GmailApiError("InvalidGmailSearchResults")
    token = response.get("nextPageToken")
    if token is not None and (not isinstance(token, str) or len(token) > 4096):
        raise GmailApiError("InvalidGmailPageToken")
    return {message["id"] for message in messages}, token or None


def collect(query, known_ids, cached_ids, queued_ids, directory, *, attempts=2, client=None):
    """Return real REST evidence, preserving partial pages and successful bodies.

    The worker owns durable queue/cache commits. Search completion is only true
    after a validated final page. Retried body failures never restart the search
    or discard successful reads, and ingestion still requires collector commit.
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    search = {"pagination_complete": False, "message_ids": [], "page_count": 0, "next_page_token": None}
    captured, failures, evidence_files = {}, [], []
    known, cached, queued = set(known_ids), set(cached_ids), set(queued_ids)
    try:
        client = client if client is not None else GmailApiClient.from_env()
    except GmailApiError as error:
        return {"search": search, "captured": {}, "failures": [{"stage": "transport", "error_type": error.code}],
                "evidence_files": []}
    ids, visited, loop = set(), set(), False
    for attempt in range(max(1, min(3, int(attempts)))):
        while not search["pagination_complete"] and not loop:
            token = search["next_page_token"]
            try:
                response = client.list_messages(query, token)
                page_ids, next_token = _page(response)
            except GmailApiError as error:
                failures.append({"stage": "search", "attempt": attempt + 1, "error_type": error.code})
                break
            path = directory / (f"page-{search['page_count'] + 1:06d}.json")
            v11_runtime.save_json(path, {"provider": "gmail_api", "operation": "users.messages.list",
                "query": query, "page_token": token, "response": response})
            evidence_files.append(str(path.resolve()))
            ids.update(page_ids)
            visited.add(token)
            search.update(message_ids=sorted(ids), page_count=search["page_count"] + 1,
                          next_page_token=next_token, pagination_complete=next_token is None)
            if next_token is not None and next_token in visited:
                loop = True
                failures.append({"stage": "search", "error_type": "GmailPaginationLoop"})
        for message_id in sorted((ids | queued) - known - cached - set(captured)):
            try:
                if not _valid_id(message_id):
                    raise GmailApiError("InvalidGmailMessageId")
                message = client.get_message(message_id)
                if (message.get("id") != message_id
                        or not gmail_scan._full_mime_payload(message.get("payload"))):
                    raise GmailApiError("MissingMatchingFullGmailMime")
            except GmailApiError as error:
                failures.append({"stage": "body", "attempt": attempt + 1, "message_id": message_id,
                                 "error_type": error.code})
                continue
            envelope = {"message_id": message_id, "body_complete": True, "message": message,
                        "provider": "gmail_api", "format": "full"}
            path = directory / ("body-" + message_id + ".json")
            v11_runtime.save_json(path, envelope)
            evidence_files.append(str(path.resolve()))
            captured[message_id] = envelope
        if search["pagination_complete"] and not ((ids | queued) - known - cached - set(captured)):
            break
    return {"search": search, "captured": captured, "failures": failures, "evidence_files": evidence_files}
