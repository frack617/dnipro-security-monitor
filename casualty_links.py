"""Link a scoped casualty summary to a uniquely supported detailed account.

Age equality alone is never a person's identity. A link additionally requires
one event group, the same reporting day and district, a specific community
listed in the summary, an equal explicit injury count, and an earlier source.
Uncertain matches remain in the text. Original source claims stay in audit.
"""
import re
from datetime import datetime
from zoneinfo import ZoneInfo

KYIV=ZoneInfo('Europe/Kyiv')
CHILD=re.compile(r'\b(\d+)-річн(?:ий|ого|ому|а|ої|у)\s+(хлоп(?:ець|ця|чик\w*)|дівчин\w*)',re.I)
SUMMARY_NOTE='описаний вище випадок уже враховано'
TOTALS_NOTE='Обласні й районні підсумки стосуються вказаних періодів; їх не додають до чисел окремих подій.'


def child_signatures(text):
    return {(int(age),'boy' if word.casefold().startswith('хлоп') else 'girl') for age,word in CHILD.findall(text)}


def summary_links(records, overlap):
    from event_brief import casualty_roles,locality
    from report_rules import NUMBER,number_value,community_stems
    from fallback_report import sentences
    # Only the pre-existing bounded episode resolver can join two sources.
    # Other records remain independent candidates, even for equal ages.
    joined={r['id'] for r,_,_ in overlap}
    candidates=[]
    for r in records:
        if r.get('reporting_period') or not r.get('display'):continue
        text=r['source_text'];children=child_signatures(text)
        roles=casualty_roles(text) or {}
        community=community_stems(text)
        if (len(children)!=1 or not roles.get('injured') or len(community)!=1 or
            re.search(r'знову|повторн|ще одн\w* атак|вчора|позавчора|минулого',text,re.I)):
            continue
        place=locality(text)
        if place:candidates.append((r,children.pop(),roles['injured'],community,place))
    links=[]
    pattern=re.compile(r'(?:Ще )?('+NUMBER+r') (?:людей|осіб), серед яких (\d+)-річн(?:ий|а) (хлопець|хлопчик|дівчинка), постраждали\.',re.I)
    for summary in records:
        at=summary.get('reporting_period')
        if not at or datetime.fromisoformat(at).hour<12:continue
        place=locality(summary['source_text']);communities=community_stems(summary['source_text'])
        for sentence in sentences(summary['source_text']):
            match=pattern.fullmatch(sentence)
            if not match:continue
            signature=(int(match[2]),'boy' if match[3].casefold().startswith('хлоп') else 'girl')
            count=number_value(match[1].casefold());end=datetime.fromisoformat(at)
            sightings=[r for r in records if not r.get('reporting_period') and r.get('display')
                       and signature in child_signatures(r['source_text']) and locality(r['source_text'])==place
                       and datetime.fromisoformat(r['published_at']).astimezone(KYIV).date()==end.date()
                       and datetime.fromisoformat(r['published_at'])<=end]
            if (len({('joined' if r['id'] in joined else r['id']) for r in sightings})!=1 or
                any(re.search(r'знову|повторн|ще одн\w* атак',r['source_text'],re.I) for r in sightings)):
                continue
            compatible=[r for r,child,n,community,where in candidates
                        if child==signature and n==count and where==place and community<=communities
                        and datetime.fromisoformat(r['published_at']).astimezone(KYIV).date()==end.date()
                        and datetime.fromisoformat(r['published_at'])<=end]
            groups={('joined' if r['id'] in joined else r['id']) for r in compatible}
            if len(groups)!=1:continue
            # Direct evidence of the age and count must survive in the
            # actual public paragraph. A pointer to the source is inadequate.
            age_targets=[];count_targets=[]
            for event in compatible:
                for claim in event.get('claims',[]):
                    if claim['disposition']!='required':continue
                    text=claim['source_text']
                    if signature in child_signatures(text):
                        age_targets.append({'text':text,'published_at':event['published_at']})
                    if (casualty_roles(text) or {}).get('injured')==count:
                        count_targets.append({'text':text,'published_at':event['published_at']})
            if not age_targets or not count_targets:continue
            links.append(dict(record_id=summary['id'],source_text=sentence,
                              summary_text='',
                              place=place,reporting_period=at,summary_context=sentences(summary['source_text'])[0],age=signature[0],sex=signature[1],injured=count,
                              event_ids=[r['id'] for r in compatible],age_targets=age_targets,count_targets=count_targets,
                              reason='unique_scoped_event_and_equal_injury_total',scope_relation='includes'))
    return links


def projection_present(source, report, published=None):
    from event_brief import tidy
    from operational_prose import concise
    from source_claims import surface_key
    original=tidy(source,published)
    if not original.endswith(('.', '!', '?')):original+='.'
    return any(surface_key(form) in surface_key(report) for form in (original,concise(original)))


def link_is_visible(link, report):
    from event_brief import date_label
    m=re.search(r'(?m)^'+re.escape(link['place'])+r':\n([^\n]+)',report)
    if not m:return False
    paragraph=m[1];at=datetime.fromisoformat(link['reporting_period'])
    # The reference belongs to its dated summary, not another day/count.
    from source_claims import canonical
    marker=canonical(date_label(at)+' '+link['summary_context'])
    if marker not in canonical(paragraph):return False
    return (any(projection_present(t['text'],paragraph,t['published_at']) for t in link['age_targets']) and
            any(projection_present(t['text'],paragraph,t['published_at']) for t in link['count_targets']))


def duplicate_summary_issues(registry, report):
    """Detect reintroduced person details despite the aggregate reference."""
    from event_brief import tidy
    issues=[]
    for link in registry.get('casualty_summary_links',[]):
        m=re.search(r'(?m)^'+re.escape(link['place'])+r':\n([^\n]+)',report)
        if m:
            occurrences=[(int(age),'boy' if word.casefold().startswith('хлоп') else 'girl') for age,word in CHILD.findall(m[1])]
            if occurrences.count((link['age'],link['sex']))>1 or projection_present(link['source_text'],m[1]):
                issues.append('duplicate_casualty_detail')
        if not link_is_visible(link,report):issues.append('unresolved_casualty_summary')
    return list(dict.fromkeys(issues))
