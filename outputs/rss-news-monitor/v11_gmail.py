"""Deterministic full-MIME newsletter extraction; Gmail access stays in its plugin.

This module never reads credentials, calls a mailbox API, resolves a remote URL,
or marks a mail/article complete. Unresolved article tracking links are retained.
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import html
import ipaddress
import json
import re
from email.header import decode_header, make_header
from email.utils import parseaddr
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit

from gmail_scan import _full_mime_payload

TRACKING_PARAMS = {"sp_eh", "test_key", "o_eid", "oly_enc_id", "rdx.ident[pull]"}
TRACKING_HOSTS = ("hello.canarymedia.com", "endeavor.omeclk.com", "lnks.gd", "rs6.net")
ACTION_LABEL = re.compile(r"unsubscribe|opt[ -]?out|manage (?:your )?(?:subscription|preferences|account)|email preferences|"
                          r"(?:reset|change|update)(?: your)? (?:password|email|account)|(?:sign|log)[ -]?in|"
                          r"verify (?:your )?(?:email|account)|activate (?:your )?account|수신\s*거부|구독\s*해지", re.I)
ACTION_PATH = re.compile(r"(?:^|/)(?:unsubscribe|unsub|optout|opt-out|preferences|email-preferences|manage-subscription|account/settings)(?:/|$)", re.I)
NAVIGATION_LABEL = re.compile(
    r"^(?:home|privacy(?: policy| notice)?|terms(?: of (?:use|service))?|terms and conditions|"
    r"contact(?: us)?|about(?: us)?|advertise(?: with us)?|sign[ -]?in|log[ -]?in|"
    r"follow us(?: on (?:facebook|linkedin|twitter|instagram|x))?|"
    r"share (?:on (?:facebook|linkedin|twitter|x)|this (?:email|newsletter))|"
    r"view (?:in (?:your )?browser|this email in (?:your )?browser|online)|"
    r"donate(?: now)?|support us|subscribe(?: now)?)$", re.I)
NAVIGATION_PATH = re.compile(
    r"^/(?:privacy(?:-policy|-notice)?|terms(?:-of-use|-of-service|-and-conditions)?|"
    r"contact(?:-us)?|about(?:-us)?|advertis(?:e|ing)|login|signin)/?$", re.I)
GENERIC_ARTICLE_LABEL = re.compile(r"^(?:read(?: the)?(?: full)? (?:more|story|article)|"
                                   r"learn more|continue reading|click here)[\s\u00bb\u203a>]*$", re.I)


def clean(value):
    return re.sub(r"\s+", " ", html.unescape(value or "")).strip()


def public_url(value):
    value = html.unescape(value or "").strip()
    if not value or re.search(r"[\s\x00-\x1f]", value):
        return None
    try:
        p = urlsplit(value)
        if p.scheme not in {"http", "https"} or not p.hostname or p.username or p.password:
            return None
        _ = p.port
        host = p.hostname.lower().rstrip(".")
        if host == "localhost" or "." not in host:
            return None
        try:
            if not ipaddress.ip_address(host).is_global:
                return None
        except ValueError:
            pass
        return value
    except ValueError:
        return None


def canonical_url(value):
    p = urlsplit(value)
    query = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
             if not k.lower().startswith(("utm_", "_hs")) and k.lower() not in TRACKING_PARAMS]
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path or "/", urlencode(query), ""))


def unwrap_embedded_url(value):
    """Decode ordinary URL wrappers without making any network request."""
    current = value
    for _ in range(4):
        p = urlsplit(current)
        decoded = None
        for key, candidate in parse_qsl(p.query):
            if key.lower() in {"url", "u", "redirect", "redirect_url", "destination", "target"}:
                candidate = unquote(candidate)
                if public_url(candidate):
                    decoded = candidate
                    break
        if decoded is None:
            for segment in p.path.split("/"):
                if not segment.startswith("aHR0"):
                    continue
                try:
                    candidate = base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4)).decode("utf-8")
                except (ValueError, UnicodeDecodeError):
                    continue
                if public_url(candidate):
                    decoded = candidate
                    break
        if not decoded or decoded == current:
            break
        current = decoded
    return current


def action_link(url, label):
    p = urlsplit(url)
    if ACTION_LABEL.search(label) or ACTION_PATH.search(unquote(p.path)):
        return True
    return any(k.lower() in {"unsubscribe", "optout", "opt-out"}
               or (k.lower() in {"action", "cmd"} and v.lower() in {"unsubscribe", "optout", "deleteaccount"})
               for k, v in parse_qsl(p.query))


def looks_like_tracking(url):
    host = (urlsplit(url).hostname or "").lower()
    return (any(host == domain or host.endswith("." + domain) for domain in TRACKING_HOSTS)
            or host.startswith(("click.", "clicks.", "links.", "link.", "track.", "tracking.")))


def navigation_link(url, label):
    """Exclude only unequivocal utility links, not sponsored technical material."""
    p = urlsplit(url)
    if NAVIGATION_LABEL.fullmatch(clean(label)) or NAVIGATION_PATH.fullmatch(unquote(p.path)):
        return True
    host = (p.hostname or '').lower().removeprefix('www.')
    return ((host in {'facebook.com', 'linkedin.com', 'twitter.com', 'x.com'}
             and re.match(r'^/(?:sharer(?:\.php)?|share|sharing|intent)(?:/|$)', p.path) is not None))


class Links(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self.text = []
        self.anchor = None
        self.parts = []
        self.skip = 0
        self.records = []
        self.anchor_start = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in {"script", "style"}:
            self.skip += 1
        if tag == "a":
            self.anchor = attrs.get("href")
            self.parts = []
            self.anchor_start = len(self.text)
        if tag == "img" and self.anchor and attrs.get("alt"):
            self.parts.append(attrs["alt"])

    def handle_endtag(self, tag):
        if tag in {"script", "style"} and self.skip:
            self.skip -= 1
        if tag == "a":
            if self.anchor:
                label = clean(" ".join(self.parts))
                self.links.append((self.anchor, label))
                self.records.append((self.anchor, label, self.anchor_start, len(self.text)))
            self.anchor = None
            self.parts = []

    def handle_data(self, value):
        if not self.skip:
            self.text.append(value)
            if self.anchor:
                self.parts.append(value)


def mime_texts(payload):
    """Decode all text leaves, including Gmail API and connector field names."""
    results = []
    mime = payload.get("mimeType", payload.get("mime_type", "")).lower()
    body = payload.get("body", {})
    if mime in {"text/html", "text/plain"}:
        if body.get("attachmentId") or body.get("attachment_id"):
            raise ValueError("Full text MIME attachment content is missing")
        text = body.get("content")
        if not isinstance(text, str) or not text:
            encoded = body.get("base64_url_content", body.get("data", ""))
            try:
                raw = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
                headers = {h.get("name", "").lower(): h.get("value", "") for h in payload.get("headers", [])}
                charset = re.search(r"charset\s*=\s*[\"']?([^;\s\"']+)", headers.get("content-type", ""), re.I)
                text = raw.decode(charset.group(1) if charset else "utf-8")
            except (ValueError, UnicodeError, LookupError) as error:
                raise ValueError("Cannot decode complete text MIME body") from error
        results.append((mime, text))
    for part in payload.get("parts") or []:
        results.extend(mime_texts(part))
    return results


def _plain_link_records(text):
    """Read explicit `label (URL)` or `[label](URL)` in a plain MIME part.

    Standalone URLs and preceding unrelated lines never gain invented labels.
    Context is literal message text with URLs and email addresses removed.
    """
    for match in re.finditer(r'https?://[^\s<>"\']+', text):
        url = match.group().rstrip('.,;!)]}')
        start = text.rfind('\n', 0, match.start()) + 1
        end = text.find('\n', match.end())
        if end < 0:
            end = len(text)
        prefix = text[start:match.start()].rstrip()
        label = ''
        if prefix.endswith('('):
            label = prefix[:-1].rstrip()
            markdown = re.search(r'\[([^\[\]]+)\]$', label)
            if markdown:
                label = markdown.group(1)
            else:
                # HubSpot's text alternative uses ordinary parenthesized URLs.
                # A previous inline URL ends the earlier label, not this one.
                previous = list(re.finditer(r'\(https?://[^\s]+\)', label))
                if previous:
                    label = label[previous[-1].end():].lstrip(' ,;:-')
            label = clean(label[-300:])
        context = text[max(start, match.start()-400):min(end, match.end()+200)]
        context = re.sub(r'https?://[^\s<>"\']+', '[link]', context)
        context = re.sub(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}', '[email]', context)
        yield url, label, clean(context)[:800], False


def link_evidence(envelope):
    """Return local full-MIME link provenance, with action exclusions dominant.

    Values have allowed=True for an explicitly labeled article candidate, False for
    known actions/navigation, and None when article purpose is unproven. This
    is discovery evidence, never editorial or publication-date verification.
    No request is made; an opaque tracker is not itself a meaningful title.
    """
    if not isinstance(envelope, dict) or envelope.get('body_complete') is not True:
        raise ValueError('Full MIME evidence is required')
    message = envelope.get('message', {})
    mid = envelope.get('message_id')
    if not mid or message.get('id') != mid or not _full_mime_payload(message.get('payload')):
        raise ValueError('Matching full MIME evidence is required')
    records = []
    for mime, text in mime_texts(message['payload']):
        if mime == 'text/html':
            parser = Links()
            parser.feed(text)
            for url, label, start, end in parser.records:
                context = clean(' '.join(parser.text[max(0, start-4):end+4]))[:800]
                context = re.sub(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}', '[email]', context)
                records.append((url, label, context, True))
        else:
            records.extend(_plain_link_records(text))
    evidence = {}
    for raw, label, context, from_html in records:
        url = public_url(raw)
        if not url:
            continue
        unwrapped = unwrap_embedded_url(url)
        key = canonical_url(unwrapped)
        blocked = action_link(url, label) or action_link(unwrapped, label)
        navigation = navigation_link(url, label) or navigation_link(unwrapped, label)
        # HTML image alternatives and plaintext can repeat the exact same link.
        # A known footer/action label must dominate all its unlabeled variants.
        prior = evidence.get(key)
        if prior is not None and prior['allowed'] is False:
            continue
        reason = 'subscription_or_account_action' if blocked else 'navigation_or_social_share'
        if blocked or navigation:
            evidence[key] = {'allowed': False, 'label': label, 'context': '',
                             'reason': reason, 'from_html': from_html, 'message_id': mid}
            continue
        usable_label = bool(label and not re.search(r'https?://|[A-Za-z0-9_-]{48,}', label))
        ambiguous_label = label.lower() in {
            'here', 'page', 'website', 'canary media', 'click here', 'home', 'homepage'}
        generic = bool(GENERIC_ARTICLE_LABEL.fullmatch(label))
        # Nearby article copy does not make a logo/home/footer link an article.
        # Only an explicit article CTA can borrow its surrounding context.
        allowed = True if usable_label and not ambiguous_label and (not generic or len(context) >= 100) else None
        item = {'allowed': allowed, 'label': label if usable_label else '',
                'context': context, 'reason': ('html_article_candidate' if from_html else 'explicit_plain_article_link') if allowed else 'article_purpose_unverified',
                'from_html': from_html, 'message_id': mid}
        quality = (allowed is True, usable_label, from_html, len(label) if usable_label else 0)
        old_quality = (prior['allowed'] is True, bool(prior['label']), prior['from_html'], len(prior['label'])) if prior else (-1,)
        if quality > old_quality:
            evidence[key] = item
    return evidence


def extract_message(envelope, resolved_urls=None):
    """Return schema-1 mail plus an honest local extraction-stage report."""
    if (not isinstance(envelope, dict) or envelope.get("body_complete") is not True
            or not isinstance(envelope.get("message"), dict)):
        raise ValueError("A complete original Gmail cache envelope is required")
    message = envelope["message"]
    message_id = envelope.get("message_id")
    if not message_id or message.get("id") != message_id or not _full_mime_payload(message.get("payload")):
        raise ValueError("Matching message ID and full MIME payload are required")
    headers = {h.get("name", "").lower(): h.get("value", "") for h in message["payload"].get("headers", [])}
    sender = str(make_header(decode_header(headers.get("from", ""))))
    subject = str(make_header(decode_header(headers.get("subject", "Newsletter"))))
    name, address = parseaddr(sender)
    source = clean(name or address or subject)[:200]
    domain = address.rsplit("@", 1)[-1] if "@" in address else ""
    source_url = public_url("https://" + domain + "/") or "https://mail.google.com/"
    stamp = message.get("internal_date", message.get("internalDate"))
    try:
        received = dt.datetime.fromtimestamp(int(stamp) / 1000, dt.timezone.utc).isoformat()
    except (ValueError, TypeError, OverflowError, OSError) as error:
        raise ValueError("Actual Gmail internal_date is required") from error
    texts = mime_texts(message["payload"])
    links, body_parts = [], []
    # HTML first: descriptive labels win over the plain-text URL alternative.
    for mime, text in sorted(texts, key=lambda x: x[0] != "text/html"):
        if mime == "text/html":
            parser = Links()
            parser.feed(text)
            links.extend(parser.links)
            body_parts.append(clean(" ".join(parser.text)))
        else:
            links.extend((url, label) for url, label, _, _ in _plain_link_records(text))
            body_parts.append(clean(text))
    excluded, articles, unresolved = [], {}, []
    resolutions = resolved_urls or {}
    evidence = link_evidence(envelope)
    for raw_url, label in links:
        url = public_url(raw_url)
        if not url:
            excluded.append({"reason": "non_public_or_non_http_link", "label": label})
            continue
        if action_link(url, label):
            excluded.append({"reason": "subscription_or_account_action", "label": label})
            continue
        if navigation_link(url, label):
            excluded.append({"reason": "navigation_or_social_share", "label": label})
            continue
        url = unwrap_embedded_url(url)
        provenance = evidence.get(canonical_url(url), {})
        if provenance.get('allowed') is False:
            excluded.append({'reason': provenance['reason'], 'label': provenance.get('label', '')})
            continue
        # A later descriptive anchor wins over an earlier empty image link.
        label = provenance.get('label', '') if provenance else label
        if url in resolutions:
            resolution = resolutions[url]
            url = resolution.get("url", url) if isinstance(resolution, dict) else resolution
        if not public_url(url) or action_link(url, label):
            excluded.append({"reason": "unsafe_or_action_destination", "label": label})
            continue
        if navigation_link(url, label):
            excluded.append({"reason": "navigation_or_social_share", "label": label})
            continue
        url = canonical_url(url)
        slug = unquote(urlsplit(url).path.strip("/").rsplit("/", 1)[-1]).replace("-", " ")
        # Generic buttons carry no article facts. A resolved descriptive slug is
        # better evidence, while opaque tracking IDs must retain the mail label.
        title = label
        if not label or (GENERIC_ARTICLE_LABEL.fullmatch(label) and not looks_like_tracking(url)
                         and len(slug.split()) >= 3):
            title = (subject + ' - unlabelled newsletter link') if looks_like_tracking(url) else (slug or subject)
        if url not in articles:
            articles[url] = {"url": url, "title": title, "summary": "", "published_at": None}
            if looks_like_tracking(url):
                unresolved.append(url)
        elif label and not GENERIC_ARTICLE_LABEL.fullmatch(label) and len(label) > len(articles[url]["title"]):
            articles[url]["title"] = label
    mail = {"message_id": message_id, "source": source, "source_url": source_url,
            "received_at": received, "must_review": True, "articles": list(articles.values())}
    report = {"message_id": message_id, "subject": subject, "full_mime_parsed": True,
              "text_parts": len(texts), "body_text_chars": sum(len(x) for x in body_parts),
              "raw_link_count": len(links), "candidate_links": len(articles),
              "excluded_links": excluded, "unresolved_tracking": unresolved,
              "import_ready": bool(articles),
              "manual_mail_classification_required": not bool(articles),
              "article_review_complete": False, "editorial_completion_claimed": False}
    return mail, report


def build_newsletter(cache_paths, resolved_urls=None):
    messages, reports, seen = [], [], set()
    for path in cache_paths:
        try:
            envelope = json.loads(Path(path).read_text(encoding="utf-8-sig"))
            mail, report = extract_message(envelope, resolved_urls)
        except (ValueError, OSError, UnicodeError) as error:
            reports.append({"cache_path": str(Path(path).resolve()), "import_ready": False,
                            "manual_mail_classification_required": False, "extraction_failed": True,
                            "error_type": type(error).__name__, "unresolved_tracking": [],
                            "editorial_completion_claimed": False})
            continue
        if mail["message_id"] in seen:
            raise ValueError("Duplicate message cache supplied")
        seen.add(mail["message_id"])
        report["cache_path"] = str(Path(path).resolve())
        # A newsletter can contain news entirely within its body. No links is
        # not proof of a non-news message; retain its cache for explicit review.
        if report["import_ready"]:
            messages.append(mail)
        reports.append(report)
    return {"schema_version": 1, "messages": messages}, {"schema_version": 1, "messages": reports}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", action="append", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--resolutions", type=Path)
    args = parser.parse_args(argv)
    resolutions = json.loads(args.resolutions.read_text(encoding="utf-8-sig")) if args.resolutions else None
    newsletter, report = build_newsletter(args.cache, resolutions)
    for path, value in ((args.output, newsletter), (args.report, report)):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"messages": len(newsletter["messages"]),
                      "article_links": sum(len(m["articles"]) for m in newsletter["messages"]),
                      "unresolved_tracking_links": sum(len(m["unresolved_tracking"]) for m in report["messages"]),
                      "manual_mail_classification_required": sum(m["manual_mail_classification_required"] for m in report["messages"]),
                      "extraction_failed": sum(m.get("extraction_failed", False) for m in report["messages"]),
                      "output": str(args.output), "report": str(args.report),
                      "editorial_completion_claimed": False}))


if __name__ == "__main__":
    main()
