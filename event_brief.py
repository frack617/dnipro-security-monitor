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
    return text.strip()


def split_places(text):
    chunks=[]
    for sentence in sentences(text):
        multiple=bool(re.search(r'\bрайонах\b',sentence,re.I))
        place=None if multiple else locality(sentence)
        if re.search(r'^У передмісті\b',sentence,re.I) and chunks and chunks[-1][0]=='Дніпро':
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
    city=city_episode(records)
    # Resolve compatible update coverage before rendering, so a later post
    # cannot lose its extinguishing status merely because its anchor was read first.
    if city:
        for r in records:
            if r.get('reporting_period') or locality(r['source_text'])!='Дніпро':
                continue
            day=datetime.fromisoformat(r['published_at']).astimezone(KYIV).date()
            raw=tidy(r['display'],r['published_at'])
            coarse=re.fullmatch(r'Наслідки атаки росіян на Дніпро\. Рятувальники вже загасили пожежу у приватному будинку\. Пошкоджені понад (\d+) осель\.',raw)
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
            continue
        rescue=recaps.get(r['id'])
        if rescue:
            add('Інші наслідки атак',None,date_label(rescue['day'])+': '+rescue['text'],[r['id']])
            mapping.append({'covered_record_id':r['id'],'covered_by':rescue['covered_by'],
                            'reason':'bounded_regional_recap_claims_covered_unique_fire_facts_retained'})
            continue
        for place,body in split_places(raw):
            if city and at and datetime.fromisoformat(at).date()==city['day'] and place=='Дніпро' and body=='У Дніпрі пошкоджені приватні будинки.':
                mapping.append({'covered_record_id':r['id'],'covered_by':[city['anchor']],
                                'reason':'generic_daily_city_damage_in_detailed_episode'})
                continue
            if any(x and x['nikopol_id']==r['id'] for x in recaps.values()):
                body=body.replace('Є поранені.','Одну людину поранено.')
            # Relative wording is normalized to the source's own calendar day;
            # a publication clock never becomes an asserted attack clock.
            add(place,at,body,[r['id']])
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
    return {'paragraphs':result or registry['sections']['2.1'],'provenance':mapping}
