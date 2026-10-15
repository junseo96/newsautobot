#!/usr/bin/env python3
"""Deterministic RSS/official-page collector for the power-industry news monitor."""
from __future__ import annotations
import argparse, concurrent.futures, datetime as dt, email.utils, hashlib, html, io, json, os, re, sqlite3, ssl, sys, urllib.error, urllib.parse, urllib.request, uuid, zipfile
from collections import deque
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import review_state
import newsletter_queue
import newsletter_completion
import runtime_scope
import source_normalization
from project_paths import evidence_path

KST = dt.timezone(dt.timedelta(hours=9)); UTC = dt.timezone.utc; TIMEOUT = 20
def now_utc(): return dt.datetime.now(UTC)
def iso(v):
    if v is None: return None
    return v.replace(tzinfo=v.tzinfo or UTC).astimezone(UTC).isoformat(timespec="seconds")
def published_value(article):
    # DART list.json provides a calendar day only. Preserve that day without
    # inventing a 00:00 publication time or shifting KST into the prior UTC day.
    return article.get("publication_calendar_date") or iso(article.get("published_at"))
def clean(v): return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html.unescape(v or ""))).strip()
def canonical(v):
    p=urllib.parse.urlsplit(v.strip()); q=[(k,x) for k,x in urllib.parse.parse_qsl(p.query) if not k.lower().startswith("utm_") and k.lower() not in {"ref","source","output"}]
    return urllib.parse.urlunsplit((p.scheme.lower(),p.netloc.lower(),re.sub(r"/{2,}","/",p.path).rstrip("/") or "/",urllib.parse.urlencode(q),""))
def norm_title(v): return re.sub(r"[^0-9a-z가-힣]+","",clean(v).lower())[:500]
def material_terms(v):
    """Return facts whose change can justify reopening an editorial decision.

    Feed publishers frequently alter punctuation, add a byline, or replace an
    excerpt. Those presentation-only updates must never turn a receipt-backed
    delivery back into a pending Telegram candidate. Numeric values and the
    lifecycle/regulatory vocabulary below are the compact, auditable signal
    set used to distinguish an actual update from that feed churn.
    """
    tokens=re.findall(r"\d+(?:\.\d+)?|[a-z]+|[가-힣]+",clean(v).lower())
    markers={
        "mw","gw","mwh","gwh","kv","capex","ppa","ferc","puc","iso","rto","smp",
        "approval","approved","authorize","authorised","construction","commission","operation",
        "contract","award","procurement","interconnection","rate","tariff","loan","restart",
        "retire","delay","cancel","suspend","increase","decrease","build","launch","expand",
        "승인","인가","착공","준공","가동","계약","수주","발주","입찰","계통","접속",
        "송전","전력망","요금","규제","시장","증설","감축","폐지","연기","재개","투자",
    }
    return frozenset(token for token in tokens if token.isdigit() or token in markers)
def material_content_change(previous,x,src):
    """True only for a new official edition or a changed industrial fact."""
    previous_date=parse_date(previous["published_at"])
    incoming_date=parse_date(iso(x.get("published_at")))
    if ((src.get("primary") or src.get("refresh_on_date_change")) and previous_date
            and incoming_date and incoming_date>previous_date+dt.timedelta(hours=1)):
        # Recurring official releases may legitimately keep one URL and title.
        return True
    before_title=source_normalization.article_title(x.get("url"),previous["title"] or "")
    after_title=source_normalization.article_title(x.get("url"),x.get("title") or "")
    if source_normalization.is_kpx_notice_url(x.get("url")):
        # KPX list counters are decoration; actual text changes are revisions,
        # including nonnumeric headline/body changes outside keyword markers.
        after_summary=x.get("summary") or previous["summary"] or ""
        return clean(before_title)!=clean(after_title) or clean(previous["summary"])!=clean(after_summary)
    before=material_terms(" ".join((before_title,previous["summary"] or "")))
    after=material_terms(" ".join((after_title,x.get("summary") or "")))
    return before!=after
def date_timezone(value):
    if isinstance(value,dt.tzinfo): return value
    if value in {"UTC","Z"}: return UTC
    match=re.fullmatch(r"([+-])(\d{2}):?(\d{2})",str(value))
    if not match or int(match[2])>23 or int(match[3])>59: raise ValueError("Invalid source date_timezone")
    offset=dt.timedelta(hours=int(match[2]),minutes=int(match[3]))
    return dt.timezone(offset if match[1]=="+" else -offset)
def parse_date(v,default_timezone=UTC):
    if not v: return None
    fallback=date_timezone(default_timezone)
    try:
        # email.utils can silently treat RFC dates ending in +09:00 as naive.
        # Normalize only the explicit terminal offset, not the wall-clock time.
        rfc_value=re.sub(r"([+-]\d{2}):(\d{2})$",r"\1\2",v.strip())
        x=email.utils.parsedate_to_datetime(rfc_value); return x.replace(tzinfo=x.tzinfo or fallback).astimezone(UTC)
    except Exception: pass
    try:
        x=dt.datetime.fromisoformat(v.strip().replace("Z","+00:00")); return x.replace(tzinfo=x.tzinfo or fallback).astimezone(UTC)
    except ValueError: return None
def parse_date_from_text(v,title_date_order="MDY"):
    text=clean(v)
    if title_date_order not in {"MDY","DMY"}: raise ValueError("title_date_order must be MDY or DMY")
    numeric_format="%d/%m/%Y" if title_date_order=="DMY" else "%m/%d/%Y"
    patterns=((r"\b([A-Z][a-z]+ \d{1,2}, \d{4})\b",("%B %d, %Y","%b %d, %Y")),(r"\b(\d{1,2} [A-Z][a-z]+ \d{4})\b",("%d %B %Y","%d %b %Y")),(r"\b(\d{4}[-./]\d{1,2}[-./]\d{1,2})\b",("%Y-%m-%d","%Y.%m.%d","%Y/%m/%d")),(r"\b(\d{1,2}/\d{1,2}/\d{4})\b",(numeric_format,)))
    for pattern,formats in patterns:
        match=re.search(pattern,text)
        if not match: continue
        for fmt in formats:
            try: return dt.datetime.strptime(match.group(1),fmt).replace(tzinfo=UTC)
            except ValueError: pass
    return None
def lname(tag): return tag.rsplit("}",1)[-1].lower()
def child_text(node,names):
    for c in list(node):
        if lname(c.tag) in names:
            if lname(c.tag)=="link" and c.attrib.get("href"): return c.attrib["href"]
            return "".join(c.itertext()).strip()
    return ""
def feed_link(node,base):
    # Atom often places the self link or a urn:id before the article URL.
    links=[c for c in node if lname(c.tag)=="link" and c.attrib.get("rel","alternate")=="alternate"]
    links.extend(c for c in node if lname(c.tag) in {"guid","id"})
    for child in links:
        value=(child.attrib.get("href") or "".join(child.itertext())).strip()
        link=urllib.parse.urljoin(base,value)
        if value and link.startswith(("http://","https://")): return link
    return ""
def feed_nodes(data):
    root=ET.fromstring(data)
    if lname(root.tag) not in {"rss","feed","rdf"}:
        raise ValueError("Response is not an RSS/Atom feed; source coverage is unverified")
    if lname(root.tag)=="rss" and not any(lname(n.tag)=="channel" for n in root):
        raise ValueError("RSS channel missing; source coverage is unverified")
    return [n for n in root.iter() if lname(n.tag) in {"item","entry"}]

def google_news_text(node,title,summary,src):
    """Publisher display-name changes are not revisions to the article."""
    if urllib.parse.urlsplit(src["url"]).hostname!="news.google.com": return title,summary
    publisher=child_text(node,{"source"})
    original=clean(title)
    if publisher:
        title=re.sub(r"\s+[-\u2013\u2014]\s+"+re.escape(clean(publisher))+r"$","",original)
    # Google RSS summaries are normally a linked headline plus <font>publisher.
    # Only collapse that exact shape; retain genuine additional reporting text.
    anchors=re.findall(r"<a\b[^>]*>(.*?)</a>",summary,re.I|re.S)
    if len(anchors)==1 and clean(anchors[0]) in {clean(title),original}:
        remaining=clean(re.sub(r"<a\b[^>]*>.*?</a>","",summary,count=1,flags=re.I|re.S))
        if remaining in {"",clean(publisher)}: summary=title
    return title,summary

def parse_feed(data,src):
    out=[]
    for node in feed_nodes(data):
        title=child_text(node,{"title"}); link=feed_link(node,src["url"]); summary=child_text(node,{"description","summary","content","encoded"})
        if not title or not link: continue
        title,summary=google_news_text(node,title,summary,src)
        include_terms=src.get("include_terms",[])
        if include_terms and not any(str(term).lower() in f"{title} {summary} {link}".lower() for term in include_terms): continue
        link=urllib.parse.urljoin(src["url"],link)
        if not link.startswith(("http://","https://")): continue
        date_text=child_text(node,{"pubdate","published","updated","date"})
        out.append(item(src,link,title,summary,parse_date(date_text,src.get("date_timezone",UTC))))
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}",date_text.strip()):out[-1]["publication_precision"]="date"
        if len(out)>=int(src.get("max_items",200)): break
    return out
def item(src,url,title,summary="",published=None):
    title,listing_date=source_normalization.kpx_listing_title(url,clean(title))
    inferred=parse_date_from_text(listing_date or title,src.get("title_date_order","MDY")) if published is None else None
    return {"source":src["name"],"source_url":src["url"],"priority":int(src.get("priority",2)),"primary":bool(src.get("primary")),"sec_watch":bool(src.get("sec_watch")),"must_review":bool(src.get("must_review") or src.get("critical") or src.get("sec_watch")),"url":canonical(url),"title":clean(title),"summary":clean(summary)[:3000],"published_at":published or inferred,"publication_precision":"exact" if published is not None else ("date" if inferred else "unknown")}
def parse_miso_news(data,src):
    """Read the public news API used by MISO's JavaScript media center."""
    payload=json.loads(data)
    if not isinstance(payload,dict) or not isinstance(payload.get("articles"),list):
        raise ValueError("MISO news API did not return an articles list")
    out=[]; seen=set(); host=urllib.parse.urlsplit(src["url"]).netloc.lower()
    for row in payload["articles"]:
        if not isinstance(row,dict) or row.get("isDeleted") or row.get("isPendingPublish"): continue
        title=row.get("name"); href=row.get("linkURL")
        if not title or not href: continue
        link=urllib.parse.urljoin(src["url"],href); parsed=urllib.parse.urlsplit(link)
        if parsed.scheme not in {"http","https"} or parsed.netloc.lower()!=host: continue
        key=canonical(link)
        if key in seen: continue
        seen.add(key)
        summary=" ".join(str(row.get(field) or "") for field in ("subheader","text"))
        out.append(item(src,link,title,summary,parse_date(row.get("releaseDate"))))
        if len(out)>=int(src.get("max_items",200)): break
    return out

def parse_hitachi_news(data,src):
    """Public JSON endpoint linked by Hitachi's news-listing component."""
    payload=json.loads(data)
    if not isinstance(payload,dict) or not isinstance(payload.get("items"),list):
        raise ValueError("Hitachi news API did not return an items list")
    out=[]; seen=set(); host=urllib.parse.urlsplit(src["url"]).hostname
    for row in payload["items"]:
        if not isinstance(row,dict) or row.get("webItemInsideIntranetContext"):continue
        title=row.get("title"); href=row.get("url")
        if not title or not href:continue
        link=urllib.parse.urljoin(src["url"],href)
        parsed=urllib.parse.urlsplit(link)
        if parsed.scheme not in {"http","https"} or parsed.hostname!=host or "/press-releases/" not in parsed.path:continue
        key=canonical(link)
        if key in seen:continue
        seen.add(key)
        # This API exposes a wall clock with no timezone. Preserve only its
        # stated date; the original must establish time before timely delivery.
        published=None
        try:published=dt.datetime.strptime(str(row.get("date","")).split()[0],"%d.%m.%Y").replace(tzinfo=UTC)
        except (ValueError,IndexError):pass
        article=item(src,link,title,row.get("description") or "",published)
        article["publication_precision"]="date" if published else "unknown"
        out.append(article)
        if len(out)>=int(src.get("max_items",200)):break
    return out

class LinkParser(HTMLParser):
    def __init__(self,base):
        super().__init__(convert_charrefs=True); self.base=base; self.links=[]; self.href=None; self.parts=[]; self.heading_depth=0
    def handle_starttag(self,tag,attrs):
        tag=tag.lower(); attrs=dict(attrs)
        if re.fullmatch(r"h[1-6]",tag): self.heading_depth+=1
        if tag=="a":
            self.href=attrs.get("href"); self.parts=[]; self.has_image=False
            self.has_headline=bool(self.heading_depth or re.search(r"(?:^|[-_\s])(?:title|headline)(?:$|[-_\s])",attrs.get("class",""),re.I))
        if self.href is not None:
            self.has_headline=self.has_headline or self.heading_depth>0
            self.has_image=self.has_image or tag=="img"
    def handle_data(self,data):
        if self.href is not None: self.parts.append(data)
    def handle_endtag(self,tag):
        tag=tag.lower()
        if tag=="a" and self.href is not None:
            label=clean(" ".join(self.parts)); url=urllib.parse.urljoin(self.base,self.href)
            # Cards may link both a photo caption and a headline to one article.
            quality=2 if self.has_headline else (0 if self.has_image else 1)
            if label and url.startswith(("http://","https://")): self.links.append((url,label,quality))
            self.href=None; self.parts=[]
        if re.fullmatch(r"h[1-6]",tag): self.heading_depth=max(0,self.heading_depth-1)
def parse_html(data,src):
    parser=LinkParser(src["url"]); parser.feed(data.decode("utf-8",errors="replace")); inc=src.get("include_path",""); host=urllib.parse.urlsplit(src["url"]).netloc.lower(); selected={}
    allowed_hosts={host,*(str(value).lower() for value in src.get("allowed_hosts",[]))}
    for link,title,quality in parser.links:
        p=urllib.parse.urlsplit(link)
        if p.netloc.lower() not in allowed_hosts or (inc and inc not in p.path) or len(title)<18: continue
        if src.get("include_terms") and not any(str(t).lower() in f"{title} {link}".lower() for t in src["include_terms"]): continue
        if src.get("include_regex") and not re.search(src["include_regex"],link): continue
        if any(part in p.path for part in src.get("exclude_paths",[])): continue
        url=canonical(link)
        if url==canonical(src["url"]): continue
        if url not in selected or quality>selected[url][0]: selected[url]=(quality,title)
    # One update per article: an image caption cannot reopen a decision before
    # its unchanged headline is processed again. Retain the original label text.
    return [item(src,url,title) for url,(_,title) in selected.items()][:int(src.get("max_items",200))]
def tdworld_publication_date(data):
    """Use the article's exact published timestamp, never its date-only label."""
    page=html.unescape(data.decode("utf-8",errors="replace"))
    match=re.search(r'"published"\s*:\s*"(\d{4}-\d{2}-\d{2}T[^"<>]+)"',page)
    return parse_date(match.group(1)) if match else None
def fetch_tdworld_publication(url):
    try:
        request=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0 PowerIndustryMonitor/2.0"})
        with urllib.request.urlopen(request,timeout=TIMEOUT) as response:
            published=tdworld_publication_date(response.read(1_000_000))
        return published,None if published else "Exact publication timestamp missing"
    except Exception as error:
        return None,f"{type(error).__name__}: {str(error)[:160]}"
def enrich_tdworld_new_articles(results,con):
    """Fetch new originals; retry recent undated links at most three times."""
    con.execute("CREATE TABLE IF NOT EXISTS source_date_checks(url TEXT PRIMARY KEY, checked_at TEXT NOT NULL, attempts INTEGER NOT NULL, error TEXT)")
    current=now_utc()
    for result in results:
        if result["source"].get("name")!="T&D World" or not result["ok"]:continue
        new=[]
        for article in result["items"]:
            if article.get("published_at") is not None:continue
            existing=con.execute("SELECT first_seen_at,published_at FROM articles WHERE url=?",(article["url"],)).fetchone()
            if existing and (existing["published_at"] or not parse_date(existing["first_seen_at"])
                             or parse_date(existing["first_seen_at"])<current-dt.timedelta(hours=12)):continue
            prior=con.execute("SELECT checked_at,attempts FROM source_date_checks WHERE url=?",(article["url"],)).fetchone()
            if prior and (prior["attempts"]>=3 or parse_date(prior["checked_at"])>current-dt.timedelta(minutes=10)):continue
            new.append(article)
        failures=[]
        if new:
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(6,len(new))) as pool:
                resolved=list(pool.map(lambda x:fetch_tdworld_publication(x["url"]),new))
                for article,(published,error) in zip(new,resolved):
                    if published:article.update(published_at=published,publication_precision="exact")
                    else:failures.append({"url":article["url"],"error":error})
                    con.execute("INSERT INTO source_date_checks(url,checked_at,attempts,error) VALUES(?,?,1,?) "
                                "ON CONFLICT(url) DO UPDATE SET checked_at=excluded.checked_at,attempts=attempts+1,error=excluded.error",
                                (article["url"],iso(current),error))
        result["date_resolution"]={"new_links_checked":len(new),"exact_dates_found":len(new)-len(failures),
                                   "undated_new_links":failures}
def fetch_once(src):
    started=now_utc(); headers={"User-Agent":src.get("user_agent","Mozilla/5.0 PowerIndustryMonitor/2.0"),"Accept":src.get("accept","application/rss+xml, application/atom+xml, application/xml, text/xml, text/html;q=0.9, */*;q=0.5")}
    try:
        context=None
        if src.get("legacy_tls"):
            context=ssl.create_default_context(); context.set_ciphers("DEFAULT:@SECLEVEL=1")
        request_url=urllib.parse.quote(src["url"],safe=":/?&=%()+")
        with urllib.request.urlopen(urllib.request.Request(request_url,headers=headers),timeout=TIMEOUT,context=context) as r: data=r.read(5_000_000)
        parser={"rss":parse_feed,"miso_news_json":parse_miso_news,"hitachi_news_json":parse_hitachi_news}.get(src.get("kind"),parse_html)
        items=parser(data,src)
        raw_count=len(items); coverage_state="articles_parsed"
        if src.get("kind")=="rss":
            nodes=feed_nodes(data)
            raw_count=sum(bool(child_text(n,{"title"}) and feed_link(n,src["url"])) for n in nodes)
            if nodes and not raw_count:
                raise ValueError("Feed entries contain no valid article titles/URLs; source coverage is unverified")
            if not items and raw_count and src.get("include_terms"):
                coverage_state="filtered_no_matches"
            elif not items and (src.get("discovery") or src.get("allow_empty")):
                coverage_state="discovery_no_results" if src.get("discovery") else "allowed_empty"
            elif not items:
                raise ValueError("No feed entries parsed; source coverage is unverified")
        elif not items:
            if src.get("kind")=="html" and src.get("include_terms"):
                unfiltered=dict(src);unfiltered.pop("include_terms")
                raw_count=len(parse_html(data,unfiltered))
            if raw_count:
                coverage_state="filtered_no_matches"
            elif not src.get("allow_empty"):
                raise ValueError("No article links parsed; source coverage is unverified")
            else:coverage_state="allowed_empty"
        return {"source":src,"ok":True,"items":items,"raw_item_count":raw_count,"coverage_state":coverage_state,"error":None,"started_at":iso(started),"finished_at":iso(now_utc())}
    except Exception as e:
        retryable=(isinstance(e,urllib.error.HTTPError) and e.code in {500,502,503,504}) or isinstance(e,TimeoutError) or (isinstance(e,urllib.error.URLError) and isinstance(e.reason,TimeoutError))
        return {"source":src,"ok":False,"items":[],"error":f"{type(e).__name__}: {str(e)[:300]}","retryable":retryable,"started_at":iso(started),"finished_at":iso(now_utc())}
def fetch(src):
    result=fetch_once(src); result["attempts"]=1
    if not result["ok"] and result.get("retryable") and src.get("retry_transient",True):
        result=fetch_once(src); result["attempts"]=2
    return result
def dart_companies(archive, cfg):
    """Resolve watchlisted issuers by DART name or stable listed stock code."""
    with zipfile.ZipFile(io.BytesIO(archive)) as z:
        root=ET.fromstring(z.read(z.namelist()[0]))
    wanted=set(cfg.get("dart_watchlist",[]))
    stock_codes=set(cfg.get("dart_watchlist_stock_codes",[]))
    companies=[]
    for node in root.findall("list"):
        name=(node.findtext("corp_name") or "").strip()
        stock=(node.findtext("stock_code") or "").strip()
        code=(node.findtext("corp_code") or "").strip()
        if code and (name in wanted or stock in stock_codes):
            companies.append((code,name))
    return companies

def dart_document_text(archive):
    """Extract bounded readable text from an official document.xml ZIP."""
    parts=[]
    with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
        for member in zipped.infolist():
            if not member.filename.lower().endswith((".xml",".html",".htm")) or member.file_size>4_000_000:
                continue
            raw=zipped.read(member)
            decoded=None
            for encoding in ("utf-8-sig","euc-kr","cp949"):
                try: decoded=raw.decode(encoding); break
                except UnicodeDecodeError: pass
            if decoded is None: continue
            decoded=re.sub(r"(?is)<(script|style)\b[^>]*>.*?</\1>"," ",decoded)
            decoded=re.sub(r"(?i)</(?:td|th)>"," | ",decoded)
            decoded=re.sub(r"(?i)</(?:tr|p|div|section|table)>","\n",decoded)
            decoded=html.unescape(re.sub(r"(?s)<[^>]*>"," ",decoded))
            parts.extend(line.strip() for line in decoded.splitlines() if line.strip())
            if sum(len(part) for part in parts)>30000: break
    text="\n".join(parts)[:30000]
    if len(text)<100: raise ValueError("DART original lacks usable filing text")
    return text

def cache_dart_document(cache_path, url, title, filing_day, key, rcp, headers, dart_ssl):
    """Cache verified official contract text for the read-only review worker."""
    if cache_path is None:return None
    path=Path(cache_path).parent/'source-cache'/(hashlib.sha256(url.encode()).hexdigest()+'.json')
    if path.exists():
        try:
            old=json.loads(path.read_text(encoding="utf-8"))
            result=old.get("result",{})
            if (old.get("url")==url and result.get("source_method")=="opendart_document_xml"
                    and now_utc().timestamp()-old.get("stored_at",0)<(86400 if result.get("usable") else 900)):
                return bool(result.get("usable"))
        except (OSError,ValueError,TypeError): pass
    result={"url":url,"final_url":url,"title":title,"published_at":filing_day,
            "fetched_at":iso(now_utc()),"text":"","ok":False,"usable":False,
            "from_cache":False,"source_method":"opendart_document_xml"}
    try:
        api="https://opendart.fss.or.kr/api/document.xml?"+urllib.parse.urlencode({"crtfc_key":key,"rcept_no":rcp})
        with urllib.request.urlopen(urllib.request.Request(api,headers=headers),timeout=TIMEOUT,context=dart_ssl) as response:
            payload=response.read(4_500_000)
        result.update(text=dart_document_text(payload),ok=True,usable=True)
    except Exception as error:
        result["error"]=type(error).__name__
    temporary=None
    try:
        path.parent.mkdir(parents=True,exist_ok=True)
        temporary=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
        temporary.write_text(json.dumps({"version":2,"url":url,"stored_at":now_utc().timestamp(),"result":result},ensure_ascii=False),encoding="utf-8")
        os.replace(temporary,path)
    except OSError:
        return False
    finally:
        if temporary is not None and temporary.exists(): temporary.unlink()
    return bool(result["usable"])

def dart_material_report(name):
    """Filing types that can change physical power-infrastructure activity."""
    return any(term in name for term in (
        "단일판매","공급계약","신규시설투자","시설투자","생산중단","생산재개",
        "영업정지","영업재개","투자판단관련주요경영사항","타법인주식및출자증권취득",
        "사업양수","사업양도","유형자산취득","기타경영사항","장래사업","기술도입"))

def fetch_dart(cfg, cache_path=None, *, extended=False):
    key=os.environ.get("NEWS_DART_KEY","").strip()
    src={"name":"OpenDART Extended" if extended else "OpenDART Watchlist",
         "url":"https://opendart.fss.or.kr/","priority":1,"primary":True,"critical":True}
    started=now_utc()
    if not key: return None
    headers={"User-Agent":"PowerIndustryMonitor/2.0"}
    # OpenDART currently presents a legacy DH parameter rejected by OpenSSL's
    # default security level. Keep certificate/hostname validation enabled and
    # lower only the cipher security level for requests to the official host.
    dart_ssl=ssl.create_default_context(); dart_ssl.set_ciphers("DEFAULT:@SECLEVEL=1")
    try:
        active_cfg={"dart_watchlist":cfg.get("dart_extended_watchlist",[]) if extended else cfg.get("dart_watchlist",[]),
                    "dart_watchlist_stock_codes":cfg.get("dart_extended_stock_codes",[]) if extended else cfg.get("dart_watchlist_stock_codes",[])}
        watch_signature=hashlib.sha256(json.dumps([active_cfg["dart_watchlist"],active_cfg["dart_watchlist_stock_codes"]],ensure_ascii=False).encode()).hexdigest()
        cached=None
        if cache_path and Path(cache_path).exists():
            try:
                cached=json.loads(Path(cache_path).read_text(encoding="utf-8"))
                if cached.get("watch_signature")!=watch_signature: cached=None
            except (OSError,ValueError): cached=None
        fresh_cache=cached and (now_utc().timestamp()-cached.get("fetched_epoch",0)<86400)
        if fresh_cache:
            companies=[tuple(row) for row in cached["companies"]]
        else:
            try:
                code_url="https://opendart.fss.or.kr/api/corpCode.xml?"+urllib.parse.urlencode({"crtfc_key":key})
                with urllib.request.urlopen(urllib.request.Request(code_url,headers=headers),timeout=TIMEOUT,context=dart_ssl) as r: archive=r.read(8_000_000)
                companies=dart_companies(archive,active_cfg)
                if cache_path:
                    try:
                        path=Path(cache_path); path.parent.mkdir(parents=True,exist_ok=True)
                        temporary=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
                        temporary.write_text(json.dumps({"watch_signature":watch_signature,"fetched_epoch":now_utc().timestamp(),"companies":companies},ensure_ascii=False),encoding="utf-8")
                        os.replace(temporary,path)
                    except OSError:
                        pass  # Mapping remains valid for this poll even if cache storage fails.
            except (OSError,ValueError,zipfile.BadZipFile,ET.ParseError):
                if not cached: raise
                companies=[tuple(row) for row in cached["companies"]]
        start=(now_utc().astimezone(KST)-dt.timedelta(days=2)).strftime("%Y%m%d"); end=now_utc().astimezone(KST).strftime("%Y%m%d"); items=[]
        for corp_code,name in companies:
            query=urllib.parse.urlencode({"crtfc_key":key,"corp_code":corp_code,"bgn_de":start,"end_de":end,"page_count":100})
            with urllib.request.urlopen(urllib.request.Request("https://opendart.fss.or.kr/api/list.json?"+query,headers=headers),timeout=TIMEOUT,context=dart_ssl) as r: payload=json.loads(r.read().decode("utf-8"))
            if payload.get("status") not in {"000","013"}: raise RuntimeError(f"DART {payload.get('status')}: {payload.get('message')}")
            for filing in payload.get("list",[]):
                report_name=filing.get("report_nm","")
                if extended and not dart_material_report(report_name): continue
                rcp=filing.get("rcept_no",""); received=filing.get("rcept_dt","")
                filing_day=f"{received[:4]}-{received[4:6]}-{received[6:8]}" if re.fullmatch(r"\d{8}",received) else "미확인"
                # list.json supplies a calendar day, not an exact filing time.
                # Queue from first_seen_at; require original-document review.
                x=item(src,"https://dart.fss.or.kr/dsaf001/main.do?rcpNo="+rcp,f"{name} | {filing.get('report_nm','공시')}",f"DART 접수일 {filing_day}; 접수번호 {rcp}")
                if filing_day!="미확인":
                    x["published_at"]=parse_date(received+"T00:00:00+09:00")
                    x["publication_precision"]="date"
                    x["publication_calendar_date"]=filing_day
                if ("단일판매" in report_name and "공급계약" in report_name) or (extended and dart_material_report(report_name)):
                    x["must_review"]=True
                    cache_dart_document(cache_path,x["url"],x["title"],filing_day,key,rcp,headers,dart_ssl)
                x["sec_watch"]=True; items.append(x)
        return {"source":src,"ok":True,"items":items,"error":None,"started_at":iso(started),"finished_at":iso(now_utc())}
    except Exception as e: return {"source":src,"ok":False,"items":[],"error":f"{type(e).__name__}: {str(e)[:300]}","started_at":iso(started),"finished_at":iso(now_utc())}
def ensure_db(c):
    c.executescript("""
    CREATE TABLE IF NOT EXISTS articles(id INTEGER PRIMARY KEY,url TEXT NOT NULL UNIQUE,url_hash TEXT NOT NULL,normalized_title TEXT NOT NULL,title TEXT NOT NULL,summary TEXT NOT NULL DEFAULT '',source TEXT NOT NULL,source_url TEXT NOT NULL,published_at TEXT,first_seen_at TEXT NOT NULL,last_seen_at TEXT NOT NULL,score INTEGER NOT NULL,score_reasons TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'pending',delivered_at TEXT,reviewed_at TEXT);
    CREATE INDEX IF NOT EXISTS idx_articles_status ON articles(status,score,first_seen_at);
    CREATE INDEX IF NOT EXISTS idx_articles_title ON articles(normalized_title);
    CREATE TABLE IF NOT EXISTS source_runs(id INTEGER PRIMARY KEY,run_id TEXT NOT NULL,source TEXT NOT NULL,source_url TEXT NOT NULL,ok INTEGER NOT NULL,item_count INTEGER NOT NULL,new_item_count INTEGER NOT NULL DEFAULT 0,latest_published_at TEXT,error TEXT,started_at TEXT NOT NULL,finished_at TEXT NOT NULL);
    """)
    columns={r[1] for r in c.execute("PRAGMA table_info(source_runs)")}
    if "new_item_count" not in columns: c.execute("ALTER TABLE source_runs ADD COLUMN new_item_count INTEGER NOT NULL DEFAULT 0")
    if "latest_published_at" not in columns: c.execute("ALTER TABLE source_runs ADD COLUMN latest_published_at TEXT")
    article_columns={r[1] for r in c.execute("PRAGMA table_info(articles)")}
    if "decision_policy_version" not in article_columns: c.execute("ALTER TABLE articles ADD COLUMN decision_policy_version INTEGER NOT NULL DEFAULT 0")
    if "decision_reason" not in article_columns: c.execute("ALTER TABLE articles ADD COLUMN decision_reason TEXT")
    for name,definition in (("must_review","INTEGER NOT NULL DEFAULT 0"),("last_presented_at","TEXT"),("presentation_count","INTEGER NOT NULL DEFAULT 0"),("content_updated_at","TEXT"),("content_source","TEXT"),("timestamp_corrected_at","TEXT"),("publication_precision","TEXT NOT NULL DEFAULT 'unknown'")):
        if name not in article_columns: c.execute(f"ALTER TABLE articles ADD COLUMN {name} {definition}")
    review_state.ensure_review_schema(c)
def term_matches(text,term):
    term=term.lower()
    if re.fullmatch(r"[a-z0-9][a-z0-9 .&+/_-]*",term):
        return re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])",text) is not None
    return term in text
def score_item(x,cfg):
    title=x["title"].lower(); text=f"{x['title']} {x.get('summary','')} {x.get('source','')}".lower(); groups=cfg["keyword_groups"]; score=10 if x.get("priority")==1 else 4; reasons=[]; matched=[]; weights={"grid_market":22,"equipment":18,"generation":18,"ai_infra":14,"industrial_event":18}
    if x.get("primary"): score+=15; reasons.append("1차자료")
    for group,words in groups.items():
        hits=[w for w in words if term_matches(text,w)]
        if hits: score+=weights.get(group,12); matched.append(group); reasons.append(f"{group}:{','.join(hits[:3])}")
    if re.search(r"\b\d+(?:[.,]\d+)?\s*(?:gw|mw|gwh|mwh|kv|billion|million|bn|억|조|기)\b",text,re.I): score+=12; reasons.append("물량·규모")
    if any(term_matches(title,w) for w in groups["industrial_event"]): score+=8; reasons.append("제목의 산업 이벤트")
    if "industrial_event" in matched and {"grid_market","equipment","generation","ai_infra"}.intersection(matched): score+=8; reasons.append("산업 이벤트와 핵심 분야 동시 확인")
    exclusions=[w for w in cfg.get("exclude_keywords",[]) if term_matches(text,w)]
    if exclusions and not any(g in matched for g in ("grid_market","equipment","generation","ai_infra")): score-=45; reasons.append("매크로·가격 단독")
    if x.get("sec_watch"): score=max(score,35); reasons.append("SEC 감시종목 공시")
    if "ai_infra" in matched and not {"grid_market","equipment","generation"}.intersection(matched): score=min(score,35); reasons.append("전력 연계가 약한 데이터센터 기사")
    if not {"grid_market","equipment","generation","ai_infra"}.intersection(matched): score=min(score,20); reasons.append("산업 직접성 부족")
    if x.get("sec_watch"): score=max(score,35)
    if x.get("source","").startswith("OpenDART") and "단일판매" in x["title"] and "공급계약" in x["title"]:
        score=max(score,70); reasons.append("DART 공식 수주계약 공시 우선검토")
    return max(0,min(score,100)),reasons
def config(path): return json.loads(path.read_text(encoding="utf-8-sig"))
def source_diverse(rows,quota=3):
    """Keep every URL, while preventing a high-volume feed monopolizing page one."""
    buckets={}
    for row in rows: buckets.setdefault(row["source"],deque()).append(row)
    def rank(row):
        return (-int(row["must_review"]),int(row["presentation_count"]),-row["score"],row["last_presented_at"] or "",row["first_seen_at"],row["url"])
    for name,values in buckets.items(): buckets[name]=deque(sorted(values,key=rank))
    ordered=[]
    while buckets:
        for name in sorted(buckets,key=lambda n:rank(buckets[n][0])):
            values=buckets[name]
            for _ in range(min(max(1,quota),len(values))): ordered.append(values.popleft())
            if not values: del buckets[name]
    return ordered
def candidate_order(rows,cfg,lookback,page_size,audit_urls):
    queues={"fresh":[],"backlog":[],"revalidation":[]}
    for row in rows:
        key="revalidation" if row["url"] in audit_urls else ("backlog" if (parse_date(row["published_at"]) or parse_date(row["first_seen_at"]))<lookback else "fresh")
        queues[key].append(row)
    queues={k:deque(source_diverse(v,int(cfg.get("candidate_source_round_quota",3)))) for k,v in queues.items()}
    backlog_quota=max(1,int(page_size*float(cfg.get("pending_backlog_share",.25))))
    audit_quota=min(int(cfg.get("revalidation_max_candidates",40)),max(1,page_size//4))
    ordered=[]
    while any(queues.values()):
        page=[]
        limits={"fresh":max(1,page_size-(backlog_quota if queues["backlog"] else 0)-(audit_quota if queues["revalidation"] else 0)),"backlog":backlog_quota,"revalidation":audit_quota}
        for name,limit in limits.items():
            for _ in range(min(limit,len(queues[name]),page_size-len(page))): page.append(queues[name].popleft())
        for name in queues:
            for _ in range(min(len(queues[name]),page_size-len(page))): page.append(queues[name].popleft())
        ordered.extend(page)
    return ordered
def render_page(payload,offset,limit,snapshot_path):
    if offset<0 or limit<1: raise ValueError("offset must be non-negative and max_candidates positive")
    total=len(payload["candidates"]); page=dict(payload); summary_limit=int(payload.get("export_options",{}).get("summary_chars",1000)); page["candidates"]=[dict(row,summary=row["summary"][:summary_limit]) for row in payload["candidates"][offset:offset+limit]]
    page["pagination"]={"snapshot_path":str(snapshot_path),"offset":offset,"page_size":limit,"total_candidates":total,"has_more":offset+limit<total,"next_offset":offset+limit if offset+limit<total else None}
    return page
def note_presented(con,rows,stamp):
    con.executemany("UPDATE articles SET last_presented_at=?,presentation_count=presentation_count+1 WHERE url=?",[(stamp,row["url"]) for row in rows])
def processed_newsletter_ids(con):
    newsletter_queue.ensure_newsletter_schema(con)
    return [row[0] for row in con.execute("SELECT message_id FROM newsletter_messages ORDER BY imported_at,message_id")]
def official_agency(url):
    host=(urllib.parse.urlsplit(url).hostname or "").lower().rstrip(".")
    return next((domain for domain in newsletter_queue.OFFICIAL_DOMAINS if host==domain or host.endswith("."+domain)),None)
def may_update_content(previous,x,src):
    """Share newer official editions without letting old feed excerpts ping-pong."""
    previous_date=parse_date(previous["published_at"]); incoming_date=parse_date(iso(x.get("published_at")))
    if previous_date and incoming_date and incoming_date<previous_date: return False
    is_owner=previous["source"]==x["source"]
    last_writer=previous["content_source"] or previous["source"]
    agency=official_agency(x["url"])
    trusted_official=bool(src.get("primary") and agency and official_agency(src["url"])==agency)
    newer=bool(incoming_date and incoming_date>(previous_date or parse_date(previous["first_seen_at"])))
    if trusted_official and newer: return True
    if not is_owner: return False
    # When Gmail supplied a newer edition, an owning RSS feed must catch up
    # with a later dated edition before it may replace that content again.
    if last_writer!=x["source"]: return newer
    return True
def is_legacy_timestamp_correction(previous,x,src):
    """One-time repair for an explicitly configured legacy parser error."""
    timezone_repair=src.get("timestamp_correction_hours")==9
    title_repair=src.get("legacy_title_date_order")=="MDY" and src.get("title_date_order")=="DMY"
    if not (timezone_repair or title_repair) or previous["timestamp_corrected_at"]: return False
    cutoff=parse_date(src.get("timestamp_correction_before"))
    first_seen=parse_date(previous["first_seen_at"])
    if not cutoff or not first_seen or first_seen>=cutoff: return False
    updated=parse_date(previous["content_updated_at"])
    if previous["content_updated_at"] and (updated is None or updated>cutoff): return False
    if previous["source"]!=x["source"] or previous["content_source"] not in (None,previous["source"]): return False
    if clean(previous["title"])!=clean(x["title"]) or clean(previous["summary"])!=clean(x["summary"]): return False
    old_date=parse_date(previous["published_at"]); corrected=parse_date(iso(x.get("published_at")))
    if not old_date or not corrected: return False
    if timezone_repair and old_date-corrected==dt.timedelta(hours=9): return True
    if title_repair:
        legacy=parse_date_from_text(previous["title"],"MDY"); current=parse_date_from_text(x["title"],"DMY")
        return bool(legacy and current and legacy!=current and old_date==legacy and corrected==current)
    return False
def export_batch(args):
    payload=json.loads(args.batch.read_text(encoding="utf-8-sig")); snapshot=evidence_path(payload.get("pagination",{}).get("snapshot_path") or args.batch)
    if snapshot.resolve()!=args.batch.resolve(): payload=json.loads(snapshot.read_text(encoding="utf-8-sig"))
    if args.output.resolve()==snapshot.resolve(): raise ValueError("Export must not overwrite its immutable snapshot")
    page=render_page(payload,args.offset,args.max_candidates,snapshot)
    if args.db.exists():
        con=sqlite3.connect(args.db); ensure_db(con); page.setdefault("integrations",{})["gmail_processed_message_ids"]=processed_newsletter_ids(con); note_presented(con,page["candidates"],iso(now_utc())); con.commit(); con.close()
    args.output.parent.mkdir(parents=True,exist_ok=True); args.output.write_text(json.dumps(page,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"run_id":page["run_id"],"candidate_count":len(page["candidates"]),"pagination":page["pagination"],"output":str(args.output)},ensure_ascii=False)); return 0
def collect(args):
    cfg=config(args.config); args.db.parent.mkdir(parents=True,exist_ok=True); args.output.parent.mkdir(parents=True,exist_ok=True); con=sqlite3.connect(args.db,timeout=30); con.row_factory=sqlite3.Row; ensure_db(con)
    # Never retain a schema/housekeeping write transaction while sources wait
    # on the network; delivery ACKs can commit during collection.
    con.commit()
    scope = runtime_scope.load(args.db.resolve().parent.parent)
    existing_before=con.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
    known_sources={r[0] for r in con.execute("SELECT DISTINCT source FROM source_runs")}
    runtime=now_utc(); lookback=runtime-dt.timedelta(hours=args.lookback_hours); run_id=runtime.strftime("%Y%m%dT%H%M%SZ")+"-"+uuid.uuid4().hex[:12]
    configured_sources=cfg["sources"]
    sources=configured_sources
    if getattr(args,"fast_poll",False):
        fast_path=args.config.with_name("runtime-v12.json")
        if not fast_path.exists():fast_path=args.config.with_name("runtime-v11.json")
        fast_config=config(fast_path)
        requested=set(fast_config.get("fast_poll_source_names",[]))
        available={src["name"] for src in configured_sources}
        missing=requested-available
        if not requested or missing:raise ValueError(f"Invalid fast_poll_source_names: {sorted(missing)}")
        sources=[src for src in configured_sources if src["name"] in requested]
    for src in sources:
        if src.get("sec_watch"): src["user_agent"]=cfg["sec_user_agent"]
    results=[]
    if sources:
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(8,len(sources))) as pool: results=list(pool.map(fetch,sources))
    if getattr(args,"fast_poll",False):
        dart_result=fetch_dart(cfg,args.db.parent/'v11'/'dart-corp-codes.json')
    else:
        dart_result=fetch_dart(cfg,args.db.parent/'v11'/'dart-corp-codes-extended.json',extended=True)
    if dart_result is not None: results.append(dart_result)
    newsletter_results=[]; newsletter_error=None
    if getattr(args,"newsletter_file",None):
        try:
            newsletter_results=newsletter_queue.load_newsletter_results(args.newsletter_file,item,parse_date, received_after_epoch=scope.get('gmail_start_epoch'))
            results.extend(newsletter_queue.unimported_newsletter_results(con,newsletter_results))
        except (OSError,ValueError,KeyError,TypeError) as error:
            newsletter_results=[]; newsletter_error=f"{type(error).__name__}: {error}"
            results.append({"source":{"name":"Gmail newsletter ingestion","url":"https://mail.google.com/","group":"newsletter","critical":False},"ok":False,"items":[],"error":newsletter_error,"started_at":iso(runtime),"finished_at":iso(now_utc())})
    enrich_tdworld_new_articles(results,con)
    inserted=0; new_by_source={}
    for result in results:
        src=result["source"]; source_new=0
        for x in result["items"]:
            score,reasons=score_item(x,cfg); stamp=iso(runtime); before=con.total_changes
            is_baseline=(existing_before==0 or src["name"] not in known_sources)
            is_discovery=bool(src.get("discovery")) or urllib.parse.urlsplit(src["url"]).netloc.lower()=="news.google.com"
            is_analysis=bool(src.get("analysis"))
            # A score or age is a queueing hint, never evidence of a completed review.
            history_since=runtime-dt.timedelta(days=int(cfg.get("new_source_history_days",cfg.get("revalidation_days",14))))
            queue_date=runtime if x.get("publication_calendar_date")==runtime.astimezone(KST).date().isoformat() else x["published_at"]
            if queue_date is not None and queue_date<history_since: initial_status="archive"
            elif (queue_date is not None and queue_date<lookback) or (is_baseline and queue_date is None): initial_status="brief"
            elif not x.get("must_review") and (is_discovery or is_analysis) and score<cfg["realtime_score_threshold"]: initial_status="brief"
            else: initial_status="pending"
            con.execute("INSERT OR IGNORE INTO articles(url,url_hash,normalized_title,title,summary,source,source_url,published_at,first_seen_at,last_seen_at,score,score_reasons,status,must_review,publication_precision) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(x["url"],hashlib.sha256(x["url"].encode()).hexdigest(),norm_title(x["title"]),x["title"],x["summary"],x["source"],x["source_url"],published_value(x),stamp,stamp,score,json.dumps(reasons,ensure_ascii=False),initial_status,int(x.get("must_review",False)),x.get("publication_precision","unknown")))
            if con.total_changes>before:
                inserted+=1; source_new+=1
                if initial_status=="archive": con.execute("UPDATE articles SET decision_reason='initial_archive_outside_history_window' WHERE url=?",(x["url"],))
            else:
                previous=con.execute("SELECT * FROM articles WHERE url=?",(x["url"],)).fetchone()
                # Official feeds and newsletters may share a recurring report
                # URL; allow newer editions while preserving the original source.
                if is_legacy_timestamp_correction(previous,x,src):
                    con.execute("UPDATE articles SET published_at=?,timestamp_corrected_at=?,last_seen_at=? WHERE url=?",(published_value(x),stamp,stamp,x["url"]))
                elif may_update_content(previous,x,src):
                    changed=material_content_change(previous,x,src)
                    con.execute("UPDATE articles SET last_seen_at=?,title=?,normalized_title=?,summary=CASE WHEN ?<>'' THEN ? ELSE summary END,published_at=COALESCE(?,published_at),must_review=MAX(must_review,?),content_updated_at=CASE WHEN ? THEN ? ELSE content_updated_at END,content_source=? WHERE url=?",(stamp,x["title"],norm_title(x["title"]),x["summary"],x["summary"],published_value(x),int(x.get("must_review",False)),changed,stamp,x["source"],x["url"]))
                    if changed:
                        con.execute("UPDATE articles SET status='pending',last_presented_at=NULL,presentation_count=0 WHERE url=? AND status IN ('reviewed','delivered','brief','archive')",(x["url"],))
                    if x.get("published_at") is not None:
                        con.execute("UPDATE articles SET publication_precision=? WHERE url=?",(x.get("publication_precision","unknown"),x["url"]))
                else:
                    con.execute("UPDATE articles SET last_seen_at=?,must_review=MAX(must_review,?) WHERE url=?",(stamp,int(x.get("must_review",False)),x["url"]))
        latest=max((published_value(x) for x in result["items"] if x.get("published_at")),default=None)
        con.execute("INSERT INTO source_runs(run_id,source,source_url,ok,item_count,new_item_count,latest_published_at,error,started_at,finished_at) VALUES(?,?,?,?,?,?,?,?,?,?)",(run_id,src["name"],src["url"],int(result["ok"]),len(result["items"]),source_new,latest,result["error"],result["started_at"],result["finished_at"]))
        if source_new: new_by_source[src["name"]]=source_new
    newsletter_ingestion=newsletter_queue.journal_newsletter_results(con,newsletter_results,run_id)
    newsletter_ingestion["error"]=newsletter_error
    # Re-score stored unresolved rows when the watchlist/keywords improve. Old
    # feed entries need not be fetched again for the expanded policy to apply.
    source_lookup={s["name"]:s for s in configured_sources}; source_lookup.update({r["source"]["name"]:r["source"] for r in [*results,*newsletter_results]}); policy_version=int(cfg.get("selection_policy_version",1))
    for row in con.execute("SELECT * FROM articles WHERE status IN ('pending','brief') OR (status='reviewed' AND decision_policy_version<?)",(policy_version,)).fetchall():
        src=source_lookup.get(row["source"],{}); x=dict(row); x.update({k:src.get(k,False) for k in ("primary","sec_watch")}); x["priority"]=src.get("priority",2)
        score,reasons=score_item(x,cfg); required=bool(row["must_review"] or src.get("must_review") or src.get("critical") or src.get("sec_watch"))
        con.execute("UPDATE articles SET score=?,score_reasons=?,must_review=? WHERE id=?",(score,json.dumps(reasons,ensure_ascii=False),int(required),row["id"]))
    # Legacy seen_urls are observation history, not Telegram delivery evidence.
    # Existing records are preserved; no automatic delivery migration occurs.
    statuses=("pending","brief")
    if getattr(args,"include_archive",False): statuses=(*statuses,"archive")
    marks=",".join("?" for _ in statuses)
    # Some feeds publish scheduled stories with timestamps several hours ahead.
    # Keep them pending, but do not surface them before their stated release time.
    future_cutoff=runtime+dt.timedelta(minutes=5)
    explicit_deferral="" if args.lane=="morning" else " AND NOT (status='brief' AND reviewed_at IS NOT NULL)"
    rows=list(con.execute(f"SELECT * FROM articles WHERE status IN ({marks}) AND (published_at IS NULL OR published_at<=?){explicit_deferral}",(*statuses,iso(future_cutoff))).fetchall()); candidates=[]
    audit_urls=set()
    # Newsletter articles are an end-to-end queue, including explicit brief
    # deferrals and imported archive/legacy statuses. Never drop them by age.
    mail_workflow = newsletter_completion.audit(con, policy_version)
    present_urls = {row['url'] for row in rows}
    for pending_mail_article in mail_workflow['unresolved_articles']:
        if pending_mail_article['url'] in present_urls:
            continue
        mail_row = con.execute('SELECT * FROM articles WHERE url=?', (pending_mail_article['url'],)).fetchone()
        # Unverified legacy delivered rows need receipt recovery, not an
        # automatic re-send candidate. They remain visible in mail_workflow.
        if mail_row is not None and mail_row['status'] != 'delivered' and (not mail_row['published_at'] or parse_date(mail_row['published_at']) <= future_cutoff):
            rows.append(mail_row)
            present_urls.add(mail_row['url'])
    if args.lane=="morning" and not scope:
        # A previous policy's rejection is unresolved until the current policy
        # explicitly decides it. Age and score affect ordering, not eligibility.
        audit_rows=con.execute("SELECT * FROM articles WHERE status='reviewed' AND decision_policy_version<? AND COALESCE(published_at,first_seen_at)<=?",(policy_version,iso(future_cutoff))).fetchall()
        rows.extend(row for row in audit_rows if row['url'] not in present_urls); audit_urls={row["url"] for row in audit_rows}
    scoped_out = []
    active_mail_urls = {x['url'] for x in mail_workflow['unresolved_articles']}
    newsletter_origins = {}
    for url, message_id, received_at in con.execute(
            'SELECT ma.article_url,n.message_id,n.received_at FROM newsletter_message_articles ma '
            'JOIN newsletter_messages n ON n.message_id=ma.message_id '
            'WHERE n.received_at IS NOT NULL ORDER BY n.received_at,n.message_id'):
        newsletter_origins.setdefault(url, (message_id, received_at))
    eligible_rows = []
    for row in rows:
        reason = runtime_scope.exclusion(row, scope, runtime.timestamp(), active_mail_urls)
        if reason:
            scoped_out.append({"url": row["url"], "reason": reason})
        else:
            eligible_rows.append(row)
    for row in candidate_order(eligible_rows,cfg,lookback,max(1,args.max_candidates),audit_urls):
        stamp=parse_date(row["first_seen_at"]) if row["publication_precision"]=="date" else (parse_date(row["published_at"]) or parse_date(row["first_seen_at"]))
        candidates.append({"url":row["url"],"title":row["title"],"summary":row["summary"],"source":row["source"],"source_group":source_lookup.get(row["source"],{}).get("group","other"),"published_at":row["published_at"],"publication_precision":row["publication_precision"],"first_seen_at":row["first_seen_at"],"score":row["score"],"score_reasons":json.loads(row["score_reasons"]),"recommended_lane":"realtime" if row["must_review"] or row["score"]>=cfg["realtime_score_threshold"] else "brief","must_review":bool(row["must_review"]),"review_status":row["status"],"content_updated_at":row["content_updated_at"],"outside_lookback":stamp<lookback,"age_hours":round((runtime-stamp).total_seconds()/3600,1),"presentation_count":row["presentation_count"],"policy_revalidation":row["url"] in audit_urls})
        candidates[-1]["content_source"]=row["content_source"] or row["source"]
        candidates[-1]["publication_precision"]=row["publication_precision"]
        if row['url'] in newsletter_origins:
            candidates[-1]['newsletter_message_id'],candidates[-1]['newsletter_received_at']=newsletter_origins[row['url']]
    successful=sum(1 for r in results if r["ok"]); coverage=successful/len(results) if results else 0.0
    source_freshness={}
    latest_by_source=dict(con.execute("SELECT source,MAX(published_at) FROM articles GROUP BY source"))
    for source_result in results:
        name=source_result["source"]["name"]
        latest=latest_by_source.get(name)
        latest_date=parse_date(latest)
        source_freshness[name]={"fetch_ok":source_result["ok"],"items":len(source_result["items"]),
            "latest_verified_published_at":latest,"latest_age_hours":round((runtime-latest_date).total_seconds()/3600,1) if latest_date else None,
            "new_article_dates":source_result.get("date_resolution"),
            "coverage_state":source_result.get("coverage_state","articles_parsed" if source_result["ok"] else "fetch_or_parse_failed"),
            "raw_item_count":source_result.get("raw_item_count"),
            "discovery":bool(source_result["source"].get("discovery")),
            "direct":bool(source_result["source"].get("primary"))}
    failed=[{"name":r["source"]["name"],"url":r["source"]["url"],"group":r["source"].get("group","other"),"critical":bool(r["source"].get("critical")),"error":r["error"]} for r in results if not r["ok"]]
    # Full verified history: old facts remain old even after 14 days / 100 sends.
    recent_delivered=[dict(r) for r in con.execute("SELECT a.title,h.url,a.source,a.published_at,h.sent_at AS delivered_at,h.message_text,h.message_sha256,h.receipt_file,'telegram_receipt' AS evidence_type FROM delivery_history h LEFT JOIN articles a ON a.url=h.url ORDER BY h.sent_at DESC")]
    delivered_messages={}
    for delivery in recent_delivered: delivered_messages[delivery["message_sha256"]]=delivery.pop("message_text")
    legacy_unverified=[dict(r) for r in con.execute("SELECT title,url,source,delivered_at,'legacy_unverified' AS evidence_type FROM articles WHERE status='delivered' AND NOT EXISTS (SELECT 1 FROM delivery_history h WHERE h.url=articles.url) ORDER BY delivered_at DESC LIMIT 100")]
    coverage_by_group={}
    for result in results:
        group=coverage_by_group.setdefault(result["source"].get("group","other"),{"successful":0,"total":0,"critical_failed":[]}); group["total"]+=1; group["successful"]+=int(result["ok"])
        if not result["ok"] and result["source"].get("critical"): group["critical_failed"].append(result["source"]["name"])
    waiting={r["status"]:r["n"] for r in con.execute("SELECT status,COUNT(*) n FROM articles WHERE status IN ('pending','brief') GROUP BY status")}
    archive_count=con.execute("SELECT COUNT(*) FROM articles WHERE status='archive'").fetchone()[0]
    oldest=con.execute("SELECT MIN(first_seen_at) FROM articles WHERE status IN ('pending','brief')").fetchone()[0]
    run_dir=args.output.parent/"runs"/run_id; run_dir.mkdir(parents=True,exist_ok=True); snapshot_path=run_dir/"snapshot.json"; decisions_path=run_dir/"decisions.json"; index_path=run_dir/"screening-index.json"
    decisions_path.write_text(json.dumps({"run_id":run_id,"decisions":[]}),encoding="utf-8")
    index_rows=[]
    for position,candidate in enumerate(candidates):
        row={key:candidate[key] for key in ("url","title","source","source_group","must_review","score","published_at","outside_lookback","policy_revalidation")}; row["index"]=position; row["summary"]=candidate["summary"][:350]; index_rows.append(row)
    index_path.write_text(json.dumps({"run_id":run_id,"total_candidates":len(index_rows),"snapshot_path":str(snapshot_path),"candidates":index_rows},ensure_ascii=False,separators=(",",":")),encoding="utf-8")
    payload={"schema_version":5,"policy_version":policy_version,"run_id":run_id,"lane":args.lane,"generated_at_kst":runtime.astimezone(KST).isoformat(timespec="seconds"),"coverage_ok":coverage>=float(cfg.get("minimum_coverage_ratio",.75)) and not any(x["critical"] for x in failed),"coverage_ratio":round(coverage,3),"critical_gap":any(x["critical"] for x in failed),"coverage_by_group":coverage_by_group,"integrations":{"dart_configured":bool(os.environ.get("NEWS_DART_KEY","").strip()),"gmail":"heartbeat_connector"},"successful_sources":successful,"total_sources":len(results),"failed_sources":failed,"fetched_items":sum(len(r["items"]) for r in results),"inserted_articles":inserted,"new_by_source":new_by_source,"recent_delivered":recent_delivered,"legacy_unverified_deliveries":legacy_unverified,"candidates":candidates,"queue":{"waiting_by_status":waiting,"oldest_unreviewed_first_seen_at":oldest,"eligible_candidates":len(candidates),"eligible_outside_lookback":sum(x["outside_lookback"] for x in candidates),"policy_revalidation_candidates":len(audit_urls)},"run_files":{"snapshot":str(snapshot_path),"decisions":str(decisions_path)},"thresholds":{"realtime":cfg["realtime_score_threshold"],"brief":cfg["brief_score_threshold"]},"revalidation_scope":"all_previous_policy_reviews"}
    payload["source_freshness"]=source_freshness
    payload["poll_scope"]="fast" if getattr(args,"fast_poll",False) else "full"
    payload["run_files"]["screening_index"]=str(index_path)
    payload["export_options"]={"summary_chars":int(cfg.get("candidate_summary_chars",1000))}
    payload["queue"]["unreviewed_archive_count"]=archive_count
    payload["queue"]["archive_included"]=bool(getattr(args,"include_archive",False))
    payload["newsletter_ingestion"]=newsletter_ingestion
    payload["newsletter_workflow"]=mail_workflow
    payload["operational_scope"] = {"version":scope.get("version"), "gmail_start_epoch":scope.get("gmail_start_epoch"), "freshness_hours":scope.get("freshness_hours"), "historical_reference_only_count":len(scoped_out), "historical_reference_only":scoped_out}
    if scope: payload["revalidation_scope"]="current_news_only_no_historical_backlog"
    payload["integrations"]["gmail_processed_message_ids"]=processed_newsletter_ids(con)
    payload["delivered_messages"]=delivered_messages
    snapshot_path.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
    page=render_page(payload,0,args.max_candidates,snapshot_path); note_presented(con,page["candidates"],iso(runtime))
    args.output.write_text(json.dumps(page,ensure_ascii=False,indent=2),encoding="utf-8"); con.commit(); con.close(); print(json.dumps({"run_id":run_id,"operational_version":scope.get("version"),"coverage_ok":payload["coverage_ok"],"coverage_ratio":payload["coverage_ratio"],"inserted":inserted,"candidate_count":len(page["candidates"]),"total_candidates":len(candidates),"has_more":page["pagination"]["has_more"],"run_files":payload["run_files"],"output":str(args.output)},ensure_ascii=False)); return 0
def acknowledge(args):
    return review_state.acknowledge(args,canonical,ensure_db)
def recover_legacy_deliveries(args):
    return review_state.recover_legacy_direct_link_deliveries(args,canonical,ensure_db)
def status(args):
    con=sqlite3.connect(args.db); con.row_factory=sqlite3.Row; ensure_db(con); counts={r["status"]:r["count"] for r in con.execute("SELECT status,COUNT(*) count FROM articles GROUP BY status")}; runs=[dict(r) for r in con.execute("SELECT source,ok,item_count,error,finished_at FROM source_runs WHERE run_id=(SELECT run_id FROM source_runs ORDER BY id DESC LIMIT 1) ORDER BY source")]; ids=processed_newsletter_ids(con); con.commit(); con.close(); print(json.dumps({"article_counts":counts,"latest_source_runs":runs,"integrations":{"gmail_processed_message_ids":ids}},ensure_ascii=False,indent=2)); return 0
def parser():
    base=Path(__file__).resolve().parents[2]; p=argparse.ArgumentParser(); subs=p.add_subparsers(dest="command",required=True)
    x=subs.add_parser("collect"); x.add_argument("--config",type=Path,default=base/"outputs"/"rss-news-monitor"/"sources.json"); x.add_argument("--db",type=Path,default=base/"work"/"rss-news-monitor.db"); x.add_argument("--output",type=Path,default=base/"work"/"rss-news-candidates.json"); x.add_argument("--lookback-hours",type=int,default=12); x.add_argument("--max-candidates",type=int,default=100); x.add_argument("--include-archive",action="store_true"); x.add_argument("--newsletter-file",type=Path); x.add_argument("--fast-poll",action="store_true"); x.add_argument("--lane",choices=("realtime","morning"),default="realtime"); x.set_defaults(handler=collect)
    x=subs.add_parser("export"); x.add_argument("--batch",type=Path,required=True); x.add_argument("--db",type=Path,default=base/"work"/"rss-news-monitor.db"); x.add_argument("--output",type=Path,default=base/"work"/"rss-news-candidates.json"); x.add_argument("--offset",type=int,default=0); x.add_argument("--max-candidates",type=int,default=100); x.set_defaults(handler=export_batch)
    x=subs.add_parser("ack"); x.add_argument("--config",type=Path,default=base/"outputs"/"rss-news-monitor"/"sources.json"); x.add_argument("--db",type=Path,default=base/"work"/"rss-news-monitor.db"); x.add_argument("--batch",type=Path,default=base/"work"/"rss-news-candidates.json"); x.add_argument("--decision-file",type=Path); x.add_argument("--recover-deliveries",action="store_true"); x.add_argument("--delivered-url",action="append"); x.add_argument("--reviewed-url",action="append"); x.add_argument("--brief-url",action="append"); x.set_defaults(handler=acknowledge)
    x=subs.add_parser("recover-legacy-deliveries"); x.add_argument("--db",type=Path,default=base/"work"/"rss-news-monitor.db"); x.add_argument("--mapping-file",type=Path,required=True); x.set_defaults(handler=recover_legacy_deliveries)
    x=subs.add_parser("status"); x.add_argument("--db",type=Path,default=base/"work"/"rss-news-monitor.db"); x.set_defaults(handler=status); return p
if __name__=="__main__":
    a=parser().parse_args(); raise SystemExit(a.handler(a))
