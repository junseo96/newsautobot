import base64
import json
import tempfile
import unittest
from pathlib import Path

import v11_gmail as gmail


def envelope(html_text, plain=""):
    def part(mime, text):
        return {"mime_type": mime, "headers": [], "parts": None, "body": {
            "size": len(text.encode()),
            "base64_url_content": base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")}}
    return {"message_id": "mail1", "body_complete": True, "message": {
        "id": "mail1", "internal_date": "1790200000000", "payload": {
            "mime_type": "multipart/alternative", "headers": [
                {"name": "From", "value": "Utility News <news@example.com>"},
                {"name": "Subject", "value": "Industry update"}],
            "parts": [part("text/plain", plain), part("text/html", html_text)]}}}


class GmailExtractionTests(unittest.TestCase):
    def test_full_mime_all_links_dedup_preserves_article_id(self):
        data = envelope('<a href="https://example.com/news?id=41&utm_source=mail">발전소 승인</a>'
                        '<a href="https://example.com/news?id=42"><img alt="Transformer order"></a>',
                        'https://example.com/news?id=41&utm_source=mail')
        mail, report = gmail.extract_message(data)
        self.assertEqual([a['url'] for a in mail['articles']],
                         ['https://example.com/news?id=41', 'https://example.com/news?id=42'])
        self.assertEqual(mail['articles'][0]['title'], '발전소 승인')
        self.assertEqual(mail['articles'][1]['title'], 'Transformer order')
        self.assertEqual(report['text_parts'], 2)
        self.assertFalse(report['editorial_completion_claimed'])

    def test_keep_sponsored_technical_material_and_unresolved_tracker(self):
        mail, report = gmail.extract_message(envelope(
            '<a href="https://click.example.com/a/123">BESS thermal performance webinar</a>'
            '<a href="https://example.com/sponsor/report">Sponsored utility report</a>'))
        self.assertEqual(len(mail['articles']), 2)
        self.assertEqual(report['unresolved_tracking'], ['https://click.example.com/a/123'])

    def test_excludes_actions_before_and_after_unwrapping(self):
        data = envelope('<a href="https://example.com/click?id=1">Unsubscribe</a>'
                        '<a href="https://click.example.com/?url=https%3A%2F%2Fexample.com%2Funsubscribe">Open</a>'
                        '<a href="https://example.com/account/settings">Settings</a>'
                        '<a href="http://127.0.0.1/private">Local</a>')
        mail, report = gmail.extract_message(data)
        self.assertEqual(mail['articles'], [])
        self.assertEqual(len(report['excluded_links']), 4)
        self.assertNotIn('non_article_reason', mail)
        self.assertTrue(report['manual_mail_classification_required'])

    def test_embedded_destination_is_decoded_without_network(self):
        target = 'https://example.com/article?idxno=77&sp_eh=tracking'
        encoded = base64.urlsafe_b64encode(target.encode()).decode().rstrip('=')
        mail, report = gmail.extract_message(envelope(f'<a href="https://click.example.com/{encoded}">Grid</a>'))
        self.assertEqual(mail['articles'][0]['url'], 'https://example.com/article?idxno=77')
        self.assertEqual(report['unresolved_tracking'], [])

    def test_snippet_and_missing_text_attachment_are_not_full_body(self):
        with self.assertRaises(ValueError):
            gmail.extract_message({'message_id': 'mail1', 'body_complete': True,
                                   'message': {'id': 'mail1', 'snippet': 'Not full'}})
        data = envelope('ok')
        data['message']['payload']['parts'][1]['body'] = {'attachment_id': 'missing', 'size': 500}
        with self.assertRaises(ValueError):
            gmail.extract_message(data)

    def test_resolved_action_destination_still_rejected(self):
        mail, report = gmail.extract_message(envelope('<a href="https://click.example.com/a">Read</a>'),
                                             {'https://click.example.com/a': 'https://example.com/unsubscribe'})
        self.assertEqual(mail['articles'], [])

    def test_one_bad_cache_does_not_block_ready_newsletters(self):
        with tempfile.TemporaryDirectory() as directory:
            valid = Path(directory) / 'valid.json'
            invalid = Path(directory) / 'invalid.json'
            valid.write_text(json.dumps(envelope('<a href="https://example.com/news/1">Grid</a>')), encoding='utf-8')
            invalid.write_text('{bad json', encoding='utf-8')
            newsletter, report = gmail.build_newsletter([invalid, valid])
            self.assertEqual(len(newsletter['messages']), 1)
            self.assertTrue(report['messages'][0]['extraction_failed'])
            self.assertTrue(report['messages'][1]['import_ready'])

    def test_body_only_mail_needs_editorial_classification(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / 'body.json'
            cache.write_text(json.dumps(envelope('<p>New generation permit decision without a link.</p>')), encoding='utf-8')
            newsletter, report = gmail.build_newsletter([cache])
            self.assertEqual(newsletter['messages'], [])
            self.assertTrue(report['messages'][0]['manual_mail_classification_required'])

    def test_footer_navigation_does_not_become_article_work(self):
        mail, report = gmail.extract_message(envelope(
            '<a href="https://click.example.com/policy">Privacy Policy</a>'
            '<a href="https://example.com/terms-of-use">Legal</a>'
            '<a href="https://www.linkedin.com/sharing/share-offsite/?url=https://example.com/news">Share</a>'
            '<a href="https://example.com/news/privacy-policy-shapes-grid-data">Grid data privacy policy</a>'
            '<a href="https://example.com/sponsor/report">Sponsored utility report</a>'))
        self.assertEqual(len(mail['articles']), 2)
        self.assertEqual(len(report['excluded_links']), 3)
        self.assertEqual(report['unresolved_tracking'], [])

    def test_generic_read_more_uses_article_slug_not_tracking_id(self):
        mail, report = gmail.extract_message(envelope(
            '<a href="https://example.com/news/duke-new-grid-investment">Read more</a>'
            '<a href="https://click.example.com/a/123456">Read more</a>'))
        self.assertEqual(mail['articles'][0]['title'], 'duke new grid investment')
        self.assertEqual(mail['articles'][1]['title'], 'Read more')

    def test_labeled_footer_cannot_return_through_plaintext_variant(self):
        target = 'https://hello.canarymedia.com/e3t/Ctc/opaque-footer'
        data = envelope('<a href="' + target + '?utm_source=email">Unsubscribe</a>', target)
        mail, report = gmail.extract_message(data)
        self.assertEqual(mail['articles'], [])
        self.assertFalse(gmail.link_evidence(data)[target]['allowed'])
        self.assertEqual(report['candidate_links'], 0)

    def test_descriptive_anchor_replaces_earlier_empty_image_without_token_title(self):
        target = 'https://hello.canarymedia.com/e3t/Ctc/' + 'OpaqueTOKEN' * 20
        data = envelope('<a href="' + target + '"><img src="image.png"></a>'
                        '<p>A state approved a major transmission investment today. '
                        '<a href="' + target + '">Commission transmission decision</a></p>', target)
        mail, _ = gmail.extract_message(data)
        self.assertEqual(len(mail['articles']), 1)
        self.assertEqual(mail['articles'][0]['title'], 'Commission transmission decision')
        evidence = gmail.link_evidence(data)[target]
        self.assertTrue(evidence['allowed'])
        self.assertIn('major transmission', evidence['context'])

    def test_unlabelled_opaque_tracker_preserves_unknown_purpose_without_fake_title(self):
        target = 'https://hello.canarymedia.com/e3t/Ctc/' + 'OpaqueTOKEN' * 20
        data = envelope('<a href="' + target + '"><img src="image.png"></a>', target)
        mail, _ = gmail.extract_message(data)
        self.assertNotIn('OpaqueTOKEN', mail['articles'][0]['title'])
        self.assertIsNone(gmail.link_evidence(data)[target]['allowed'])

    def test_rejected_opaque_anchor_label_does_not_reappear_as_title(self):
        target = 'https://hello.canarymedia.com/e3t/Ctc/' + 'OpaqueTOKEN' * 20
        data = envelope('<a href="'+target+'">'+target+'</a>')
        mail, _ = gmail.extract_message(data)
        self.assertEqual(gmail.link_evidence(data)[target]['label'], '')
        self.assertEqual(mail['articles'][0]['title'], 'Industry update - unlabelled newsletter link')

    def test_privacy_label_wins_over_another_human_label_for_same_tracker(self):
        target = 'https://hello.canarymedia.com/e3t/Ctc/opaque'
        data = envelope('<a href="' + target + '">Policy updates</a>'
                        '<a href="' + target + '">Privacy Policy</a>', target)
        self.assertFalse(gmail.link_evidence(data)[target]['allowed'])
        self.assertEqual(gmail.extract_message(data)[0]['articles'], [])

    def test_explicit_parenthesized_plain_article_link_retains_real_label(self):
        target = 'https://hello.canarymedia.com/e3t/Ctc/plain-variant'
        data = envelope('', 'Commission approves a new 2 GW transmission project (' + target + ')\n')
        evidence = gmail.link_evidence(data)[target]
        self.assertTrue(evidence['allowed'])
        self.assertFalse(evidence['from_html'])
        self.assertEqual(evidence['reason'], 'explicit_plain_article_link')
        self.assertEqual(gmail.extract_message(data)[0]['articles'][0]['title'],
                         'Commission approves a new 2 GW transmission project')

    def test_plain_footer_variant_is_blocked_and_bare_url_is_not_inferred(self):
        footer = 'https://hello.canarymedia.com/e3t/Ctc/plain-footer'
        bare = 'https://hello.canarymedia.com/e3t/Ctc/bare'
        data = envelope('', 'Unsubscribe (' + footer + ')\nA news headline on another line\n' + bare)
        evidence = gmail.link_evidence(data)
        self.assertFalse(evidence[footer]['allowed'])
        self.assertIsNone(evidence[bare]['allowed'])
        self.assertEqual(evidence[bare]['label'], '')
        self.assertEqual(len(gmail.extract_message(data)[0]['articles']), 1)

    def test_plain_account_action_label_never_allows_an_opaque_route(self):
        target = 'https://hello.canarymedia.com/e3t/Ctc/account'
        self.assertFalse(gmail.link_evidence(envelope('', 'Reset your password ('+target+')'))[target]['allowed'])

    def test_publisher_logo_home_label_stays_unknown_despite_long_context(self):
        target = 'https://hello.canarymedia.com/e3t/Ctc/logo'
        context = 'Major transmission and generation investment announcement. ' * 4
        for label in ('Canary Media', 'website', 'page', 'Home', 'click here'):
            with self.subTest(label=label):
                data = envelope('<p>'+context+'<a href="'+target+'">'+label+'</a></p>')
                self.assertIsNot(gmail.link_evidence(data)[target]['allowed'], True)
        data = envelope('<p>'+context+'<a href="'+target+'">Read more</a></p>')
        self.assertTrue(gmail.link_evidence(data)[target]['allowed'])


if __name__ == '__main__':
    unittest.main()
