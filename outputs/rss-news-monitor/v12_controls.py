"""Deterministic final checks independent of an analyst's prose."""
import datetime as dt
import re

def analysis_candidate(candidate):
    """Admission hint only. Original review, importance and receipts still gate send."""
    text=(candidate.get('title','')+' '+candidate.get('summary','')).lower()
    industry=re.search(r'전력|송전|배전|변압|hvdc|ppa|데이터센터|data.?cent(?:er|re)|electricity|power demand|grid|interconnection|turbine',text)
    analysis=re.search(r'분석|전망|보고서|연구|실증|검증|성능|forecast|outlook|report|research|study|mckinsey|insight|interview|demand.{0,60}(?:grow|project)|(?:grow|project).{0,60}demand',text)
    return bool(industry and analysis)


def publication_day_bounds(value):
    """Timezone-unspecified calendar date; never assert a midnight timestamp."""
    day=dt.date.fromisoformat(str(value)[:10])
    midnight=dt.datetime.combine(day,dt.time.min,dt.timezone.utc).timestamp()
    # A publisher's date can be anywhere from UTC+14 to UTC-12. Preserve the
    # uncertainty, including Korean morning news dated later than UTC today.
    return midnight-14*3600,midnight+36*3600


def verified_publication_is_fresh(decision, candidate, now, max_age_hours=12):
    if analysis_candidate(candidate):max_age_hours=max(max_age_hours,168)
    value=decision.get('source_published_at')
    if not value:return False
    try:
        published=dt.datetime.fromisoformat(value.replace('Z','+00:00'))
        published=published.replace(tzinfo=published.tzinfo or dt.timezone.utc).timestamp()
    except (ValueError,TypeError):return False
    date_only=len(value)==10
    if date_only:published,upper=publication_day_bounds(value)
    else:upper=published
    # A date-only publication is an explicitly coarse interval, not midnight.
    if published<=now+300 and upper>=now-max_age_hours*3600:
        return True
    received=candidate.get('newsletter_received_at')
    try:mail=dt.datetime.fromisoformat(received.replace('Z','+00:00')).timestamp()
    except (ValueError,TypeError,AttributeError):return False
    return now-max_age_hours*3600<=mail<=now and published<=mail+300 and upper>=mail-24*3600
