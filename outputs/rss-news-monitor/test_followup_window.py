import datetime as dt,unittest
from v12_controls import analysis_candidate,verified_publication_is_fresh
from v11_runtime import _fresh_candidate
class FollowupTests(unittest.TestCase):
    def setUp(self):
        self.now=dt.datetime.fromisoformat('2026-10-08T01:00:00+00:00').timestamp()
        self.c={'title':'Data center power demand McKinsey outlook','summary':'','published_at':'2026-10-02T01:00:00+00:00'}
    def test_six_day_analysis_admitted(self):
        self.assertTrue(_fresh_candidate(self.c,self.now,self.now-30*86400,12))
        self.assertTrue(verified_publication_is_fresh({'source_published_at':self.c['published_at']},self.c,self.now))
    def test_eight_day_analysis_excluded(self):
        old={**self.c,'published_at':'2026-09-30T01:00:00+00:00'}
        self.assertFalse(_fresh_candidate(old,self.now,self.now-30*86400,12))
        self.assertFalse(verified_publication_is_fresh({'source_published_at':old['published_at']},old,self.now))
    def test_non_analysis_retains_twelve_hour_limit(self):
        c={**self.c,'title':'New transformer supply contract'}
        self.assertFalse(analysis_candidate(c))
        self.assertFalse(_fresh_candidate(c,self.now,self.now-30*86400,12))
    def test_future_exact_time_still_rejected(self):
        self.assertFalse(verified_publication_is_fresh({'source_published_at':'2026-10-09T01:00:00+00:00'},self.c,self.now))
if __name__=='__main__':unittest.main()
