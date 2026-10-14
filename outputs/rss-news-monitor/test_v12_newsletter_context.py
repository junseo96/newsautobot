"""Article tracking permission must be bound to exact original full MIME."""
import json
from pathlib import Path
import tempfile
import unittest

from v12_newsletter_context import candidate_link_evidence, local_link_decision


class NewsletterContextTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.cache=self.root/'work/gmail-body-cache'
        self.cache.mkdir(parents=True)
        self.url='https://hello.canarymedia.com/e3t/opaque-story'
        self.candidate={'url':self.url,'newsletter_message_id':'mail123'}

    def envelope(self,label='Major utility approves 2GW battery project',mid='mail123',plain=True):
        parts=[{'mimeType':'text/html','headers':[],'body':{'content':f'<p>New project announcement.</p><a href="{self.url}">{label}</a>'}}]
        if plain:parts.append({'mimeType':'text/plain','headers':[],'body':{'content':self.url}})
        return {'body_complete':True,'message_id':mid,'message':{'id':mid,'payload':{'mimeType':'multipart/alternative','headers':[],'parts':parts}}}

    def store(self,value):
        (self.cache/'mail123.json').write_text(json.dumps(value),encoding='utf-8')

    def test_labeled_article_has_context_and_exact_mail_evidence(self):
        self.store(self.envelope())
        evidence=candidate_link_evidence(self.root,self.candidate)
        self.assertIs(evidence['allowed'],True)
        self.assertEqual(evidence['message_id'],'mail123')
        self.assertIn('2GW',evidence['label'])
        self.assertIsNone(local_link_decision(0,evidence))

    def test_html_unsubscribe_exclusion_dominates_plain_duplicate(self):
        self.store(self.envelope('Unsubscribe'))
        evidence=candidate_link_evidence(self.root,self.candidate)
        self.assertIs(evidence['allowed'],False)
        decision=local_link_decision(0,evidence)
        self.assertEqual(decision['action'],'reviewed')
        self.assertEqual(decision['review_category'],'non_article')
        self.assertIsNone(decision['message_text'])

    def test_missing_incomplete_or_wrong_mail_remains_pending(self):
        for value in (None,{'body_complete':False},self.envelope(mid='other')):
            if value is not None:self.store(value)
            evidence=candidate_link_evidence(self.root,self.candidate)
            self.assertIsNone(evidence['allowed'])
            decision=local_link_decision(0,evidence)
            self.assertEqual(decision['action'],'defer')
            self.assertFalse(decision['verified'])

    def test_opaque_plain_link_is_not_article_permission(self):
        data=self.envelope()
        data['message']['payload']['parts']=data['message']['payload']['parts'][1:]
        self.store(data)
        self.assertIsNone(candidate_link_evidence(self.root,self.candidate)['allowed'])

    def test_no_path_escape_or_cross_link_provenance(self):
        self.store(self.envelope())
        for change in ({'newsletter_message_id':'../mail123'},{'url':self.url+'-other'}):
            self.assertIsNone(candidate_link_evidence(self.root,{**self.candidate,**change})['allowed'])

    def test_unrelated_sources_unchanged(self):
        self.assertIsNone(candidate_link_evidence(self.root,{'url':'https://www.canarymedia.com/articles/storage/news'}))
        self.assertIsNone(local_link_decision(0,None))


if __name__=='__main__':unittest.main()
