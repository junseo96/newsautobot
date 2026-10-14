"""Operational scope with v10 overrides; retired history remains in the v9 baseline."""
import datetime as dt
import json
from pathlib import Path

def load(root):
    directory = Path(root) / 'outputs/rss-news-monitor'
    path = directory / 'runtime-v9.json'
    scope = json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else {}
    override = directory / 'runtime-v10.json'
    if override.exists():
        settings = json.loads(override.read_text(encoding='utf-8-sig'))
        if not scope:
            raise ValueError('v10 requires the preserved runtime-v9.json scope baseline')
        if settings.get('version') != 10:
            raise ValueError('Invalid v10 operational version')
        protected = {'gmail_start_epoch', 'gmail_start_kst', 'retired_message_ids',
                     'retired_unresolved_urls', 'baseline_counts', 'retirement_reason'}
        if protected.intersection(settings):
            raise ValueError('v10 settings must not replace the historical Gmail baseline')
        scope.update(settings)
    v11 = directory / 'runtime-v11.json'
    if v11.exists():
        settings = json.loads(v11.read_text(encoding='utf-8-sig'))
        if settings.get('version') != 11 or not scope:
            raise ValueError('v11 requires the preserved historical baseline')
        protected = {'gmail_start_epoch', 'gmail_start_kst', 'retired_message_ids',
                     'retired_unresolved_urls', 'baseline_counts', 'retirement_reason'}
        if protected.intersection(settings):
            raise ValueError('v11 must not replace the historical Gmail baseline')
        scope.update(settings)
    v12 = directory / 'runtime-v12.json'
    if v12.exists():
        settings = json.loads(v12.read_text(encoding='utf-8-sig'))
        if settings.get('version') != 12 or not scope:
            raise ValueError('v12 requires the preserved historical baseline')
        protected = {'gmail_start_epoch', 'gmail_start_kst', 'retired_message_ids',
                     'retired_unresolved_urls', 'baseline_counts', 'retirement_reason'}
        if protected.intersection(settings):
            raise ValueError('v12 must not replace the historical Gmail baseline')
        scope.update(settings)
    return scope

def for_connection(con):
    main = next((r[2] for r in con.execute('PRAGMA database_list') if r[1] == 'main'), '')
    return load(Path(main).resolve().parent.parent) if main else {}

def timestamp(value):
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed.replace(tzinfo=parsed.tzinfo or dt.timezone.utc).timestamp()
    except (ValueError, TypeError):
        return None

def exclusion(row, scope, now_epoch, active_mail_urls=()):
    if not scope or row['url'] in active_mail_urls:
        return None
    changed = timestamp(row['content_updated_at']) or 0
    floor = scope['gmail_start_epoch']
    if row['url'] in scope['retired_unresolved_urls'] and changed < floor:
        return 'user_retired_gmail_backlog'
    published = timestamp(row['published_at'])
    if published is not None and 'publication_precision' in row.keys() and row['publication_precision']=='date':
        published+=86400  # Upper bound of a known day, for discovery eligibility only.
    from v12_controls import analysis_candidate
    hours=max(scope['freshness_hours'],168) if analysis_candidate(dict(row)) else scope['freshness_hours']
    if published is not None and published < now_epoch - hours * 3600:
        return 'historical_reference_only'
    if published is None and (timestamp(row['first_seen_at']) or 0) < floor and changed < floor:
        return 'historical_undated_reference_only'
    return None
