"""Source sentence ledger and conservative selection for operational records.

Predicates describe a clause; they never decide whether an unfamiliar clause
is disposable. Unknown clauses are opaque obligations, retained verbatim.
Only complete recognised editorial/administrative formulas are excluded.
"""
import hashlib
import re
from datetime import datetime
from zoneinfo import ZoneInfo
from fallback_report import clean_lines, sentences

PREDICATES = {
    'casualty': r'поран|постраждал|травм|загин|загиб|госпітал|лікарні|тяжк|важк\w* стан',
    'evacuation': r'еваку|відселен|відселено|без житла',
    'rescue': r'врят|вивели|пошук|шукають|з-під завал',
    'restriction': r'перекрит|закрит|обмежен|призупинен',
    'service': r'без світла|без води|знеструм|електропостач|водопостач',
    'damage': r'пошкодж|знищ|понівеч|зруйн|вигор|потрощ',
    'fire': r'пожеж|займан|горів|горіла|загас',
    'attack': r'атак|обстріл|влучан|завдав удар|цілив',
}


def canonical(text):
    from brief_editor import normalize_names
    return re.sub(r'[^\w]+',' ',normalize_names(text).casefold().replace('ʼ','’')).strip()


def boilerplate(text):
    """Never match a prefix: an additional consequence makes the clause stay."""
    patterns = [
        r'Наслідки уточнюємо[.!]?',
        r'Загроза для міста зберігається[.!]?',
        r'Залишайтеся у безпечних місцях до відбою повітряної тривоги[.!]?',
        r'Медики надають усю необхідну допомогу[.!]?',
        r'Потерпілим надають необхідну медичну допомогу[.!]?',
        r'На місці працюють усі екстрені служби[.!]?',
        r'Остаточні наслідки атаки встановлюють слідчо-оперативні групи поліції[.!]?',
        r'Правоохоронці документують наслідки обстрілу в межах кримінального провадження, відкритого за ч\. 1 ст\. 438 Кримінального кодексу України[.!]?',
        r'Медики надають (?:їм|постраждалим) (?:усю необхідну )?допомогу[.!]?',
        r'Інформацію (?:про|щодо) постраждалих уточнюємо[.!]?',
        r'Загроза(?: для міста)? триває[.!]?',
        r'До відбою повітряної тривоги залишайтеся у безпечних місцях[.!]?',
        r'(?:До відбою )?[Зз]алишайтеся в укриттях[.!]?',
        r'Бережіть себе[.!]?',
        r'Із заявками на державне «єВідновлення» людям допомагають працівники адміністрації [А-ЯІЇЄҐа-яіїєґ’\x27-]+ району[.!]?',
        r'Сайт(?:\s+(?:Fb|X|IG|YT|TT))+[.!]?',
        r'(?:На місці події|На місці|Профільні служби) працюють (?:усі профільні служби|зокрема міські служби та благодійники)[.!]?',
        r'Поліцейські документують наслідки ворожих атак на місто Дніпро[.!]?',
        r'Поліція працює на місці ворожого удару у місті Дніпрі[.!]?',
        r'Слідчі поліції документують наслідки чергового воєнного злочину рф, проводять огляди пошкоджених будинків та фіксують руйнування[.!]?',
        r'Наразі правоохоронці встановлюють остаточні масштаби руйнувань і пошкоджень[.!]?',
        r'Робота на місці атаки триває[.!]?',
        r'Поліція продовжує працювати на місцях ворожих атак, фіксувати руйнування та надавати необхідну допомогу громадянам[.!]?',
    ]
    return any(re.fullmatch(p,text,re.I) for p in patterns)


def select_units(text, source_key='', published_at=None, reporting_period=None, scope=None):
    units=[];offset=0
    # Remove only standalone editorial headings before sentence tokenisation;
    # a heading sharing a line with a concrete fact cannot match boilerplate.
    lines=[line for line in text.splitlines() if not boilerplate(clean_lines(line))]
    for i in range(len(lines)-1):
        if (len(lines[i].strip())>15 and not re.search(r'[.!?:;]$',lines[i].strip()) and
            (re.match(r'\d{1,2}\s+[а-яіїєґ]+\s+(?:ворог|росіяни)\b',lines[i+1].strip(),re.I) or
             re.match(r'(?:Внаслідок|Унаслідок|Сьогодні)\b',lines[i+1].strip()))):
            lines[i]+='.'
    body=' '.join(lines)
    body=clean_lines(body)
    # Protect the legal abbreviation sentence from the generic tokenizer.
    body=re.sub(r'Правоохоронці документують наслідки обстрілу в межах кримінального провадження, відкритого за ч\. 1 ст\. 438 Кримінального кодексу України\.(?=\s|$)', '', body).strip()
    for index,sentence in enumerate(sentences(body)):
        start=body.find(sentence,offset)
        end=start+len(sentence) if start>=0 else None
        if end is not None:offset=end
        excluded=boilerplate(sentence)
        predicates=[k for k,p in PREDICATES.items() if re.search(p,sentence,re.I)]
        from event_brief import casualty_roles
        units.append(dict(id=hashlib.sha256((source_key+'\0'+str(index)+'\0'+sentence).encode()).hexdigest()[:24],
                          source_key=source_key,source_text=sentence,
                          source_span={'basis':'normalized_selection','start':start if start>=0 else None,'end':end},
                          numeric_surfaces=re.findall(r'\b\d+(?:[.,]\d+)?\b',sentence),
                          quantity_roles=casualty_roles(sentence),
                          published_at=published_at,reporting_period=reporting_period,scope=scope,
                          predicates=predicates or ['opaque'],
                          certainty='preliminary' if re.search(r'попередньо|може перебувати|уточню',sentence,re.I) else 'asserted',
                          disposition='excluded' if excluded else 'required',
                          reason='complete_non_operational_formula' if excluded else 'source_consequence_or_opaque'))
    return units


def selected_text(text):
    return ' '.join(u['source_text'] for u in select_units(text) if u['disposition']=='required')


def prepare_claims(records):
    """Freeze the selected source clauses before any coverage resolution."""
    from event_brief import tidy,locality
    for r in records:
        if r['section']!='2.1' or not r.get('display'):continue
        value=(r['source_text'] if r.get('reporting_period') else
               r.get('selection_input') or tidy(r['display'],r['published_at']))
        r['claims']=select_units(value,r['source_key'],r['published_at'],r.get('reporting_period'),r.get('scope'))
        place=None
        for u in r['claims']:
            if re.search(r'\bпередміст(?:і|я)\b',u['source_text'],re.I) and place=='Дніпро':
                place='Передмістя Дніпра'
            else:
                place=(None if re.search(r'\bрайонах\b',u['source_text'],re.I)
                       else locality(u['source_text']) or place)
            u['place']=place


def surface_key(text):
    text=canonical(text)
    for pattern,value in [(r'\bзруйнован\w*','зруйн'),(r'\bпошкоджен\w*|\bпошкоджено','пошкодж')]:
        text=re.sub(pattern,value,text)
    return text


def claim_plan(registry, report):
    """Evaluate clause obligations against the actual public document.

    Explicit bounded projection coverage is a proof with target IDs, not a
    bare source-pointer assertion. Unknown clauses must appear in the actual
    document. A lost unfamiliar consequence cannot be certified by record ID.
    """
    from event_brief import tidy,date_label
    result=[];projection=registry.get('public_projection',{})
    by_id={r['id']:r for r in registry.get('records',[])}
    for r in by_id.values():
        for u in r.get('claims',[]):
            item=dict(claim_id=u['id'],record_id=r['id'],source_key=r['source_key'],
                      source_text=u['source_text'],place=u.get('place'),predicates=u['predicates'])
            if u['disposition']=='excluded':
                result.append(dict(item,disposition='excluded',reason=u['reason']));continue
            from casualty_links import link_is_visible
            summary_link=next((link for link in registry.get('casualty_summary_links',[]) if link['record_id']==r['id'] and canonical(link['source_text'])==canonical(u['source_text'])),None)
            if summary_link:
                valid=link_is_visible(summary_link,report)
                result.append(dict(item,disposition='covered' if valid else 'unresolved',
                                   reason=summary_link['reason'] if valid else 'summary_reference_not_supported_in_public_text'))
                continue
            decisions=r.get('claim_decisions',[])+r.get('assessment_history',[])
            own=next((d for d in decisions if canonical(d['source_text'])==canonical(u['source_text'])
                      and d['disposition'] in {'covered','superseded'}),None)
            if own and own.get('target_id') in by_id:
                result.append(dict(item,**{k:v for k,v in own.items() if k!='source_text'}));continue
            if r.get('warehouse_target') in by_id:
                from operational_facts import warehouse_generic_statement
                target=by_id[r['warehouse_target']]
                source=u['source_text'].removeprefix(r.get('detail_label','')+': ').strip()
                if (r['source_key'] in target.get('detail_source_refs',[]) and
                    warehouse_generic_statement(source)):
                    result.append(dict(item,disposition='covered',reason='bounded_warehouse_fire_consolidation',
                                       target_id=target['id']));continue
            proof=next((p for p in projection.get('provenance',[]) if p.get('covered_record_id')==r['id']
                        and (not p.get('covered_sentence') or canonical(p['covered_sentence'])==canonical(u['source_text']))),None)
            if proof:
                result.append(dict(item,disposition='covered',reason=proof['reason'],
                                   target_ids=proof.get('covered_by',[])));continue
            body=report
            if r.get('reporting_period') and (r.get('scope')=='Дніпропетровська область' or
                re.fullmatch(r'Всюди минулося без постраждалих[.!]?',u['source_text'],re.I)):
                at=datetime.fromisoformat(r['reporting_period'])
                marker='за '+date_label(at)+f' (станом на {at:%H:%M}):'
                body=next((p for p in report.split('\n\n') if marker.casefold() in p.casefold()),'')
            overlap=next((p for p in registry.get('clause_projection_proofs',[]) if p['record_id']==r['id'] and canonical(p['source_text'])==canonical(u['source_text'])),None)
            if overlap:
                m=re.search(r'(?m)^'+re.escape(overlap['place'])+r':\n([^\n]+)',report)
                paragraph=m[1] if m else ''
                from operational_prose import concise
                if all(surface_key(concise(tidy(target,r['published_at']))) in surface_key(paragraph) for target in overlap['targets']):
                    result.append(dict(item,disposition='covered',reason=overlap['reason']));continue
            if u.get('place'):
                m=re.search(r'(?m)^'+re.escape(u['place'])+r':\n([^\n]+)',report)
                body=m[1] if m else ''
            text=tidy(u['source_text'],r['published_at'])
            from operational_prose import concise
            visible=any(surface_key(form) in surface_key(body) for form in (text,concise(text if text.endswith(('.', '!', '?')) else text+'.')))
            reason='verbatim_or_morphological_rendering' if visible else None
            if not visible:
                reason=clause_coverage(text,body)
                visible=bool(reason)
            if (not visible and re.fullmatch(r'Всюди минулося без постраждалих[.!]?',text,re.I)
                and 'За цим зведенням, постраждалих немає.' in body):
                visible=True;reason='explicit_no_casualties_in_same_bulletin_period'
            result.append(dict(item,disposition='rendered' if visible else 'unresolved',reason=reason))
    return result


def sentence_coverage(source, target):
    """Exact full-clause coverage, not overlapping damage-object keywords."""
    key=canonical(source)
    return any(key==canonical(s) for s in sentences(clean_lines(target)))


def damage_signature(text):
    """Closed damage vocabulary. Unknown nouns/modifiers make it opaque."""
    from event_brief import damage_atoms
    if re.fullmatch(r'Пошкоджень зазнавав приватний сектор - руйнувань зазнали помешкання людей\.',text,re.I):
        return {'home'}
    m=re.search(r'(?:пошкоджен\w*|пошкоджено|понівечен\w*)\s+(.+?)[.!]?$',text,re.I)
    if not m:return None
    rest=m[1].rstrip('.')
    # These are categories, not arbitrary material matching. Counts, names,
    # degree of damage and any unfamiliar object must remain verbatim.
    for p in [r'об[’ʼ\x27]єкт\w* інфраструктур\w*',r'приватн\w* (?:будин\w*|осел\w*)',
              r'житлов\w* будин\w*',r'багатоквартирн\w* будин\w*',
              r'адміністративн\w* будівл\w*',r'адмінбудівл\w*',r'інфраструктур\w*',
              r'підприємств\w*',r'вантажівк\w*',r'автівк\w*',r'автомобіл\w*']:
        rest=re.sub(p,'',rest,flags=re.I)
    if re.sub(r'\b(?:і|й|та)\b|[,\s]','',rest):return None
    return damage_atoms(text)


def medical_ages(text):
    ages=set(re.findall(r'\b(\d+)-річн',text))
    for match in re.finditer(r'(?:чоловіки|хлопець|дівчина)\s+([\d, іта]+)\s+рок',text,re.I):
        ages.update(re.findall(r'\d+',match[1]))
    return ages


def medical_role_counts(text):
    """Typed clinical quantities; hospitalized is not total injured."""
    from report_rules import NUMBER,number_value
    found={}
    patterns={'hospitalized':r'(?:у|в) лікарні|госпіталізован\w*',
              'severe':r'(?:у|в) (?:важк\w*|тяжк\w*) стан\w*',
              'outpatient':r'(?:на )?амбулаторн\w* (?:лікуван\w*)?'}
    for role,pattern in patterns.items():
        for m in re.finditer(r'\b('+NUMBER+r')\s+(?:(?:люд\w*|поранен\w*|постраждал\w*|осіб)\s+)?(?:перебувають\s+)?(?:'+pattern+r')',text,re.I):
            found[role]=max(found.get(role,0),number_value(m[1].casefold()))
    enumerated={}
    for s in sentences(text):
        n=len(re.findall(r'\b\d+-річн',s))
        for m in re.finditer(r'(?:чоловіки|хлопець|дівчина)\s+([\d, іта]+)\s+рок',s,re.I):
            n+=len(re.findall(r'\d+',m[1]))
        if not n:continue
        for role,pattern in patterns.items():
            if re.search(pattern,s,re.I):enumerated[role]=enumerated.get(role,0)+n
    for role,n in enumerated.items():found[role]=max(found.get(role,0),n)
    return found


def bare_geographic_attack(clause):
    from event_brief import PATTERNS
    m=re.fullmatch(r'(?:\d{1,2} \w+ )?(?:Ворог|росіяни) (?:(?:завдав|завдали) удару по|атакував|атакували) (.+)\.',clause,re.I)
    if not m:return False
    place=re.sub(r'^(?:місто|м\.)\s+','',m[1],flags=re.I)
    return any(re.fullmatch(pattern,place,re.I) for pattern in PATTERNS.values())


def clause_coverage(clause, target):
    """Return a bounded proof of coverage, or None. Never infer event identity."""
    from event_brief import casualty_roles
    from report_rules import NUMBER
    if sentence_coverage(clause,target):return 'equivalent_full_clause'
    absence=r'(?:На щастя, (?:люди|мешканці) не постраждали|Обійшлося без постраждалих)\.'
    if re.fullmatch(absence,clause,re.I) and re.search(r'без постраждалих|не постраждали',target,re.I):
        return 'same_scope_explicit_absence_of_casualties'
    if re.search(r'\bне\s+(?:пошкодж|зруйн)|спростован|помилков',target,re.I):return None
    if re.search(r'вул\.|просп\.|пров\.|№',clause,re.I):return None
    from brief_editor import key,normalize_names
    def communities(text):
        names=set()
        for m in re.finditer(r'([А-ЯІЇЄҐ][а-яіїєґ’\x27]+(?:\s*(?:,|та|і|й)\s*[А-ЯІЇЄҐ][а-яіїєґ’\x27]+)*)\s+громад',normalize_names(text)):
            names.update(key(n) for n in re.findall(r'[А-ЯІЇЄҐ][а-яіїєґ’\x27]+',m[1]))
        return names
    if not communities(clause)<=communities(target):return None
    damage=damage_signature(clause)
    damaged=set().union(*(__import__('event_brief').damage_atoms(s) for s in sentences(target)
                         if re.search(r'пошкодж|понівеч|зруйн',s,re.I)))
    if damage and damage<=damaged:
        # Geography is checked by the caller. Explicit numeric damage is not
        # eligible for category coverage.
        return 'generic_damage_in_daily_scope'
    # Medical clauses have a closed grammatical vocabulary, so a sentence
    # about a child plus an unfamiliar outcome cannot vanish as "casualties".
    words=re.findall(r'[а-яіїєґ’ʼ\x27]+|\d+',clause.casefold())
    allowed=re.compile(r'^(?:\d+|'+NUMBER+r'|люд\w*|людин\w*|осіб|людей|постраждал\w*|'
        r'поранен\w*|поранень|діста\w*|через|атаку|атак\w*|ворож\w*|росіян|'
        r'на|у|в|і|й|та|а|також|ще|вже|до|зросла|кількість|семи|них|серед|'
        r'чоловік\w*|чоловіки|чоловіка|жін\w*|хлопець|хлопці|дівчин\w*|дитин\w*|'
        r'років|роки|річн\w*|лікарні|лікарню|лікарів|ліку\w*|госпіталізован\w*|'
        r'перебува\w*|знаходиться|він|вона|вони|стан\w*|важк\w*|тяжк\w*|середньої|'
        r'медики|оцінюють|як|під|наглядом|амбулаторно|загинул\w*|зараз|'
        r'дніпр\w*|крив\w*|ріг|розі|рогу|нікопол\w*|павлоград\w*)$',re.I)
    # Named communities are not a generic patient group. The exact age
    # enumeration is already covered by full-clause equality above.
    if words and all(allowed.fullmatch(w) for w in words) and re.search(r'поран|постраждал|лікарні|загин|госпітал|хлопець|дитин',clause,re.I):
        if not medical_ages(clause)<=medical_ages(target):return None
        clinical=medical_role_counts(clause)
        final_clinical=medical_role_counts(target)
        if any(n>final_clinical.get(role,0) for role,n in clinical.items()):return None
        for degree in ('вкрай','важкому','тяжкому','середньої тяжкості'):
            if degree in clause.casefold() and degree not in target.casefold():return None
        roles=casualty_roles(clause) or {}
        final=casualty_roles(target) or {}
        if 'dead' in roles and roles['dead']!=final.get('dead'):return None
        if 'injured' in roles and final.get('injured',0)<roles['injured']:
            # A detailed day's patient enumeration replaces a preliminary
            # count without creating or publishing an inferred new total.
            if not re.search(r'госпіталізован|лікарні',target,re.I) or len(medical_ages(target))<2:return None
        if not roles and not re.search(r'поран|постраждал|лікарні',target,re.I):return None
        return 'earlier_medical_update_in_daily_scope'
    # A bare attack announcement adds no object, weapon, clock or quantity
    # to a later daily local attack block. Unknown detail cannot match this.
    if bare_geographic_attack(clause):
        return 'bare_attack_in_daily_local_scope'
    return None


def resolve_updates(records):
    """Resolve only dated daily scope coverage; retain every unknown clause.

    Not a same-incident merge: explicit clocks/repeated attacks are excluded
    from this reduction. Every removed sentence records its target and rule.
    """
    from event_brief import (split_places,tidy,recap_coverage,city_daily_details,
                             city_episode,rescue_supplement,shared_rescue_effect)
    daily=[r for r in records if r.get('reporting_period') and
           datetime.fromisoformat(r['reporting_period']).hour>=12 and
           r.get('display') and r['state'] not in {'mirror','excluded','review'}]
    # Existing bounded episode resolvers own their input until projection.
    # Do not partly rewrite that input and then ask a second resolver to
    # recognise a different text. Unknown trailing clauses remain available.
    legacy_covered,_,_=recap_coverage(records)
    details=city_daily_details(records,legacy_covered)
    protected={i for d in details.values() for i in d['source_ids']}
    episode=city_episode(records)
    if episode:protected.update(episode['refs'])
    for r in records:
        if r.get('display') and (rescue_supplement(r,daily,episode) or shared_rescue_effect(r,records)):
            protected.add(r['id'])
    protected.update(i for i in legacy_covered if not i.endswith(':sentences'))
    verified_recap_keys={r['source_key'] for r in records if r['id'] in legacy_covered and
                        clean_lines(r['source_text']).lstrip('# ').startswith('Дніпропетровщина')}
    resolve_initial_assessments(records,daily,details)
    for r in records:
        if (r['section']!='2.1' or r.get('reporting_period') or not r.get('display') or
            r['state'] not in {'included'} or r.get('warehouse_target') or r['id'] in protected):continue
        original=clean_lines(r['source_text'])
        if re.search(r'\b(?:о|близько|після|до)\s+\d{1,2}[:.]\d{2}|знову|повторн|ще одн\w* атак',original,re.I):continue
        published=datetime.fromisoformat(r['published_at']).astimezone(ZoneInfo('Europe/Kyiv'))
        recap=(r['source_key'].split('/')[0].casefold() in {'gunpvdp','dsns_telegram'} and
               (r['source_key'] in verified_recap_keys or
                bool(re.search(r'документують наслідки|протягом дня|наслідки ворожих атак',original,re.I))))
        targets=[b for b in daily if datetime.fromisoformat(b['reporting_period']).date()==published.date()
                 and (datetime.fromisoformat(b['reporting_period'])>=published or recap)]
        if not targets:continue
        original_parts=split_places(original)
        initial=original_parts[0][0] if original_parts else None
        chunks=[];decisions=[]
        for place,body in split_places(tidy(r['display'],r['published_at'])):
            place=place or initial
            target_parts=[(b,p,t) for b in targets for p,t in split_places(b['source_text']) if place and p==place]
            kept=[]
            for clause in sentences(body):
                target=None;reason=None
                for b,_,target_text in target_parts:
                    reason=clause_coverage(clause,target_text)
                    if reason:target=b;break
                if not target and episode and place=='Дніпро' and published.date()==episode['day']:
                    # Generic damage/absence already stated in the detailed
                    # dated city account; no clinical totals or incident
                    # identity are inferred from this category coverage.
                    if damage_signature(clause) or bare_geographic_attack(clause) or re.fullmatch(r'На щастя, (?:люди|мешканці) не постраждали\.',clause,re.I):
                        reason=clause_coverage(clause,episode['text'])
                        if reason:target=next(b for b in records if b['id']==episode['anchor'])
                if target:
                    decisions.append({'source_text':clause,'disposition':'covered','target_id':target['id'],
                                      'place':place,'reason':reason})
                else:
                    kept.append(clause)
                    decisions.append({'source_text':clause,'disposition':'rendered','place':place,
                                      'reason':'uncovered_source_clause'})
            if kept:chunks.append((place,' '.join(kept)))
        r['claim_decisions']=decisions
        if chunks:
            r['resolved_chunks']=chunks
            r['display']=' '.join(t for _,t in chunks)
        else:
            r['state']='supplement';r['reason']='all_source_clauses_covered_by_dated_daily_scope';r['display']=None


def resolve_initial_assessments(records,daily,details):
    """Archive provisional assessments when a bounded final account exists.

    Not a casualty sum or proof of a person's identity. A possible person
    under rubble is unconfirmed; retain it when multiple buildings or an
    explicit street/time prevent the unique-building account below.
    """
    from event_brief import locality,split_places,tidy,casualty_roles
    for r in records:
        if r.get('reporting_period') or not r.get('display'):continue
        text=tidy(r['display'],r['published_at']);place=locality(text)
        if not place or re.search(r'вул\.|просп\.|\bо \d{1,2}:\d{2}|знову|повторн',text,re.I):continue
        at=datetime.fromisoformat(r['published_at'])
        target=next((b for b in daily if datetime.fromisoformat(b['reporting_period']).date()==at.astimezone(ZoneInfo('Europe/Kyiv')).date()
                     and datetime.fromisoformat(b['reporting_period'])>at
                     and any(p==place for p,_ in split_places(b['source_text']))),None)
        if target is None:continue
        final=' '.join(t for p,t in split_places(target['source_text']) if p==place)
        remove=[]
        for s in sentences(text):
            if re.fullmatch(r'Попередньо, (?:люди не постраждали|загиблих і поранених немає)\.',s) and casualty_roles(final):
                remove.append((s,'provisional_absence_replaced_by_daily_assessment'))
            if (re.fullmatch(r'Під його завалами може перебувати людина\.',s) and
                details.get(target['id'],{}).get('recovery')):
                houses=[a for a in records if a.get('display') and not a.get('reporting_period')
                        and locality(a['source_text'])==place and
                        datetime.fromisoformat(a['published_at']).date()==at.date() and
                        re.search(r'Зруйнований приватний будинок\.',a['source_text'])]
                if len(houses)==1 and houses[0]['id']==r['id']:
                    remove.append((s,'unconfirmed_rubble_assessment_replaced_by_unique_building_recovery'))
        for sentence,reason in remove:
            r['display']=r['display'].replace(sentence,'').strip()
            r.setdefault('assessment_history',[]).append(dict(source_text=sentence,
                disposition='superseded',target_id=target['id'],reason=reason))
