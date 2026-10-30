"""Bounded transport-station casualty updates, without adding patient counts.

Requires one city, one station, no second-attack marker and compatible explicit
incident dates/clocks. Unknown consequences survive verbatim. A new death
count supersedes an older assessment, never changes an old bulletin's clock.
"""
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from fallback_report import sentences, clean_lines

KYIV=ZoneInfo('Europe/Kyiv')
STATION=re.compile(r'залізничн\w* вокзал|перон|електропотяг',re.I)


def death_count(text):
    for pattern in [r'кількість загиблих.{0,100}зросла до (\d+)',
                    r'До (\d+) зросла кількість загиблих',
                    r'(\d+) (?:людей )?загинули',r'(\d+) загиблих']:
        m=re.search(pattern,text,re.I)
        if m:return int(m[1])
    return None


def resolve_incident_updates(records, diagnostics=None):
    from event_brief import locality,tidy
    from source_claims import canonical
    from report_rules import MONTHS,NUMBER,number_value
    active=lambda r:r['section']=='2.1' and r.get('display') and r['state'] not in {'excluded','review','mirror','supplement'}
    group=[r for r in records if active(r) and not r.get('reporting_period')
           and STATION.search(r['source_text']) and locality(r['source_text'])=='Дніпро']
    if len(group)<2:return
    group.sort(key=lambda r:r['published_at'])
    first=datetime.fromisoformat(group[0]['published_at']).astimezone(KYIV)
    # A preliminary city fatality count may be linked only when the same
    # authority explicitly repeats that count for the unique station within
    # 90 minutes. Other objects, cities and a second fatal episode disable it.
    initial_counts={death_count(r['source_text']) for r in group[:4]}-{None}
    competing_fatal=any(active(r) and not r.get('reporting_period') and not STATION.search(r['source_text'])
        and locality(r['source_text'])=='Дніпро' and death_count(r['source_text']) is not None
        and re.search(r'будин|підприємств|гуртожит|магазин|іншу',r['source_text'],re.I)
        and first-timedelta(minutes=90)<=datetime.fromisoformat(r['published_at']).astimezone(KYIV)<=first+timedelta(minutes=90)
        for r in records)
    for r in records:
        if not active(r) or r in group or r.get('reporting_period'):continue
        raw=clean_lines(r['source_text'])
        at=datetime.fromisoformat(r['published_at']).astimezone(KYIV)
        if (not competing_fatal and r['source_key'].split('/')[0].casefold()=='dnipropetrovskaoda'
            and first-timedelta(minutes=90)<=at<=first
            and re.fullmatch(r'\d+ людей загинули через атаку росіян на Дніпро\. Дістали поранень щонайменше [\wʼ’]+\.(?: Медики надають усім необхідну допомогу\.)?',raw)
            and death_count(raw) in initial_counts):
            group.append(r)
    # Earlier clinical updates have no station noun, but identify the same
    # unique child and are bounded by the first station notice and the latest
    # station medical assessment. Never link a count alone or a new object.
    child_ages=set(re.findall(r'(\d+)-річн\w* хлоп', ' '.join(r['source_text'] for r in group), re.I))
    specific_medical=[r for r in group if re.search(r'вже \d+ поранених через атаку росіян на залізничний вокзал',r['source_text'],re.I)]
    if len(child_ages)==1 and len(specific_medical)==1:
        medical_at=datetime.fromisoformat(specific_medical[0]['published_at']).astimezone(KYIV)
        for r in records:
            if not active(r) or r in group or r.get('reporting_period'):continue
            raw=clean_lines(r['source_text'])
            at=datetime.fromisoformat(r['published_at']).astimezone(KYIV)
            if (first<=at<medical_at<=first+timedelta(hours=4)
                and r['source_key'].split('/')[0].casefold()=='dnipropetrovskaoda'
                and locality(raw)=='Дніпро'
                and re.match(r'(?:До \d+ зросла кількість поранених через ворожу атаку на Дніпро|Вже \d+ поранених через ворожий удар по Дніпру)\.',raw)
                and set(re.findall(r'(\d+)-річн\w* хлоп',raw,re.I))==child_ages
                and not re.search(r'підприємств|гуртожит|магазин|іншу|повторн|знову',raw,re.I)):
                group.append(r)
    group.sort(key=lambda r:r['published_at'])
    first=datetime.fromisoformat(group[0]['published_at']).astimezone(KYIV)
    last=datetime.fromisoformat(group[-1]['published_at']).astimezone(KYIV)
    combined=' '.join(r['source_text'] for r in group)
    # Do not infer one attack across two dated events or a repeat marker.
    dates={(int(m[1]),m[2].casefold()) for m in re.finditer(r'(\d{1,2}) ('+'|'.join(MONTHS)+r')',combined,re.I)}
    clocks=set(re.findall(r'(?:близько|о)\s+(\d{1,2}(?::\d{2}|-ї))',combined,re.I))
    if (last-first>timedelta(hours=24) or len(dates)>1 or len(clocks)>1
        or re.search(r'повторн\w* (?:атак|удар)|ще одн\w* (?:атак|удар)|знову|вкотре',combined,re.I)
        or re.search(r'вокзал\w*\s+[«“\"]',combined,re.I)):
        return
    updates=[(r,death_count(r['source_text'])) for r in group if death_count(r['source_text']) is not None]
    latest=updates[-1] if updates else None
    # Conflicting/reduced numbers are not silently repaired by taking a max.
    if updates and any(a[1]>b[1] for a,b in zip(updates,updates[1:])):
        if diagnostics is not None:
            diagnostics.append({'reason':'source_conflict','detail':'station_mortality_count_decreased','sources':[r['source_key'] for r,n in updates]})
        return
    anchor=group[0]
    # Only a fully recognised count-only assessment is replaceable. Mixed
    # clinical or physical consequences are copied in full.
    def count_assessment(clause):
        m=re.fullmatch(r'(?:Ще|Дістали поранень щонайменше) ('+NUMBER+r')(?: людей)?(?: постраждали)?\.',clause,re.I)
        if m:return {'injured':number_value(m[1].casefold())}
        m=re.fullmatch(r'(?:До (\d+) зросла кількість поранених через ворожу атаку на Дніпро|Вже (\d+) поранених через ворожий удар по Дніпру)\.',clause)
        if m:return {'injured':int(m[1] or m[2])}
        m=re.fullmatch(r'Внаслідок влучання по електропотягу загинули (\d+) людей, ще (\d+) отримали поранення\.',clause)
        if m:return {'dead':int(m[1]),'injured':int(m[2])}
        return None
    latest_injury=None
    for r in group:
        match=re.search(r'У Дніпрі вже (\d+) поранених через атаку росіян на залізничний вокзал\.',r['source_text'])
        if match:latest_injury=(r,int(match[1]))
    clinical_evidence=[]
    if latest_injury:
        body=clean_lines(latest_injury[0]['source_text'])
        clinical_evidence=[s for s in sentences(body) if re.fullmatch(
            r'(?:'+NUMBER+r' - у тяжкому стані|\d+ із них госпіталізовані)\.',s,re.I)]
    seen={};parts=[]
    for r in group:
        kept=[]
        for clause in sentences(tidy(r['display'],r['published_at'])):
            original_clause=clause
            count=death_count(clause)
            # Only complete simple mortality assessments can be superseded;
            # a combined death/injury or unknown consequence stays intact.
            simple=bool(re.fullmatch(r'(?:На жаль, станом на (?:зараз )?відомо про \d+ загиблих|\d+ людей загинули (?:через|внаслідок) атаку росіян на Дніпро|До \d+ зросла кількість загиблих унаслідок удару російського безпілотника по залізничному вокзалу у Дніпрі)\.',clause,re.I))
            if latest and count is not None and count<latest[1] and simple:
                r.setdefault('assessment_history',[]).append(dict(source_text=next((c['source_text'] for c in r.get('claims',[]) if canonical(tidy(c['source_text'],r['published_at']))==canonical(original_clause)),clause),disposition='superseded',target_id=latest[0]['id'],reason='incident_station_death_update',evidence=latest[0]['source_text']))
                continue
            assessment=count_assessment(clause)
            if assessment and latest_injury and latest and all(
                    value<=(latest[1] if role=='dead' else latest_injury[1])
                    for role,value in assessment.items()):
                evidence='Кількість загиблих унаслідок цієї атаки зросла до '+str(latest[1])+'. '+latest_injury[0]['source_text']
                r.setdefault('assessment_history',[]).append(dict(
                    source_text=next((c['source_text'] for c in r.get('claims',[]) if canonical(tidy(c['source_text'],r['published_at']))==canonical(original_clause)),clause),
                    disposition='superseded',target_id=latest[0]['id'],reason='incident_station_counts_update',
                    evidence=evidence,expected_injured=latest_injury[1]))
                continue
            if (latest_injury and len(clinical_evidence)==2 and not STATION.search(r['source_text'])
                and re.fullmatch(r'(?:Троє людей госпіталізовані у важкому стані|Четверо людей у тяжкому стані|Стан решти поранених медики оцінюють як середньої тяжкості|Усі у лікарні)\.',clause)):
                r.setdefault('assessment_history',[]).append(dict(
                    source_text=next((c['source_text'] for c in r.get('claims',[]) if canonical(tidy(c['source_text'],r['published_at']))==canonical(original_clause)),original_clause),
                    disposition='superseded',target_id=latest_injury[0]['id'],reason='incident_clinical_snapshot_update',
                    evidence_fragments=clinical_evidence))
                continue
            if r not in specific_medical and re.match(r'Це \d+-річний хлопчик, чоловіки ',clause):
                clause='Серед постраждалих — '+clause.removeprefix('Це ')
            key=canonical(clause)
            if key in seen:
                r.setdefault('claim_decisions',[]).append(dict(source_text=next((c['source_text'] for c in r.get('claims',[]) if canonical(tidy(c['source_text'],r['published_at']))==canonical(original_clause)),clause),disposition='covered',target_id=anchor['id'],reason='incident_copied_clause',evidence=clause))
                continue
            seen[key]=r['id'];kept.append(clause)
            if r is not anchor:
                r.setdefault('claim_decisions',[]).append(dict(source_text=next((c['source_text'] for c in r.get('claims',[]) if canonical(tidy(c['source_text'],r['published_at']))==canonical(original_clause)),clause),disposition='covered',target_id=anchor['id'],reason='incident_copied_clause',evidence=clause))
        parts+=kept
        if r is not anchor:
            r['display']=None;r['state']='supplement';r['reason']='unique_station_update_chain'
    anchor['display']=' '.join(parts)
    anchor['scope_context']='Дніпро'
    anchor['resolved_chunks']=[('Дніпро',anchor['display'])]
    # Archive the earlier regional mortality assessment in its own ledger.
    # The amended number remains in the station paragraph, not relabelled as
    # having been known at yesterday's reporting clock.
    if latest:
        for r in records:
            if not active(r) or not r.get('reporting_period'):continue
            body=r['source_text']
            if r['scope']!='Дніпропетровська область' or not STATION.search(body):continue
            if not first<=datetime.fromisoformat(r['published_at']).astimezone(KYIV)<=last:continue
            for clause in sentences(body):
                original_clause=clause
                if re.fullmatch(r'\d+ людей загинули внаслідок російської атаки на залізничний вокзал\.',clause) and death_count(clause)<latest[1]:
                    r['public_header_body']=body.replace(clause,'').strip()
                    r.setdefault('assessment_history',[]).append(dict(source_text=next((c['source_text'] for c in r.get('claims',[]) if canonical(tidy(c['source_text'],r['published_at']))==canonical(original_clause)),clause),disposition='superseded',target_id=latest[0]['id'],reason='incident_station_death_update',evidence=latest[0]['source_text']))
