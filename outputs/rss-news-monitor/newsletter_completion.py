"""Read-only end-to-end newsletter completion; ingestion is not completion."""
import json
import sqlite3
from pathlib import Path
import runtime_scope


def audit(con, policy_version, scope=None):
    con.row_factory = sqlite3.Row
    scope = runtime_scope.for_connection(con) if scope is None else scope
    retired_ids = set(scope.get('retired_message_ids', []))
    retired_count = 0
    messages = []
    unresolved = {}
    recovery_needed = {}
    for mail in con.execute('SELECT * FROM newsletter_messages ORDER BY imported_at,message_id').fetchall():
        if mail['message_id'] in retired_ids:
            retired_count += 1
            continue
        remaining = []
        links = con.execute('SELECT article_url FROM newsletter_message_articles WHERE message_id=?', (mail['message_id'],)).fetchall()
        for link in links:
            url = link['article_url']
            row = con.execute('SELECT * FROM articles WHERE url=?', (url,)).fetchone()
            complete = False
            if row is not None and row['status'] == 'delivered':
                # Only ACK-created receipt history, never an imported status alone.
                complete = con.execute('SELECT 1 FROM delivery_history WHERE url=? AND sent_at=?', (url, row['delivered_at'])).fetchone() is not None
            elif row is not None and row['status'] == 'reviewed' and (row['decision_policy_version'] or 0) >= policy_version:
                complete = con.execute("SELECT 1 FROM decision_history WHERE url=? AND status='reviewed' AND policy_version>=? AND reason=?", (url, policy_version, row['decision_reason'])).fetchone() is not None and bool(row['decision_reason'])
            if not complete:
                blocker = None
                if row is not None and row['status'] == 'delivered':
                    blocker = 'legacy_delivery_missing_receipt'
                    recovery_needed[url] = {'url': url, 'title': row['title'],
                                            'status': row['status'], 'delivered_at': row['delivered_at']}
                remaining.append(url)
                unresolved[url] = {'url': url, 'title': row['title'] if row else None,
                                   'status': row['status'] if row else 'missing',
                                   'reason': row['decision_reason'] if row else None,
                                   'blocker': blocker}
        complete = not remaining and len(links) == mail['article_count'] and (bool(links) or bool(mail['classification_reason']))
        messages.append({'message_id': mail['message_id'], 'source': mail['source'],
                         'ingested': True, 'workflow_complete': complete,
                         'unresolved_urls': remaining})
    return {'ingested_messages': len(messages),
            'scope_version': scope.get('version'),
            'retired_historical_messages': retired_count,
            'historical_retirement_is_not_review_completion': True,
            'workflow_complete_messages': sum(x['workflow_complete'] for x in messages),
            'workflow_incomplete_messages': sum(not x['workflow_complete'] for x in messages),
            'unresolved_article_count': len(unresolved),
            'legacy_delivery_recovery_needed_count': len(recovery_needed),
            'workflow_complete': all(x['workflow_complete'] for x in messages),
            'messages': messages, 'unresolved_articles': list(unresolved.values()),
            'legacy_delivery_recovery_needed': list(recovery_needed.values())}


if __name__ == '__main__':
    root = Path(__file__).resolve().parents[2]
    cfg = json.loads((root / 'outputs/rss-news-monitor/sources.json').read_text(encoding='utf-8-sig'))
    con = sqlite3.connect((root / 'work/rss-news-monitor.db').as_uri() + '?mode=ro', uri=True)
    try:
        print(json.dumps(audit(con, int(cfg['selection_policy_version'])), ensure_ascii=False))
    finally:
        con.close()
