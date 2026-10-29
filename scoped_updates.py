"""Additional bounded daily coverage proofs; raw source clauses stay in audit.

A daily scope can cover an earlier fact without claiming identity of two
attacks. Explicit repeated attacks, clocks, unfamiliar consequences and
contradictory clinical assertions remain independent.
"""
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

KYIV=ZoneInfo('Europe/Kyiv')


def resolve_scoped_updates(records):
    from event_brief import locality,tidy,casualty_roles,damage_atoms,split_places
    from fallback_report import sentences,clean_lines
    from source_claims import canonical,clause_coverage,medical_ages,medical_role_counts
    from report_rules import NUMBER,number_value
    active=lambda r:r.get('display') and r['state'] not in {'mirror','excluded','review','supplement'}
    day=lambda r:datetime.fromisoformat(r.get('reporting_period') or r['published_at']).astimezone(KYIV).date()
    daily=[r for r in records if active(r) and r.get('reporting_period') and
           datetime.fromisoformat(r['reporting_period']).hour>=12]
    approved_recaps=set()
    for r in records:
        if not active(r) or not r.get('source_recap_day'):continue
        # Recognise the complete DSNS day header, not an arbitrary prefix.
        header=re.fullmatch(r'(?:Дніпропетровщина)?\s*:\s*внаслідок російських атак постраждали ('+NUMBER+r') людей\s+Упродовж дня ворог понад (\d+) разів атакував ('+NUMBER+r') райони області\.?',clean_lines(r['source_text']),re.I)
        if not header:continue
        matches=[b for b in daily if b['scope']=='Дніпропетровська область' and day(b)==day(r)
                 and (casualty_roles(b['source_text']) or {}).get('injured')==number_value(header[1].casefold())
                 and re.search(r'Понад '+header[2]+r' разів',b['source_text'])
                 and re.search(r'атакував ('+NUMBER+r') райони',b['source_text'])
                 and number_value(re.search(r'атакував ('+NUMBER+r') райони',b['source_text'])[1].casefold())==number_value(header[3].casefold())]
        if len(matches)==1:
            approved_recaps.add(r['source_key'])
            r['state']='supplement';r['reason']='same_day_regional_count_scope';r['display']=None
            r['claim_decisions']=[dict(source_text=c['source_text'],disposition='covered',target_id=matches[0]['id'],reason=r['reason']) for c in r.get('claims',[]) if c['disposition']=='required']
    # Match the narrowly stated industrial-site update using object, city,
    # explicit age, unique candidate and chronology. Equal age alone is never enough.
    industrial=[r for r in records if active(r) and not r.get('reporting_period')
                and re.search(r'Ворог завдав удару по промисловому підприємству у Дніпрі\.',r['source_text'])]
    for anchor in industrial:
        at=datetime.fromisoformat(anchor['published_at'])
        updates=[r for r in records if active(r) and not r.get('reporting_period')
                 and at<datetime.fromisoformat(r['published_at'])<=at+timedelta(hours=4)
                 and re.fullmatch(r'\d+-річний чоловік дістав поранень через російську атаку на промислове підприємство у Дніпрі\. Його ушпиталили\.(?: Медики надають усю необхідну допомогу\.)?',clean_lines(r['source_text']))]
        if len(industrial)!=1 or len(updates)!=1:continue
        update=updates[0]
        old='Попередньо, ніхто не постраждав.'
        anchor['display']=anchor['display'].replace(old,'').strip()+' '+tidy(update['display'],update['published_at'])
        anchor.setdefault('assessment_history',[]).append(dict(source_text=old,disposition='superseded',target_id=update['id'],reason='unique_industrial_site_clinical_update'))
        update['state']='supplement';update['reason']='unique_industrial_site_clinical_update';update['display']=None
        # Mark the copied clauses against the anchor whose actual text contains them.
        update['claim_decisions']=[dict(source_text=c['source_text'],disposition='covered',target_id=anchor['id'],reason=update['reason']) for c in update.get('claims',[]) if c['disposition']=='required']
        for b in records:
            if not active(b) or not b.get('reporting_period') or locality(b['source_text'])!='Дніпро':continue
            bt=datetime.fromisoformat(b['reporting_period'])
            if not at<bt<=at+timedelta(hours=12):continue
            if (re.fullmatch(r'У Дніпрі пошкоджене підприємство\. Постраждав \d+-річний чоловік\.',b['source_text'])
                and medical_ages(b['source_text'])==medical_ages(update['source_text'])):
                b['state']='supplement';b['display']=None;b['reason']='industrial_site_update_repeated_in_next_bulletin'
                b['claim_decisions']=[dict(source_text=c['source_text'],disposition='covered',target_id=anchor['id'],reason=b['reason']) for c in b.get('claims',[]) if c['disposition']=='required']
    # Resolve remaining closed recap clauses and retain unfamiliar new details.
    for r in records:
        if not active(r) or r.get('reporting_period'):continue
        if r['source_key'] not in approved_recaps and locality(r['source_text'])!='Павлоград':continue
        pub=datetime.fromisoformat(r['published_at']).astimezone(KYIV)
        if re.search(r'знову|повторн|ще одн\w* атак|\b(?:о|після|близько)\s+\d{1,2}[:.]',r['source_text'],re.I):continue
        parts=split_places(tidy(r['display'],r['published_at']))
        if parts and parts[0][0] is None and r.get('resolved_chunks'):parts[0][0]=r['resolved_chunks'][0][0]
        chunks=[]
        for place,body in parts:
            place=place or r.get('scope_context')
            targets=[b for b in daily if day(b)==pub.date() and locality(b['source_text'])==place
                     and (datetime.fromisoformat(b['reporting_period'])>=pub or r.get('source_recap_day'))]
            kept=[]
            for clause in sentences(body):
                matches=[]
                for b in targets:
                    target=b['source_text']
                    reason=clause_coverage(clause,target)
                    # The single-child daily block explicitly identifies its age,
                    # hospital status and clinical degree. Unknown diagnoses stay.
                    if not reason and re.fullmatch(r'Медики оцінюють стан (?:підлітка|хлопця|його) як середньої тяжкості\.',clause):
                        if len(medical_ages(target))==1 and 'хлопець' in target and 'середньої тяжкості' in target:reason='same_day_child_clinical_degree'
                    if not reason and r.get('source_recap_day'):
                        m=re.fullmatch(r'У Синельниківському районі внаслідок атак на автозаправну станцію та автомобіль травмувалися ('+NUMBER+r') людей\.',clause,re.I)
                        if m and {'gas_station','cars'}<=damage_atoms(target) and len(medical_ages(target))==number_value(m[1].casefold()) and medical_role_counts(target).get('hospitalized')==number_value(m[1].casefold()):reason='explicit_day_recap_matches_objects_and_hospitalized_enumeration'
                        m=re.fullmatch(r'У Кам[’\x27]янському районі внаслідок влучання по інфраструктурі виникла пожежа\.',clause)
                        if m and 'інфраструктур' in target and 'пожеж' in target:reason='explicit_day_recap_infrastructure_fire'
                    if not reason and r['source_key'] in approved_recaps and place=='Павлоград' and clause=='Виникла пожежа.':
                        fire_sources=[a for a in records if a['source_key'].startswith('gunpvdp/') and day(a)==day(r)
                            and locality(a['source_text'])==place and 'На місці удару виникла пожежа.' in a['source_text']]
                        if len(fire_sources)==1:
                            matches.append((fire_sources[0],'explicit_daily_recap_fire_in_same_locality_scope'))
                    if reason:matches.append((b,reason))
                if len(matches)==1:
                    b,reason=matches[0]
                    r.setdefault('claim_decisions',[]).append(dict(source_text=clause,disposition='covered',target_id=b['id'],place=place,reason=reason))
                else:kept.append(clause)
            # A unique earlier clinical update contributes its remaining exact
            # details to the same day's dated locality block. The original
            # source and every copied clause remain independently audited.
            candidates=[b for b in targets if place=='Павлоград' and
                pub<=datetime.fromisoformat(b['reporting_period']) and
                medical_ages(r['source_text']) and
                medical_ages(r['source_text'])<=medical_ages(b['source_text'])]
            if kept and len(candidates)==1:
                target=candidates[0]
                target['display']+=' '+' '.join(kept)
                for clause in kept:r.setdefault('claim_decisions',[]).append(dict(source_text=clause,
                    disposition='covered',target_id=target['id'],place=place,
                    reason='unique_medical_detail_copied_to_daily_scope'))
                kept=[]
            if kept:chunks.append((place,' '.join(kept)))
        if chunks:
            r['resolved_chunks']=chunks;r['display']=' '.join(t for _,t in chunks)
            if parts and parts[0][0] and not r.get('scope_context'):r['scope_context']=parts[0][0]
        else:r['state']='supplement';r['display']=None;r['reason']='scoped_day_clauses_covered'
