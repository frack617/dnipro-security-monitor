"""Deterministic presentation of source facts; no generative rewriting.

Geography is checked against a dated reference snapshot. Known spelling
corrections affect publication only; original source strings remain auditable.
"""
import json
import re
from pathlib import Path
from datetime import datetime

CATALOG=json.loads((Path(__file__).parent/'reference/communities_dp.json').read_text())
ALIASES={'Підгороднянська':'Підгородненська','Підгороднянській':'Підгородненській',
         'Підгороднянської':'Підгородненської','Підгороднянську':'Підгородненську',
         'Підгороднянською':'Підгородненською'}
REGION_ALIASES={'Нкопольщину':'Нікопольщину'}
PARENTS={'Дніпро':'Дніпровський район','Передмістя Дніпра':'Дніпровський район',
         'Кривий Ріг':'Криворізький район','Криворіжжя':'Криворізький район',
         'Нікополь':'Нікопольський район','Нікопольщина':'Нікопольський район',
         'Павлоград':'Павлоградський район'}


def key(name):
    name=name.casefold().replace("'",'’').replace('ʼ','’')
    return re.sub(r'(?:ськ|цьк)(?:а|ій|ої|у|ою|их|им|ими|ий|ому|ого)$','',name)


def normalize_names(text):
    for old,new in REGION_ALIASES.items():text=re.sub(r'\b'+old+r'\b',new,text)
    for old,new in ALIASES.items():
        text=re.sub(r'\b'+old+r'(?=\s+(?:(?:міськ|сільськ|селищн)\w*\s+)?громад)',new,text)
    return text


def geography_issues(projection):
    issues=[]
    for item in projection.get('provenance',[]):
        text=normalize_names(item.get('text',''))
        place=item.get('place')
        expected=PARENTS.get(place,place if place and place.endswith(' район') else None)
        pattern=(r'([А-ЯІЇЄҐ][А-ЯІЇЄҐа-яіїєґ’\x27-]+(?:\s*(?:,|та|і|й)\s*'
                 r'[А-ЯІЇЄҐ][А-ЯІЇЄҐа-яіїєґ’\x27-]+)*)'
                 r'(?:\s+(міськ\w*|сільськ\w*|селищн\w*))?\s+громад\w*')
        for match in re.finditer(pattern,text):
            for name in re.findall(r'[А-ЯІЇЄҐ][А-ЯІЇЄҐа-яіїєґ’\x27-]+',match[1]):
                if not re.search(r'(?:ськ|цьк)(?:а|ій|ої|у|ою|их|им|ими|ий|ому|ого)$',name):
                    continue  # A named city in a list is not a community adjective.
                choices=[r for r in CATALOG['communities'] if key(r['name'])==key(name)]
                if match[2]:
                    choices=[r for r in choices if r['type'].startswith(match[2][:4])]
                problem=None
                if not choices:
                    problem='unknown_community_name'
                elif expected and expected not in {r['district'] for r in choices}:
                    problem='community_district_mismatch'
                elif place=='Дніпро' and key(name)!=key('Дніпровська'):
                    problem='community_in_city_scope'
                if problem:
                    issues.append({'reason':'source_conflict','detail':problem,'name':name,
                                   'place':place,'record_ids':item.get('record_ids',[])})
    return issues


def overview(registry):
    projection=registry['public_projection']
    places={p.get('place') for p in projection['provenance'] if p.get('text')}
    districts_by_key={key(r['district'].replace(' район','')):r['district'] for r in CATALOG['communities']}
    texts=[p.get('text','') for p in projection['provenance']]
    for text in texts:
        for m in re.finditer(r'([А-ЯІЇЄҐ][а-яіїєґ’\x27-]+(?:,\s*[А-ЯІЇЄҐ][а-яіїєґ’\x27-]+)*(?:\s+та\s+[А-ЯІЇЄҐ][а-яіїєґ’\x27-]+)?)\s+район\w*',text):
            for word in re.findall(r'[А-ЯІЇЄҐ][а-яіїєґ’\x27-]+',m[1]):
                if key(word) in districts_by_key:
                    places.add(districts_by_key[key(word)])
        if re.search(r'місті Самар\b|м\.\s*Самар\b|у Самарі\b',text):
            places.add('Самар')
    # Canonical district names and customary regional forms share a scope.
    if 'Криворізький район' in places:places.add('Криворіжжя')
    if 'Нікопольський район' in places:places.add('Нікопольщина')
    city=[];districts=[]
    for place,word in [('Дніпро','Дніпрі'),('Передмістя Дніпра','передмісті Дніпра'),
                       ('Кривий Ріг','Кривому Розі'),('Нікополь','Нікополі'),('Павлоград','Павлограді'),('Самар','Самарі')]:
        if place in places:city.append(word)
    if 'Дніпро' in places and 'Передмістя Дніпра' in places:
        city=[x for x in city if x!='передмісті Дніпра']
        city[city.index('Дніпрі')]='Дніпрі й передмісті'
    for place,word in [('Дніпровський район','Дніпровського'),('Кам’янський район','Кам’янського'),
                       ('Криворіжжя','Криворізького'),('Нікопольщина','Нікопольського'),
                       ('Павлоградський район','Павлоградського'),('Самарівський район','Самарівського'),
                       ('Синельниківський район','Синельниківського')]:
        if place in places:districts.append(word)
    attacks=[r for r in registry['records'] if r['section']=='2.1' and r.get('display') and r['state'] not in {'excluded','review','mirror'}]
    if not attacks:
        return 'У перевірених джерелах повідомлень про атаки за звітний період не виявлено.'
    from event_brief import casualty_roles,damage_atoms
    sentence='Офіційні джерела повідомили про атаки та їхні наслідки '+('у '+', '.join(city) if city else '')
    if districts:
        sentence+=(', а також у громадах ' if city else 'у громадах ')+', '.join(districts)+(' району' if len(districts)==1 else ' районів')
    if not city and not districts:
        sentence='Офіційні джерела повідомили про атаки та їхні наслідки в області'
    result=[sentence+'.']
    roles=[casualty_roles(r['source_text']) or {} for r in attacks]
    dead=any(r.get('dead',0)>0 for r in roles)
    injured=any(r.get('injured',0)>0 for r in roles)
    if dead or injured:
        result.append('Є '+('загиблі та поранені' if dead and injured else 'загиблі' if dead else 'поранені')+'.')
    objects=set().union(*(damage_atoms(r['source_text']) for r in attacks))
    damage=[label for keys,label in [({'home','apartment'},'житло'),({'enterprise'},'підприємства'),
                                    ({'infrastructure'},'інфраструктуру'),({'cars','trucks'},'автомобілі')]
            if keys&objects]
    if damage:result.append('Пошкоджено '+(', '.join(damage[:-1])+' та '+damage[-1] if len(damage)>1 else damage[0])+'.')
    return ' '.join(result)


def smooth(text):
    """Grammar-only rules; unknown prose and all quantities remain intact."""
    text=normalize_names(text)
    text=re.sub(r'За (\d{1,2} \w+): У ',r'\1 у ',text)
    text=re.sub(r'За (\d{1,2} \w+): На ',r'\1 на ',text)
    text=re.sub(r'За (\d{1,2} \w+): Цілив ',r'\1 цілив ',text)
    text=re.sub(r'(За ранковими даними \d{1,2} \w+): У ',r'\1, у ',text)
    text=re.sub(r'(За ранковими даними \d{1,2} \w+): На ',r'\1, на ',text)
    text=re.sub(r'\b(\d+) поранені\b',r'\1 людей поранено',text)
    return text


def present_projection(registry):
    projection=registry['public_projection']
    corrected=[]
    for item in projection['provenance']:
        original=item.get('text','');changed=normalize_names(original)
        if original!=changed:
            corrected.append({'record_ids':item.get('record_ids',[]),'rule':'verified_community_spelling',
                              'reference':'https://pidgorodne.otg.dp.gov.ua/'})
    projection['paragraphs']=[city_prose(smooth(p)) for p in projection['paragraphs']]
    projection['paragraphs']=[p.replace('Криворіжжя та Синельниківський район:\nДСНС також повідомила про пошкодження об’єктів інфраструктури та ліквідацію пожеж.',
        'За спільними даними ДСНС щодо Криворізького та Синельниківського районів, пошкоджено об’єкти інфраструктури; пожежі ліквідовано.') for p in projection['paragraphs']]
    for r in registry.get('records',[]):
        for old,new in REGION_ALIASES.items():
            if re.search(r'\b'+old+r'\b',r['source_text']):
                corrected.append({'record_ids':[r['id']],'rule':'explicit_region_typo',
                                  'original':old,'replacement':new,'reference':r.get('source_url')})
    projection['name_normalizations']=corrected
    projection['overview']=overview(registry)
    projection['reference_checked_on']=CATALOG['checked_on']
    return geography_issues(projection)


def unsupported_incident_clocks(registry, report):
    """Check clock role, place and approximation, not a matching digit alone."""
    from fallback_report import sentences
    from event_brief import split_places
    clock=r'(?<![\d.])(\d{1,2})[:.](\d{2})(?![\d.])'
    canonical=lambda m:f'{int(m[1]):02d}:{m[2]}'
    evidence={}
    for r in registry.get('records',[]):
        if r['section']!='2.1' or r.get('reporting_period') or r['state'] in {'excluded','review','mirror'}:
            continue
        for place,body in split_places(r['source_text']):
            for sentence in sentences(body):
                if re.search(r'тривог|повідомлен|опублікован',sentence,re.I):continue
                if not re.search(r'атак|удар|обстріл|влучан',sentence,re.I):continue
                for match in re.finditer(clock,sentence):
                    prefix=sentence[max(0,match.start()-20):match.start()]
                    qualifier=re.search(r'\b(о|близько|приблизно|після|до|від)\s*$',prefix,re.I)
                    if qualifier and '.' in match[0] and qualifier[1].casefold() not in {'о','близько','приблизно'}:
                        continue  # A date such as 'від 23.10' is not a clock.
                    if qualifier:
                        evidence.setdefault((place,canonical(match)),set()).add(qualifier[1].casefold())
    section=report.split('2.1. Обстріли',1)[-1].split('2.2. Незаконне',1)[0]
    reporting={datetime.fromisoformat(r['reporting_period']).strftime('%H:%M') for r in registry.get('records',[]) if r.get('reporting_period')}
    problems=[];place=None
    for line in section.splitlines():
        if line.endswith(':') and (line[:-1] in PARENTS or line[:-1].endswith(' район')):
            place=line[:-1]
        for match in re.finditer(clock,line):
            value=canonical(match)
            prefix=line[max(0,match.start()-20):match.start()]
            if '.' in match[0] and not re.search(r'(\b(?:о|близько|приблизно|після|до|від)|~|≈)\s*$',prefix,re.I):
                continue
            if re.search(r'станом на\s*$',prefix) and value in reporting:continue
            roles=evidence.get((place,value),set())
            if not roles:
                problems.append(value);continue
            qualifier=re.search(r'(\b(?:о|близько|приблизно|після|до|від)|~|≈)\s*$',prefix,re.I)
            q=qualifier[1].casefold() if qualifier else None
            if 'о' in roles:continue
            if roles & {'близько','приблизно'} and q in {'близько','приблизно','~','≈'}:continue
            if roles & {'після','до','від'} and q in roles:continue
            problems.append(value)
    return problems


def transport_prose(text):
    """Condense validated travel impacts, retaining the exact closed segment."""
    text=re.sub(r'^\d{1,2} \w+ у Дніпрі діють зміни у русі громадського транспорту:\s*','Дніпро: ',text)
    text=text.replace('У зв’язку з ремонтом колії на Старому мосту призупиняється рух трамваїв. На час виконання робіт замість них працюватимуть автобуси.',
                      'На Старому мосту через ремонт колії призупиняється трамвайний рух; працюватимуть автобуси на заміну.')
    text=text.replace('У зв’язку з ремонтом колії на Старому мосту призупиняється рух трамваїв. Замість трамваїв працюватимуть автобуси.',
                      'На Старому мосту через ремонт колії призупиняється трамвайний рух; працюватимуть автобуси на заміну.')
    text=text.replace('буде тимчасово призупинено рух трамваїв','призупинять трамвайний рух')
    return text


def city_prose(paragraph):
    """A fully recognized daily city block; unknown additions stay verbatim.

    Different attacks are not declared one incident. The casualty number is
    explicitly city-wide, not attached to the destroyed house.
    """
    pattern=(r'(Дніпро:\n\d{1,2} \w+ у Дніпрі понівечені )([^.]+)\. '
             r'Загинула одна людина, її тіло дістали з-під завалів будинку\. '
             r'([\w’\x27]+) людей поранено, вони перебувають у лікарні\. '
             r'Зайнялася пожежа\. Ворог атакував критичну інфраструктуру Дніпра\. '
             r'Зруйнований приватний будинок\. Пошкоджені щонайменше (\d+) приватних осель\.')
    m=re.fullmatch(pattern,paragraph)
    if not m:return paragraph
    names=m[2].rsplit(', ',1)
    damage=' та '.join(names) if len(names)==2 else names[0]
    return (m[1]+damage+'. '+
        'Зафіксовано атаку критичної інфраструктури та пожежу. '+
        'Зруйновано приватний будинок, пошкоджено щонайменше '+m[4]+' приватних осель. '+
        'Загалом по місту одна людина загинула, '+m[3][:1].lower()+m[3][1:]+
        ' поранених перебувають у лікарні. Тіло загиблої людини рятувальники дістали з-під завалів будинку.')
