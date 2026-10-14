import sqlite3
import unittest
from newsletter_completion import audit


class CompletionTests(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(':memory:')
        self.addCleanup(self.con.close)
        self.con.executescript('''
        CREATE TABLE newsletter_messages(message_id,source,imported_at,article_count,classification_reason);
        CREATE TABLE newsletter_message_articles(message_id,article_url);
        CREATE TABLE articles(url,title,status,delivered_at,decision_policy_version,decision_reason);
        CREATE TABLE delivery_history(url,sent_at);
        CREATE TABLE decision_history(url,status,policy_version,reason);
        INSERT INTO newsletter_messages VALUES('mail','source','now',1,NULL);
        INSERT INTO newsletter_message_articles VALUES('mail','url');
        INSERT INTO articles VALUES('url','title','pending',NULL,NULL,NULL);
        ''')

    def test_pending_brief_archive_and_legacy_delivery_are_incomplete(self):
        for status in ('pending', 'brief', 'archive', 'delivered', 'reviewed'):
            self.con.execute('UPDATE articles SET status=?', (status,))
            self.assertFalse(audit(self.con, 8)['workflow_complete'])

    def test_legacy_delivery_is_an_explicit_receipt_recovery_blocker(self):
        self.con.execute("UPDATE articles SET status='delivered',delivered_at='old-run'")
        result = audit(self.con, 8)
        self.assertEqual(result['legacy_delivery_recovery_needed_count'], 1)
        self.assertEqual(result['legacy_delivery_recovery_needed'][0]['url'], 'url')
        self.assertEqual(result['unresolved_articles'][0]['blocker'], 'legacy_delivery_missing_receipt')

    def test_ack_delivery_completes_and_reopened_article_does_not(self):
        self.con.execute("UPDATE articles SET status='delivered',delivered_at='now'")
        self.con.execute("INSERT INTO delivery_history VALUES('url','now')")
        self.assertTrue(audit(self.con, 8)['workflow_complete'])
        self.con.execute("UPDATE articles SET status='pending'")
        self.assertFalse(audit(self.con, 8)['workflow_complete'])

    def test_current_explicit_review_requires_journal(self):
        self.con.execute("UPDATE articles SET status='reviewed',decision_policy_version=8,decision_reason='outside scope'")
        self.assertFalse(audit(self.con, 8)['workflow_complete'])
        self.con.execute("INSERT INTO decision_history VALUES('url','reviewed',8,'outside scope')")
        self.assertTrue(audit(self.con, 8)['workflow_complete'])
        self.assertFalse(audit(self.con, 9)['workflow_complete'])

    def test_empty_extraction_needs_reason(self):
        self.con.execute('DELETE FROM newsletter_message_articles')
        self.con.execute('UPDATE newsletter_messages SET article_count=0')
        self.assertFalse(audit(self.con, 8)['workflow_complete'])
        self.con.execute("UPDATE newsletter_messages SET classification_reason='subscription confirmation without articles'")
        self.assertTrue(audit(self.con, 8)['workflow_complete'])

    def test_all_links_required(self):
        self.con.execute('UPDATE newsletter_messages SET article_count=2')
        self.con.execute("INSERT INTO newsletter_message_articles VALUES('mail','missing')")
        self.assertEqual(audit(self.con, 8)['unresolved_article_count'], 2)
