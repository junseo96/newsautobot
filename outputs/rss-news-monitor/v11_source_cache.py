"""Public article text cache for review workers; fetching never marks reviewed."""
from __future__ import annotations

import datetime as dt
import hashlib
import http.client
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import ssl
import tempfile
import time
from html.parser import HTMLParser
import urllib.error
import urllib.parse
import urllib.request

MAX_BYTES = 2 * 1024 * 1024
TIMEOUT = 15
FAILURE_TTL = 15 * 60
USER_AGENT = "Mozilla/5.0 (compatible; Newsflow/11.0; public article review)"
_CACHE_VERSION = 2
TRACKING_RESOLVER_VERSION = 1
MAX_DOCUMENT_REDIRECTS = 2
_DOCUMENT_TRACKING_HOSTS = {'hello.canarymedia.com'}
_BLOCKED_ACTION = re.compile(
    r"(?:^|[/&?=;_\s-])(?:unsubscribe|unsub|optout|opt[-_]out|logout|"
    r"login|signin|sign[-_]in|admin|account|profile|preferences|settings|"
    r"manage[-_]?(?:subscriptions?|preferences)|change[-_]?(?:email|password))"
    r"(?:$|[/&?=;_\s-])", re.I)


class PublicSourceError(ValueError):
    """A safe error code: never include request credentials or response bodies."""


def _validate_url(url):
    if not isinstance(url, str) or len(url) > 8192 or re.search(r"[\x00-\x20\x7f]", url):
        raise PublicSourceError("invalid_url")
    try:
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            raise PublicSourceError("public_http_url_required")
        if parsed.username is not None or parsed.password is not None:
            raise PublicSourceError("url_credentials_forbidden")
        if parsed.port not in {None, 80, 443} or "%" in parsed.hostname:
            raise PublicSourceError("nonstandard_endpoint_forbidden")
    except ValueError as error:
        if isinstance(error, PublicSourceError):
            raise
        raise PublicSourceError("invalid_url") from None
    target = parsed.path + "?" + parsed.query
    for _ in range(3):
        target = urllib.parse.unquote(target)
    if _BLOCKED_ACTION.search(target):
        raise PublicSourceError("account_or_unsubscribe_url_forbidden")
    path = urllib.parse.unquote(parsed.path).lower().rstrip('/')
    if re.search(r'/(?:privacy(?:-policy|-notice)?|terms(?:-of-use|-of-service|-and-conditions)?|subscribe|donate)$', path):
        raise PublicSourceError('non_article_utility_url_forbidden')
    host = parsed.hostname.lower().removeprefix('www.').rstrip('.')
    if host in {'facebook.com', 'linkedin.com', 'twitter.com', 'x.com'} and re.match(
            r'^/(?:sharer(?:\.php)?|sharing|share|intent)(?:/|$)', path):
        raise PublicSourceError('social_share_url_forbidden')
    query_keys = {key.lower() for key, _ in urllib.parse.parse_qsl(parsed.query)}
    if query_keys & {"password", "passwd", "api_key", "apikey", "access_token", "authorization"}:
        raise PublicSourceError("credential_query_forbidden")
    return urllib.parse.urlunsplit((parsed.scheme.lower(), parsed.netloc, parsed.path or "/", parsed.query, ""))


def _public_addresses(host, port):
    """Check every answer and return the exact addresses used for connecting."""
    answers = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    if not answers:
        raise PublicSourceError("dns_no_addresses")
    for _, _, _, _, address in answers:
        try:
            ip = ipaddress.ip_address(address[0])
        except ValueError:
            raise PublicSourceError("invalid_dns_address") from None
        ip = getattr(ip, "ipv4_mapped", None) or ip
        if not ip.is_global or ip.is_multicast or ip.is_reserved:
            raise PublicSourceError("nonpublic_address_forbidden")
    return answers


def _public_socket(host, port, timeout):
    # Connect to the vetted sockaddr, not the hostname (no second DNS lookup).
    answers = _public_addresses(host, port)
    last_error = None
    for family, socktype, proto, _, address in answers:
        connection = socket.socket(family, socktype, proto)
        try:
            connection.settimeout(timeout)
            connection.connect(address)
            return connection
        except OSError as error:
            last_error = error
            connection.close()
    raise last_error or PublicSourceError("connection_failed")


class _PublicHTTPConnection(http.client.HTTPConnection):
    def connect(self):
        if self._tunnel_host:
            raise PublicSourceError("proxy_tunnel_forbidden")
        self.sock = _public_socket(self.host, self.port, self.timeout)


class _PublicHTTPSConnection(http.client.HTTPSConnection):
    def connect(self):
        if self._tunnel_host:
            raise PublicSourceError("proxy_tunnel_forbidden")
        connection = _public_socket(self.host, self.port, self.timeout)
        try:
            self.sock = self._context.wrap_socket(connection, server_hostname=self.host)
        except Exception:
            connection.close()
            raise


class _PublicHTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, request):
        return self.do_open(_PublicHTTPConnection, request)


class _PublicHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, request):
        return self.do_open(_PublicHTTPSConnection, request, context=self._context)


class _PublicRedirectHandler(urllib.request.HTTPRedirectHandler):
    max_repeats = 3
    max_redirections = 5

    def redirect_request(self, request, fp, code, message, headers, newurl):
        validated = _validate_url(newurl)
        # The connection handler vets and pins DNS again for each redirect hop.
        return super().redirect_request(request, fp, code, message, headers, validated)


def _opener():
    # Do not inherit environment proxies, cookies, HTTP auth, or user sessions.
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({}), _PublicHTTPHandler(),
        _PublicHTTPSHandler(context=ssl.create_default_context()), _PublicRedirectHandler())


def _document_tracker(url):
    return (urllib.parse.urlsplit(url).hostname or '').lower().rstrip('.') in _DOCUMENT_TRACKING_HOSTS


class _VisibleRedirectHTML(HTMLParser):
    """Only visible HTML links; script strings and JavaScript are never used."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ignored = 0
        self.text = []
        self.anchors = []
        self.anchor = None
        self.label = []

    def handle_starttag(self, tag, attrs):
        if tag in {'script', 'style', 'noscript'}:
            self.ignored += 1
        if not self.ignored and tag == 'a':
            self.anchor = dict(attrs).get('href')
            self.label = []

    def handle_endtag(self, tag):
        if tag in {'script', 'style', 'noscript'} and self.ignored:
            self.ignored -= 1
        if not self.ignored and tag == 'a' and self.anchor is not None:
            self.anchors.append((self.anchor, ' '.join(''.join(self.label).split()).lower()))
            self.anchor = None

    def handle_data(self, value):
        if not self.ignored:
            self.text.append(value)
            if self.anchor is not None:
                self.label.append(value)


def _document_redirect(url, document):
    """Follow the one visible fallback on the observed Canary redirect page.

    This is not a generic challenge/JavaScript resolver. No hidden scripts,
    forms, refresh metadata, user session, or arbitrary page links are opened.
    """
    if not _document_tracker(url):
        return None
    parser = _VisibleRedirectHTML()
    parser.feed(document)
    visible = ' '.join(' '.join(parser.text).split()).lower()
    if "you're being redirected" not in visible or "if you're not redirected in a few seconds" not in visible:
        return None
    if len(parser.anchors) != 1 or parser.anchors[0][1] != 'click here':
        raise PublicSourceError('ambiguous_tracking_interstitial')
    return _validate_url(urllib.parse.urljoin(url, parser.anchors[0][0]))


class _ArticleHTML(HTMLParser):
    blocks = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "blockquote", "pre"}
    ignored = {"script", "style", "noscript", "nav", "footer", "header", "form", "svg", "aside", "button"}
    void = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.title_parts = []
        self.parts = []
        self.article_parts = []
        self.main_parts = []
        self.published_at = None
        self.publication_rank = 0
        self.og_title = ""
        self.jsonld = None
        self.structured_body = ""
        self.article_count = 0

    def set_publication(self, value, rank):
        if isinstance(value,str) and value.strip() and rank>self.publication_rank:
            self.published_at=value.strip()
            self.publication_rank=rank

    def append_text(self, value):
        self.parts.append(value)
        if "article" in self.stack:self.article_parts.append(value)
        if "main" in self.stack:self.main_parts.append(value)

    def read_jsonld(self, value):
        if isinstance(value,list):
            for child in value:self.read_jsonld(child)
        elif isinstance(value,dict):
            kinds=value.get("@type",[])
            if isinstance(kinds,str):kinds=[kinds]
            if set(kinds).intersection({"Article","NewsArticle","BlogPosting","Report","TechArticle"}):
                self.set_publication(value.get("datePublished"),3)
                body=value.get("articleBody")
                if isinstance(body,str) and len(body)>len(self.structured_body):self.structured_body=body
            # @graph/mainEntity are structured entities; arbitrary strings in
            # scripts are never executed or used as publication metadata.
            for field in ("@graph","mainEntity"):
                if field in value:self.read_jsonld(value[field])

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'article':
            self.article_count += 1
        if tag == "meta":
            name = (attrs.get("property") or attrs.get("name") or attrs.get("itemprop") or "").lower()
            if name in {"article:published_time", "datepublished", "pubdate", "publishdate", "date"}:
                self.set_publication(attrs.get("content"),4 if name!="date" else 2)
            if name == "og:title":
                self.og_title = attrs.get("content") or ""
        if tag == "time" and attrs.get("datetime"):
            self.set_publication(attrs["datetime"],3 if attrs.get("itemprop","").lower()=="datepublished" else 1)
        if tag == "script" and attrs.get("type","").lower()=="application/ld+json":
            self.jsonld=[]
        if tag not in self.void:
            self.stack.append(tag)
        if tag in self.blocks and not self.ignored.intersection(self.stack):
            self.append_text("\n")

    def handle_endtag(self, tag):
        if tag in self.blocks and not self.ignored.intersection(self.stack):
            self.append_text("\n")
        if tag == "script" and self.jsonld is not None:
            try:self.read_jsonld(json.loads("".join(self.jsonld)))
            except (ValueError,TypeError,RecursionError):pass
            self.jsonld=None
        if tag in self.stack:
            del self.stack[len(self.stack) - 1 - self.stack[::-1].index(tag):]

    def handle_data(self, data):
        if self.jsonld is not None and "script" in self.stack:self.jsonld.append(data)
        if "title" in self.stack and not self.ignored.intersection(self.stack):
            self.title_parts.append(data)
        if self.blocks.intersection(self.stack) and not self.ignored.intersection(self.stack):
            self.append_text(data)

    def result(self):
        title = re.sub(r"\s+", " ", "".join(self.title_parts) or self.og_title).strip()
        preferred = (self.article_parts, self.main_parts, self.parts)
        # Some publisher pages mark related-story cards as <article> but put
        # the actual story in a plain <div> inside <main>. The complete main
        # must win over a handful of card snippets (observed on Canary Media).
        if self.article_count > 1 and len(''.join(self.main_parts)) > max(300, 2 * len(''.join(self.article_parts))):
            preferred = (self.main_parts, self.article_parts, self.parts)
        parts=next((parts for parts in preferred
                    if len("".join(parts).strip())>=100),self.parts)
        body="".join(parts)
        if len(body.strip())<100 and self.structured_body:body=self.structured_body
        lines = [re.sub(r"\s+", " ", line).strip() for line in body.splitlines()]
        # Repeated responsive desktop/mobile paragraphs should not double the
        # worker's source packet. Retain order and every distinct paragraph.
        return title, "\n\n".join(dict.fromkeys(line for line in lines if line)), self.published_at


def _fetch(url):
    current = _validate_url(url)
    opener = _opener()
    visited, provenance = set(), []
    for hop in range(MAX_DOCUMENT_REDIRECTS + 1):
        if current in visited:
            raise PublicSourceError('tracking_redirect_loop')
        visited.add(current)
        request = urllib.request.Request(current, headers={
            "User-Agent": USER_AGENT, "Accept": "text/html, application/xhtml+xml, text/plain;q=0.8",
            "Accept-Encoding": "identity",
        }, method="GET")
        try:
            with opener.open(request, timeout=TIMEOUT) as response:
                final_url = _validate_url(response.geturl())
                length = response.headers.get("Content-Length")
                if length and length.isdigit() and int(length) > MAX_BYTES:
                    raise PublicSourceError("body_too_large")
                body = response.read(MAX_BYTES + 1)
                if len(body) > MAX_BYTES:
                    raise PublicSourceError("body_too_large")
                if (response.headers.get("Content-Encoding") or "identity").lower() != "identity":
                    raise PublicSourceError("encoded_body_unsupported")
                content_type = response.headers.get_content_type()
                charset = response.headers.get_content_charset() or "utf-8"
        except urllib.error.HTTPError as error:
            # Preserve the actual public destination even when its publisher
            # denies access; the reviewer can search that publisher/title.
            final_url = _validate_url(error.geturl())
            return {'final_url': final_url, 'title': '', 'text': '', 'ok': False, 'usable': False,
                    'error': 'http_' + str(error.code), 'redirect_provenance': provenance,
                    'tracking_resolver_version': TRACKING_RESOLVER_VERSION}
        try:
            document = body.decode(charset, errors="replace")
        except LookupError:
            document = body.decode("utf-8", errors="replace")
        target = _document_redirect(final_url, document) if content_type in {'text/html', 'application/xhtml+xml'} else None
        if target is None:
            break
        if hop >= MAX_DOCUMENT_REDIRECTS:
            raise PublicSourceError('tracking_redirect_limit')
        if target in visited or target == final_url:
            raise PublicSourceError('tracking_redirect_loop')
        provenance.append({'from_url': final_url, 'to_url': target, 'method': 'visible_redirect_anchor'})
        current = target
    if content_type in {"text/html", "application/xhtml+xml"}:
        parser = _ArticleHTML()
        parser.feed(document)
        title, text, published_at = parser.result()
    elif content_type == "text/plain":
        title, text, published_at = "", document.strip(), None
    else:
        raise PublicSourceError("unsupported_content_type")
    result = {"final_url": final_url, "title": title, "text": text,
              "content_type": content_type, "ok": True, "usable": True,
              "redirect_provenance": provenance,
              "tracking_resolver_version": TRACKING_RESOLVER_VERSION}
    if published_at:
        result["published_at"] = published_at
        try:
            publication=dt.datetime.fromisoformat(published_at.replace("Z","+00:00"))
            result["publication_precision"]="exact" if publication.tzinfo is not None else "date"
            if publication.tzinfo is None:
                result["publication_raw"]=published_at
                result["published_at"]=publication.date().isoformat()
        except (ValueError,TypeError):
            result["publication_precision"]="unknown"
    host = (urllib.parse.urlsplit(final_url).hostname or "").lower()
    if host == "news.google.com" or _document_tracker(final_url):
        result.update(ok=False, usable=False, error="tracking_destination_unresolved")
    elif len(text) < 100:
        result.update(ok=False, usable=False, error="insufficient_article_text")
    elif any(marker in (title + " " + text[:600]).lower() for marker in (
            "access denied", "just a moment", "verify you are human", "checking your browser",
            "enable javascript", "subscribe to continue", "captcha")):
        result.update(ok=False, usable=False, error="access_or_interstitial_page")
    return result


def _error_code(error):
    if isinstance(error, PublicSourceError):
        return str(error)
    if isinstance(error, urllib.error.HTTPError):
        return "http_" + str(error.code)
    if isinstance(error, (TimeoutError, socket.timeout)):
        return "network_timeout"
    if isinstance(error, urllib.error.URLError):
        return _error_code(error.reason) if isinstance(error.reason, Exception) else "network_error"
    return type(error).__name__


def _cache_path(root, url):
    root = Path(root).resolve()
    target = (root / "work" / "v11" / "source-cache" / (hashlib.sha256(url.encode()).hexdigest() + ".json")).resolve()
    if not target.is_relative_to(root):
        raise PublicSourceError("cache_path_outside_root")
    return target


def get(root, url, ttl_seconds=86400):
    """Get a public original's cached text. ok/usable never implies review done."""
    stamp = time.time()
    fetched_at = dt.datetime.fromtimestamp(stamp, dt.timezone.utc).isoformat(timespec="seconds")
    result = {"url": url, "final_url": url, "fetched_at": fetched_at,
              "title": "", "text": "", "ok": False, "usable": False, "from_cache": False,
              "tracking_resolver_version": TRACKING_RESOLVER_VERSION}
    try:
        validated = _validate_url(url)
        path = _cache_path(root, validated)
        ttl = max(0.0, float(ttl_seconds))
    except (ValueError, OSError) as error:
        result["error"] = _error_code(error)
        return result
    try:
        cached = json.loads(path.read_text(encoding="utf-8"))
        saved = cached["result"]
        permitted_ttl = ttl if saved.get("ok") and saved.get("usable") else min(ttl, FAILURE_TTL)
        if (cached.get("version") == _CACHE_VERSION and cached.get("url") == validated
                and (not _document_tracker(validated) or saved.get('tracking_resolver_version') == TRACKING_RESOLVER_VERSION)
                and 0 <= stamp - cached["stored_at"] < permitted_ttl):
            return dict(saved, url=url, from_cache=True, cache_file=str(path))
    except (OSError, ValueError, KeyError, TypeError):
        pass
    try:
        result.update(_fetch(validated))
    except Exception as error:
        result["error"] = _error_code(error)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        envelope = {"version": _CACHE_VERSION, "url": validated, "stored_at": stamp, "result": result}
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, suffix=".tmp", delete=False) as output:
                temporary = Path(output.name)
                json.dump(envelope, output, ensure_ascii=False, separators=(",", ":"))
            os.replace(temporary, path)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()
        result["cache_file"] = str(path)
    except OSError as error:
        result["cache_error"] = type(error).__name__
    return result
