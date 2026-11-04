"""Replace closed interim count clauses with an explicit completed city summary.

This is coverage by a later aggregate, not an inferred incident identity.
New incidents, clinical ages, diagnoses and unknown consequences stay intact.
"""
import re
from datetime import datetime
from zoneinfo import ZoneInfo

KYIV=ZoneInfo('Europe/Kyiv')


def resolve_completed_city_assessments(records,diagnostics=None):
    from fallback_report import sentences,clean_lines
    from event_brief import locality,tidy
    from source_claims import canonical
    from report_rules import NUMBER
    active=lambda r:r['section']=='2.1' and r.get('display') and r['state'] not in {'excluded','review','mirror','supplement'}
    finals=[r for r in records if active(r) and not r.get('reporting_period')
            and r['source_key'].split('/')[0].casefold() in {'dnipropetrovskaoda','adm_dp'}
            and re.match(r'\d+ загиблих, \d+ поранених\.|(?:Двоє|Троє) загиблих, \d+ поранених\.',clean_lines(r['source_text']))
            and re.search(r'завершили пошуково-рятувальну операцію на місці ворожої атаки',r['source_text'],re.I)
            and locality(r['source_text'])]
    for final in finals:
        at=datetime.fromisoformat(final['published_at']).astimezone(KYIV)
        city=locality(final['source_text'])
        final_injured=int(re.search(r', (\d+) поранених',final['source_text'])[1])
        if sum(locality(r['source_text'])==city and datetime.fromisoformat(r['published_at']).astimezone(KYIV).date()==at.date() for r in finals)!=1:
            continue
        for r in records:
            if not active(r) or r is final or r.get('reporting_period'):
                continue
            pub=datetime.fromisoformat(r['published_at']).astimezone(KYIV)
            raw=clean_lines(r['source_text'])
            if not (pub.date()==at.date() and pub<at and locality(raw)==city):
                continue
            if re.search(r'знову|повторно (?:атак|вдар)|(?:ще одн|друг|інш)\w* (?:атак|удар)|вокзал|гуртожит',raw,re.I):
                continue
            # Explicit older dates or a different clock may describe a
            # different incident; do not resolve them by publication day.
            from fact_registry import DATE
            dates=list(DATE.finditer(raw))
            from report_rules import MONTHS
            if any((MONTHS.index(m[2].lower())+1,int(m[1]))!=(at.month,at.day) for m in dates):
                continue
            kept=[]
            for clause in sentences(tidy(r['display'],r['published_at'])):
                asserted=re.search(r'(?:До (\d+) зросла|щонайменше (\d+) людей|Підтверджено (\d+) постраждалих|відомо про (\d+) поранених)',clause,re.I)
                if asserted and int(next(g for g in asserted.groups() if g))>final_injured:
                    kept.append(clause)  # A decreasing count is a conflict, not an update.
                    if diagnostics is not None:
                        diagnostics.append(dict(reason='source_conflict',detail='completed_city_count_decreased',sources=[r['source_key'],final['source_key']]))
                    continue
                # These closed numeric fragments can share a sentence with
                # a rescue or damage fact. Keep the remaining text verbatim.
                fragments=[
                    r'У Дніпрі поліція документує наслідки масованих ракетних атак на місто [–—-] щонайменше \d+ людей отримали поранення\s*',
                    r', щонайменше \d+ людей постраждали:',
                    r'«Підтверджено \d+ постраждалих та (?=\d+ врятованих)',
                    r', ймовірніше всього є один загиблий',
                ]
                reduced=clause
                for pattern in fragments:
                    reduced=re.sub(pattern,' ',reduced)
                if reduced!=clause:
                    reduced=re.sub(r'\s+',' ',reduced).strip()
                    original=next((u['source_text'] for u in r.get('claims',[]) if canonical(tidy(u['source_text'],r['published_at']))==canonical(clause)),clause)
                    r.setdefault('assessment_history',[]).append(dict(source_text=original,disposition='superseded',target_id=final['id'],reason='completed_city_count_fragment',retained_fragment=reduced,evidence=final['source_text']))
                    if reduced:kept.append(reduced)
                    continue
                simple = re.fullmatch(
                    r'(?:До \d+ зросла кількість поранених через (?:ворожу )?атаку росіян на '+re.escape(city)+r'|'
                    r'Через атаку росіян на '+re.escape(city)+r' загинула одна людина|'
                    r'Станом на (?:зараз )?відомо про \d+ поранених людей)\.',clause,re.I)
                if not simple:
                    kept.append(clause);continue
                original=next((u['source_text'] for u in r.get('claims',[]) if canonical(tidy(u['source_text'],r['published_at']))==canonical(clause)),clause)
                r.setdefault('assessment_history',[]).append(dict(source_text=original,disposition='superseded',target_id=final['id'],reason='completed_city_summary_count',evidence=final['source_text']))
            if kept:
                r['display']=' '.join(kept)
                if not r.get('scope_context'):r['scope_context']=city
            else:
                r['state']='supplement';r['display']=None;r['reason']='completed_city_summary_count'
