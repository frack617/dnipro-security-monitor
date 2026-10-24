"""Public geographic facts with provenance, separate from source audit prose.

A matching date or number alone never establishes incident identity. Only the
bounded district + damage match below consolidates a detailed city episode.
Regional bulletins remain separate reporting scopes; their counts are not added.
"""
import re
from datetime import datetime
from zoneinfo import ZoneInfo
from fallback_report import sentences, clean_lines
from report_rules import MONTHS, PLACE_PATTERNS, NUMBER, number_value

KYIV = ZoneInfo('Europe/Kyiv')
PATTERNS = dict(PLACE_PATTERNS, **{
    'Кам’янський район': r'кам[’\x27]янськ\w*\s+район\w*',
    'Синельниківський район': r'синельниківськ\w*\s+район\w*|синельниківщин\w*',
})


def locality(text):
    names = [name for name,p in PATTERNS.items() if re.search(p,text,re.I)]
    if set(names)=={'Нікопольщина','Нікополь'}:
        return 'Нікопольщина'
    if names == ['Дніпро'] and re.search('передміст',text,re.I):
        return 'Передмістя Дніпра'
    return names[0] if len(names)==1 else None


def date_label(day):
    return f'{day.day} {MONTHS[day.month-1]}'


def tidy(text, published=None):
    text = re.sub(r'^Повідомлення від \d{2}:\d{2} \d{2}\.\d{2}:\s*|^Повідомлення від \d{2}\.\d{2} \d{2}:\d{2}:\s*','',text)
    text = re.sub(r'\b(області)\s+\1\b',r'\1',text,flags=re.I)
    if published:
        day = datetime.fromisoformat(published).astimezone(KYIV).date()
        text = re.sub(r'сьогоднішньої атаки', 'атаки '+date_label(day),text,flags=re.I)
        text = re.sub(r'\bсьогодні\b',date_label(day),text,flags=re.I)
    text=re.sub(r'\bЩойно\s+', '',text)
    text=re.sub(r'\bзараз\s+', '',text)
    text=re.sub(r'\.\.(?=\s|$)', '.',text)
    text=text.strip()
    return text[:1].upper()+text[1:]


def split_places(text):
    chunks=[]
    for sentence in sentences(text):
        multiple=bool(re.search(r'\bрайонах\b',sentence,re.I))
        place=None if multiple else locality(sentence)
        if re.search(r'\bпередміст(?:і|я)\b',sentence,re.I) and chunks and chunks[-1][0]=='Дніпро':
            place='Передмістя Дніпра'
        if multiple:
            chunks.append([None,sentence])
        elif place and (not chunks or chunks[-1][0]!=place):
            chunks.append([place,sentence])
        elif chunks:
            chunks[-1][1]+=' '+sentence
        else:
            chunks.append([None,sentence])
    return chunks


def city_episode(records):
    """One explicitly dated district episode plus compatible source updates.

    The detailed city statement identifies date, district and private-house
    count. Another post joins only with that same district AND count, without
    a second event marker. Coarse city totals are covered only as daily claims,
    not declared independent evidence or an identified incident.
    """
    anchors=[]
    for r in records:
        if r['source_key'].split('/')[0].casefold()!='dniprocityofficial':
            continue
        body=tidy(r['display'],r['published_at'])
        date=re.search(r'Удень (\d{1,2}) ('+'|'.join(MONTHS)+r') ([А-ЯІЇЄҐ][а-яіїєґ’\x27-]+) район Дніпра',body)
        houses=re.search(r'пошкоджено (\d+) приватних будинків',body)
        if date and houses:
            day=datetime.fromisoformat(r['published_at']).astimezone(KYIV).date()
            if (int(date[1]),date[2])==(day.day,MONTHS[day.month-1]):
                anchors.append((r,body,day,date[3],houses[1]))
    if len(anchors)!=1:
        return None
    anchor,body,day,district,count=anchors[0]
    same_day=[r for r in records if not r.get('reporting_period') and
              datetime.fromisoformat(r['published_at']).astimezone(KYIV).date()==day and
              locality(r['source_text'])=='Дніпро']
    # An explicit different attack/time/district must survive independently.
    other=re.compile(r'ще одн\w* атак|повторн\w* атак|інш\w* атак|вночі|на світанку|вранці',re.I)
    if any(other.search(r['source_text']) for r in same_day):
        return None
    refs=[anchor['id']];extra=[]
    for r in same_day:
        if r is anchor:
            continue
        raw=r['source_text']
        allowed = [
            r'Загалом '+count+r' приватних будинків постраждали внаслідок сьогоднішньої атаки рф на Дніпро\.',
            r'Одна оселя вигоріла вщент\.',
            r'У решті потрощено кілька десятків вікон та '+NUMBER+r' покрівл[іья]\.',
            r'Проте, на щастя, всі живі\.',
            r'На місці працюють зокрема міські служби та благодійники\.',
            r'Із заявками на державне «єВідновлення» людям допомагають працівники адміністрації '+district[:6]+r'\w* району\.',
        ]
        recognized=all(any(re.fullmatch(p,sentence) for p in allowed)
                       for sentence in sentences(clean_lines(raw)))
        source_roofs=re.search('('+NUMBER+r') покрівл',raw,re.I)
        anchor_roofs=re.search('('+NUMBER+r') покрівл',body,re.I)
        windows=re.search(r'більше ніж (\d+) вікон',body)
        compatible=(source_roofs and anchor_roofs and
                    number_value(source_roofs[1].lower())==number_value(anchor_roofs[1].lower()) and
                    windows and 0<int(windows[1])<100)
        if (recognized and compatible and district[:6].casefold() in raw.casefold() and
                re.search(r'\b'+count+r' приватних будинків',raw)):
            # The bounded update also contains an additional material claim
            # which the old source-sentence extractor missed.
            extra += re.findall(r'Одна оселя вигоріла вщент\.',raw)
            refs.append(r['id'])
    return {'anchor':anchor['id'],'text':body,'day':day,'count':count,
            'refs':refs,'extra':list(dict.fromkeys(extra))}


def rescue_supplement(record, bulletin_records, city):
    """Recognize a fully covered DSNS regional recap, keeping its unique facts.

    Refuse the reduction if the recap has an unrecognized sentence or any
    unmatched damage/casualty/attack scope. Source text always remains intact.
    """
    if record['source_key'].split('/')[0].casefold()!='dsns_telegram':
        return None
    raw=tidy(record['display'],record['published_at'])
    pattern=(r'Дніпропетровщина: внаслідок російських атак загинула людина, ще одна постраждала '
      r'Протягом дня ворог понад (\d+) разів атакував ([\w’\x27]+) районів області\. '
      r'На Нікопольщині загинула людина, ще одну поранено\. '
      r'Пошкоджені житлові будинки, адміністративна будівля, спортивна школа, інфраструктура й автомобілі\. '
      r'У Дніпрі виникла пожежа на території приватного домоволодіння\. Пошкоджені житлові будинки\. '
      r'Також внаслідок атак виникли пожежі (у .+?)\. Рятувальники ліквідували всі пожежі\.')
    m=re.fullmatch(pattern,raw)
    if not m or not city:
        return None
    day=datetime.fromisoformat(record['published_at']).astimezone(KYIV).date()
    if day!=city['day']:
        return None
    same=[r for r in bulletin_records if datetime.fromisoformat(r['reporting_period']).date()==day]
    header=next((r for r in same if r['scope']=='Дніпропетровська область'),None)
    nik=next((r for r in same if locality(r['source_text'])=='Нікопольщина'),None)
    if not header or not nik:
        return None
    if not re.search(r'Понад '+m[1]+r' разів ворог атакував '+m[2]+r' районів',header['source_text']):
        return None
    if not all(s in header['source_text'] for s in ('Одна людина загинула','ще одна дістала поранень')):
        return None
    if not all(s in nik['source_text'] for s in ('Загинула одна людина','багатоквартирний і приватні будинки',
          'адміністративна будівля','спортивна школа','інфраструктура','автівки')):
        return None
    if not re.search(r'У важкому стані до лікарні доправили \d+-річного чоловіка\.',nik['source_text']):
        return None
    return {'text':'Пожежі '+m[3]+'. Рятувальники ліквідували всі пожежі.',
            'day':day,'nikopol_id':nik['id'],'covered_by':[header['id'],nik['id'],city['anchor']]}


def project_attacks(registry):
    records=[r for r in registry.get('records',[]) if r['section']=='2.1' and r.get('display') and
             r['state'] not in {'mirror','excluded','review'}]
    records.sort(key=lambda r: datetime.fromisoformat(r.get('reporting_period') or r['published_at']))
    covered,upgrades,conflicts=recap_coverage(records)
    daily_details=city_daily_details(records,covered)
    city=city_episode(records)
    # Resolve compatible update coverage before rendering, so a later post
    # cannot lose its extinguishing status merely because its anchor was read first.
    if city:
        for r in records:
            if r.get('reporting_period') or locality(r['source_text'])!='Дніпро':
                continue
            day=datetime.fromisoformat(r['published_at']).astimezone(KYIV).date()
            raw=tidy(r['display'],r['published_at'])
            coarse=re.fullmatch(r'Наслідки атаки росіян на Дніпро\. Рятувальники вже загасили пожежу у приватному будинку\. Пошкоджені понад (\d+) осель\.(?: На щастя, люди не постраждали\.)?',raw)
            if day==city['day'] and coarse and int(coarse[1])<int(city['count']):
                city['extra'].append('Пожежу у приватному будинку ліквідовано.')
                city['refs'].append(r['id'])
        city['extra']=list(dict.fromkeys(city['extra']))
    bulletins=[r for r in records if r.get('reporting_period')]
    recaps={r['id']:rescue_supplement(r,bulletins,city) for r in records if not r.get('reporting_period')}
    groups={};headers=[];mapping=[]
    def add(place,period,text,refs):
        if not text.strip():return
        slot=groups.setdefault(place or 'Інші підтверджені наслідки',{})
        values=slot.setdefault(period,[])
        if text not in values:values.append(text)
        mapping.append({'text':text,'record_ids':refs,'reporting_period':period,'place':place})
    for r in records:
        at=r.get('reporting_period')
        raw=tidy(r['display'],r['published_at'])
        source_place=None if re.search(r'\bрайонах\b',raw,re.I) else locality(raw)
        if r['id'] in covered:
            mapping.append({'covered_record_id':r['id'],'covered_by':covered[r['id']],
                            'reason':'same_day_same_locality_daily_claims_covered'})
            continue
        for sentence,target_id in covered.get(r['id']+':sentences',[]):
            raw=raw.replace(sentence,'').strip()
            mapping.append({'covered_record_id':r['id'],'covered_by':[target_id],
                            'covered_sentence':sentence,'reason':'earlier_city_claim_inside_daily_city_scope'})
        if r['id'] in upgrades:
            old,new=upgrades[r['id']]
            raw=raw.replace(old,new)
        if r['id'] in daily_details:
            raw=add_city_details(raw,daily_details[r['id']])
        if at and r['scope']=='Дніпропетровська область':
            dt=datetime.fromisoformat(at)
            label=('Денне зведення' if dt.hour>=12 else 'Ранкове зведення')
            text=f'{label} за {date_label(dt)} (станом на {dt:%H:%M}): '+tidy(r['source_text']).rstrip('.')+'.'
            headers.append(text)
            mapping.append({'text':text,'record_ids':[r['id']],'reporting_period':at,'place':'Область'})
            continue
        if re.fullmatch(r'Всюди минулося без постраждалих[.!]?',r['source_text'],re.I):
            if headers:
                headers[-1]+=' За цим зведенням, постраждалих немає.'
                header=next(p for p in mapping if p.get('place')=='Область' and p['reporting_period']==at)
                header['text']=headers[-1]
                header['record_ids'].append(r['id'])
            continue
        if city and r['id'] in city['refs']:
            if r['id']==city['anchor']:
                # Concrete event date is already in the source sentence.
                add('Дніпро',None,city['text']+' '+ ' '.join(city['extra']),city['refs'])
            else:
                mapping.append({'covered_record_id':r['id'],'covered_by':[city['anchor']],
                                'reason':'bounded_district_house_count_and_compatible_update'})
            continue
        shared=shared_rescue_effect(r,records)
        if shared:
            add(shared['place'],None,shared['text'],[r['id']])
            mapping.append({'covered_record_id':r['id'],'covered_by':shared['covered_by'],
                            'reason':'community_attacks_covered_joint_infrastructure_and_fire_status_retained'})
            continue
        rescue=recaps.get(r['id'])
        if rescue:
            add('Інші наслідки атак',None,date_label(rescue['day'])+': '+rescue['text'],[r['id']])
            mapping.append({'covered_record_id':r['id'],'covered_by':rescue['covered_by'],
                            'reason':'bounded_regional_recap_claims_covered_unique_fire_facts_retained'})
            continue
        chunks=split_places(raw)
        if chunks and chunks[0][0] is None and r.get('resolved_chunks'):
            chunks[0][0]=r['resolved_chunks'][0][0]
        for place,body in chunks:
            if not place and source_place=='Дніпро' and re.search(r'\bпередміст(?:і|я)\b',body):
                place='Передмістя Дніпра'
            place=place or source_place
            if place=='Передмістя Дніпра' and not at:
                preliminary=re.fullmatch(r'Кількість поранених через атаку росіян на передмістя зросла до (\d+)\. Усі поранені у лікарні\. (\d+-річний чоловік у вкрай тяжкому стані\.)',body)
                published=datetime.fromisoformat(r['published_at']).astimezone(KYIV)
                later=next((b for b in bulletins if b['scope']=='Дніпропетровська область'
                     and datetime.fromisoformat(b['reporting_period']).date()==published.date()
                     and datetime.fromisoformat(b['reporting_period'])>published),None)
                if preliminary and later:
                    # Do not present an intermediate count as an additional
                    # incident total or transfer a later city total to suburbs.
                    # Its unique clinical fact and its own geography survive.
                    body='Серед госпіталізованих — '+preliminary[2]
                    mapping.append({'covered_record_id':r['id'],'covered_by':[later['id']],
                        'reason':'intermediate_count_archived_not_an_additional_daily_total',
                        'archived_intermediate_count':int(preliminary[1])})
            if city and at and datetime.fromisoformat(at).date()==city['day'] and place=='Дніпро' and body=='У Дніпрі пошкоджені приватні будинки.':
                mapping.append({'covered_record_id':r['id'],'covered_by':[city['anchor']],
                                'reason':'generic_daily_city_damage_in_detailed_episode'})
                continue
            if any(x and x['nikopol_id']==r['id'] for x in recaps.values()):
                body=body.replace('Є поранені.','Одну людину поранено.')
            # Relative wording is normalized to the source's own calendar day;
            # a publication clock never becomes an asserted attack clock.
            refs=[r['id']]
            if place=='Дніпро' and r['id'] in daily_details:
                refs+=daily_details[r['id']]['source_ids']
            add(place,at,body,refs)
    result=list(headers)
    for place,periods in groups.items():
        pieces=[]
        for period,values in periods.items():
            body=' '.join(values)
            if period:
                day=datetime.fromisoformat(period)
                label=('За '+date_label(day) if day.hour>=12 else 'За ранковими даними '+date_label(day))
                body=label+': '+body
            pieces.append(body)
        result.append(place+':\n'+' '.join(pieces))
    return {'paragraphs':result or registry['sections']['2.1'],'provenance':mapping,'conflicts':conflicts}


def casualty_roles(text):
    """Keep fatal and injury roles separate; never compare an unordered set."""
    person=r'(?:людин\w*|людей|осіб)'
    result={}
    for name,verb in [('dead',r'загину\w*'),('injured',r'(?:поранен\w*|поранено|постраждал\w*|травмовано)')]:
        hits=list(re.finditer(r'\b('+NUMBER+r')\s+(?:'+person+r'\s+)?'+verb,text,re.I))
        hits+=list(re.finditer(r'\b'+verb+r'\s+('+NUMBER+r')\s+'+person,text,re.I))
        values={number_value(m[1].casefold()) for m in hits}
        if len(values)==1:
            result[name]=next(iter(values))
        elif len(values)>1:
            return None
    injuries=re.findall(r'\b('+NUMBER+r')\s+(?:(?:люд\w*|осіб)\s+)?(?:дістал\w*|отримал\w*|зазнал\w*)\s+поран\w*',text,re.I)
    values={number_value(v.casefold()) for v in injuries}
    if values:
        if len(values)>1 or ('injured' in result and result['injured'] not in values):
            return None
        result['injured']=next(iter(values))
    if 'dead' not in result and re.search(r'загинула людина',text,re.I):
        result['dead']=1
    return result


def damage_atoms(text):
    patterns={'home':r'приватн\w* (?:будин|осел)|житлов\w* будин',
              'infrastructure':r'інфраструктур','enterprise':r'підприємств',
              'cars':r'автів|автомобіл','trucks':r'вантажів',
              'admin':r'адмін(?:істративн\w*\s+)?будів|адміністративн\w* будів',
              'school':r'школ','church':r'церк|храм','hospital':r'лікарн|амбулатор',
              'warehouse':r'склад','fire':r'пожеж|горів|вигор',
              'apartment':r'багатоквартир|багатоповерх'}
    return {name for name,p in patterns.items() if re.search(p,text,re.I)}


def recap_coverage(records):
    """Covered daily source claims, not inferred identities of separate attacks.

    A precise same-day OVA locality and separate death/injury roles are
    required. Only enumerated sentence forms are eligible; unknown facts stay.
    """
    covered={};upgrades={};conflicts=[]
    backbone=[r for r in records if r.get('reporting_period') and datetime.fromisoformat(r['reporting_period']).hour>=12]
    for r in records:
        if r.get('reporting_period') or r['source_key'].split('/')[0].casefold()!='dsns_telegram':
            continue
        body=tidy(r['display'],r['published_at'])
        day=datetime.fromisoformat(r['published_at']).astimezone(KYIV).date()
        same=[b for b in backbone if datetime.fromisoformat(b['reporting_period']).date()==day]
        roles=casualty_roles(body)
        header=re.fullmatch(r'Дніпропетровщина:\s*'+NUMBER+r'\s+(?:людин\w*|людей|осіб)\s+загину\w*,\s*ще\s+'+NUMBER+r'\s+постраждал[аи] внаслідок російських атак[.!]?',body,re.I)
        if header and roles:
            match=next((b for b in same if b['scope']=='Дніпропетровська область' and casualty_roles(b['source_text'])==roles),None)
            if match:
                covered[r['id']]=[match['id']]
            elif same:
                conflicts.append({'reason':'source_conflict','sources':[r['source_key']],'detail':'regional_recap_casualty_roles_differ'})
            continue
        place=locality(body)
        targets=[b for b in same if place and any(p==place for p,_ in split_places(tidy(b['display'])))]
        for b in targets:
            parts=[t for p,t in split_places(tidy(b['display'])) if p==place]
            if len(parts)!=1:
                continue
            target=parts[0]
            # Plain local casualty summary plus a damage list; no new numeric
            # property counts, clocks, communities or unfamiliar clauses.
            simple=re.fullmatch(r'(?:У|На) [^.]+? загинула людина, ще '+NUMBER+r' постраждали\. Пошкоджено [^.]+\.',body)
            if simple and roles and roles!=casualty_roles(target):
                conflicts.append({'reason':'source_conflict','sources':[r['source_key'],b['source_key']],'detail':'local_recap_casualty_roles_differ'})
            if simple and roles==casualty_roles(target) and damage_atoms(body)<=damage_atoms(target):
                # Don't suppress a previously unseen named object hidden in
                # a list; accept only this vocabulary of source objects.
                damage=body.split('Пошкоджено ',1)[1].rstrip('.')
                known=re.fullmatch(r'(?:приватні будинки|підприємства|об’єкти інфраструктури)(?:, (?:приватні будинки|підприємства|об’єкти інфраструктури))*(?: та (?:приватні будинки|підприємства|об’єкти інфраструктури))?',damage)
                if known:
                    covered[r['id']]=[b['id']]
                    match=re.search(r'\b('+NUMBER+r') поранених у лікарні\.',target,re.I)
                    if match:
                        upgrades[b['id']]=(match[0],match[1]+' людей поранено, вони перебувають у лікарні.')
                    break
            # An explicit three-person statement can be represented by an
            # exact three-person source enumeration in the SAME community.
            community=re.fullmatch(r'У (\w+) громаді Дніпровського району травмовано ('+NUMBER+r') людей\.',body)
            enumeration=re.search(r'У (\w+) громаді Дніпровського району постраждали чоловіки \d+ і \d+ років, а також \d+-річна жінка\.',target)
            if community and enumeration:
                canon=lambda word: re.sub(r'підгородн(?:ен|ян)', 'підгородн',word.casefold())
                if canon(community[1])==canon(enumeration[1]):
                    if number_value(community[2].casefold())==3:
                        covered[r['id']]=[b['id']]
                    else:
                        conflicts.append({'reason':'source_conflict','sources':[r['source_key'],b['source_key']],'detail':'community_count_differs_from_explicit_people'})
                    break
    # Earlier city-only counts are already included in a later daily city
    # total. This is daily scope coverage, not a claim of incident identity.
    for r in records:
        if r.get('reporting_period'):
            continue
        body=tidy(r['display'],r['published_at'])
        day=datetime.fromisoformat(r['published_at']).astimezone(KYIV).date()
        for sentence in sentences(body):
            if not re.fullmatch(r'(?:Ворог завдав удару по Дніпру|'+NUMBER+r' людей дістали поранень через атаку (?:росіян на Дніпро|на Дніпровський район))\.',sentence,re.I):
                continue
            for b in backbone:
                at=datetime.fromisoformat(b['reporting_period'])
                if at.date()!=day or at<=datetime.fromisoformat(r['published_at']):
                    continue
                place=locality(sentence)
                city=[t for p,t in split_places(tidy(b['display'])) if p==place]
                if len(city)!=1:
                    continue
                roles=casualty_roles(sentence)
                final=casualty_roles(city[0])
                # An explicit DSNS same-day regional recap may supply the
                # three-person count represented by the OVA age enumeration.
                # Require that recap's regional header to match this OVA slot.
                explicit=[]
                if not final or 'injured' not in final:
                    for d in records:
                        if d['id'] not in covered or b['id'] not in covered[d['id']]:
                            continue
                        if locality(d['source_text'])!=place:
                            continue
                        own=casualty_roles(d['source_text'])
                        if own and 'injured' in own:
                            explicit.append(own['injured'])
                    matching_header=any(d['id'] in covered and d['source_key'].split('/')[0].casefold()=='dsns_telegram'
                         and d['source_text'].lstrip('#\n ').startswith('Дніпропетровщина')
                         and datetime.fromisoformat(d['published_at']).astimezone(KYIV).date()==day for d in records)
                    if matching_header and len(set(explicit))==1:
                        final=dict(final or {},injured=explicit[0])
                if roles and (not final or roles.get('injured',0)>final.get('injured',0)):
                    continue
                covered.setdefault(r['id']+':sentences',[]).append((sentence,b['id']))
                break
    return covered,upgrades,conflicts


def city_daily_details(records, covered):
    """Fold recognized unique city details into the dated daily city block.

    Counts remain the daily city total, not a total for one destroyed house.
    Only source sentences before that bulletin can be covered by its day.
    Unknown consequences, different places and later attacks remain separate.
    """
    additions={}
    for b in records:
        if not b.get('reporting_period') or datetime.fromisoformat(b['reporting_period']).hour<12:
            continue
        parts=[text for place,text in split_places(tidy(b['display'])) if place=='Дніпро']
        if len(parts)!=1:
            continue
        at=datetime.fromisoformat(b['reporting_period'])
        facts=[];recovery=False;sources=[]
        for r in records:
            if r.get('reporting_period'):
                continue
            published=datetime.fromisoformat(r['published_at']).astimezone(KYIV)
            if published.date()!=at.date() or published>at:
                continue
            raw=tidy(r['display'],r['published_at'])
            for place,body in split_places(raw):
                if place!='Дніпро':
                    continue
                for sentence in sentences(body):
                    material=re.fullmatch(r'Зруйнований приватний будинок\.|Пошкоджені щонайменше \d+ приватних осель\.|Зайнялася пожежа\.|Ворог атакував критичну інфраструктуру Дніпра\.',sentence)
                    found_body=re.fullmatch(r'З-під завалів зруйнованого будинку у Дніпрі рятувальники дістали тіло загиблої людини\.',sentence)
                    if material:
                        facts.append(sentence)
                    elif found_body and casualty_roles(parts[0]).get('dead')==1:
                        recovery=True
                    else:
                        continue
                    covered.setdefault(r['id']+':sentences',[]).append((sentence,b['id']))
                    sources.append(r['id'])
        if facts or recovery:
            additions[b['id']]={'facts':list(dict.fromkeys(facts)),'recovery':recovery,'source_ids':list(dict.fromkeys(sources))}
    return additions


def add_city_details(text, details):
    # Operate on the explicit city paragraph only, even when its source block
    # also contains a Dniprovskyi district paragraph.
    result=[]
    for place,body in split_places(text):
        if place=='Дніпро':
            facts=details['facts']
            if any(s.startswith('Пошкоджені щонайменше') for s in facts):
                body=body.replace(', приватні оселі','')
            if details['recovery']:
                body=body.replace('Одна людина загинула.', 'Загинула одна людина, її тіло дістали з-під завалів будинку.')
            body+=' '+' '.join(facts)
        result.append(body)
    return ' '.join(result)


def shared_rescue_effect(record, records):
    """Keep a joint two-district effect without repeating covered attacks.

    Communities must already be present in their OWN district's daily block.
    The infrastructure statement remains joint; it is not allocated to a city.
    """
    if record.get('reporting_period') or record['source_key'].split('/')[0].casefold()!='dsns_telegram':
        return None
    raw=tidy(record['display'],record['published_at'])
    m=re.fullmatch(r'На Криворіжжі під ударом опинилися ([^.]+) громади, у Синельниківському районі — ([^.]+) громада\. Пошкоджено об’єкти інфраструктури\. Рятувальники ліквідували пожежі, що виникли внаслідок атак\.',raw)
    if not m:
        return None
    day=datetime.fromisoformat(record['published_at']).astimezone(KYIV).date()
    refs=[]
    community_stems=lambda text:set(re.findall(r'\b([а-яіїєґ’\x27]+?)(?:ській|ська|ської|ську)\b',text.casefold()))
    for part,place in [(m[1],'Криворіжжя'),(m[2],'Синельниківський район')]:
        wanted=community_stems(part)
        target=next((r for r in records if r.get('reporting_period') and
             datetime.fromisoformat(r['reporting_period']).date()==day and
             locality(r['source_text'])==place and wanted and wanted<=community_stems(r['source_text'])),None)
        if not target:
            return None
        refs.append(target['id'])
    return {'text':'ДСНС також повідомила про пошкодження об’єктів інфраструктури та ліквідацію пожеж.',
            'place':'Криворіжжя та Синельниківський район','covered_by':refs}
