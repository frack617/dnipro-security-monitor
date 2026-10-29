"""Narrow evidence selection; archived sources are never rewritten in place."""
import re
from datetime import datetime, timedelta

from fallback_report import clean_lines
from report_rules import MONTHS

BACKGROUND = re.compile(
    r'конгресов\w*\s+діалог|відкри[влт]\w*\s+форум|під\w*\s+форум|'
    r'як залишатися онлайн|мап\w* інтернету|під[’\x27]?єднати інтернет|'
    r'готові не бити|переговор|зустрівся.{0,50}(?:команд|представник)|'
    r'просимо відключити всі прилади', re.I)
ATTACK = re.compile(r'атак|обстріл|удар|влучан', re.I)
CURRENT_IMPACT = re.compile(
    r'(?:ворог|росіяни|противник)\s+(?:знову\s+)?(?:атакував|атакували|вдарив|вдарили|обстріляв|обстріляли)|'
    r'(?:через|внаслідок|унаслідок).{0,65}(?:атаку|обстріл|влучання).{0,90}'
    r'(?:залишил|пошкоджен|зруйнован|загин|поран|знеструм)|'
    r'(?:сталася|виникла|спалахнула)\s+пожежа|'
    r'(?:загинули|загинув|поранено|постраждали)\b', re.I)
PREPAREDNESS = re.compile(
    r'підготов\w*.{0,50}(?:зим|опалювальн)|'
    r'(?:мають|має|встановили|встановлено).{0,45}(?:генератор|резервного живлення)|'
    r'рівні резервного живлення|готовність\s+\d+\s*%', re.I)
DATE = re.compile(r'\b(\d{1,2})\s+('+'|'.join(MONTHS)+r')\b', re.I)


def temporary_power_schedule(post):
    """Recognize a provider's complete address/schedule notice, not an attack.

    Only enumerated house lists may be reduced to 'some houses' on the exact
    source street names. Unfamiliar payloads remain untouched for the normal
    evidence path; no outage is extended to the whole street or municipality.
    """
    if post.get('channel', '').casefold() != 'cek_info':
        return None
    body = clean_lines(post.get('text', ''))
    # Only these non-factual courtesy/maintenance tails may be omitted. Any
    # new consequence or restoration statement prevents this compact form.
    tails = [
        'Перепрошуємо за тимчасові незручності та просимо поставитися до ситуації з розумінням!',
        'Обладнання нашої компанії працює в штатному режимі та готове до розподілу електричної енергії.',
        'Фахівці підприємства працюють над усуненням технологічного порушення 24/7.',
    ]
    for tail in tails:
        if body.endswith(tail):
            body = body[:-len(tail)].rstrip()
    match = re.fullmatch(
        r'Шановні споживачі м\.\s*([^.!?:]+?)\s+Повідомляємо, що '
        r'через технологічне порушення.{0,260}будинки споживачів за адресами:\s*'
        r'(.+?)\s*відключатимуться за тимчасовим графіком:\s*'
        r'(\d+ години? зі світлом,\s*\d+ години? без світла)[.!]?', body, re.I)
    if not match:
        return None
    # A separate material incident must never disappear behind service prose.
    if CURRENT_IMPACT.search(body) or re.search(r'поран|загиб|загин|пошкоджен|зруйн|пожеж', body, re.I):
        return None
    house = r'\d+[А-ЯІЇЄҐA-Zа-яіїєґa-z]?(?:\s*[-–]\s*\d+[А-ЯІЇЄҐA-Zа-яіїєґa-z]?)?(?:\s*\((?:непарні|парні)\))?'
    house_list = re.compile(house+r'(?:\s*,\s*'+house+r')*\s*[,.;]?', re.I)
    names = []
    for entry in match[2].strip().split(';'):
        address = re.fullmatch(r'\s*((?:вул\.|пр-т\.|бульвар|проїзд)\s+[^:;]+):\s*(.+?)\s*', entry)
        if not address or not house_list.fullmatch(address[2]):
            return None
        if address[1] not in names:
            names.append(address[1])
    if not names:
        return None
    cause = ('через спричинене ворожими атаками технологічне порушення ' if
             re.search(r'спричинен\w*[^,]*ворожими атаками', body, re.I) else '')
    return (match[1].strip().capitalize()+': '+cause+'для окремих будинків ('+', '.join(names)+
            ') оголошено тимчасовий графік електропостачання: '+match[3]+'.')


def background_reason(text):
    body = clean_lines(text)
    if (PREPAREDNESS.search(body[:650]) or
        re.search(r'радий вітати.{0,100}(?:посла|посол)|наша зустріч|предметом розмови', body, re.I)):
        if not CURRENT_IMPACT.search(body):
            return 'preparedness_or_meeting_without_current_impact'
    ceremony=re.search(r'побратим|підписал\w*.{0,60}угод|церемон|ратуш',body[:650],re.I)
    specific=re.search(r'(?:загинув|загинула|загинули|поранено|постраждали|пошкоджено|зруйновано)\b',body,re.I)
    if ceremony and not specific:
        return 'ceremony_without_asserted_operational_consequence'
    if BACKGROUND.search(clean_lines(text)[:650]):
        return 'background_without_current_incident'
    if re.search(r'(?:після вибухів|після обстрілів).{0,30}(?:у травні|у червні|минулого року)',
                 clean_lines(text), re.I):
        return 'historical_repair_article'
    return None


def regional_security_operation(post):
    """Retain a source-linked SBU operation outside the oblast when the
    suspect's reconnaissance explicitly targeted this region. Place of
    detention and place of hostile activity remain separate source sentences.
    Generic birthplace/agency-address mentions do not establish that link.
    """
    if post.get('channel','').casefold() != 'sbukr':
        return None
    lines = post.get('text','').splitlines()
    if not lines or not re.search(r'^СБУ затримала\b',lines[0].strip()):
        return None
    from fallback_report import sentences
    body = sentences(clean_lines('\n'.join(lines[1:])))
    place = re.compile(r'\bДніпр(?:о|і|а|у)\b|Дніпропетровщин\w*|Дніпропетровськ\w*\s+област\w*',re.I)
    links = [s for s in body if place.search(s)
             and re.search(r'розвідав|розвідував|коригував|наводив|відстежував',s,re.I)
             and not re.search(r'Головного управління|процесуальн\w* керівництв',s,re.I)]
    # Prefer the independently worded reconnaissance sentence over a national
    # overview that names several cities. Never transplant Odessa target types.
    links.sort(key=lambda s:(bool(re.search(r'Одес|Києв|Київ',s,re.I)),len(s)))
    action = next((s for s in body if re.search(r'^Контррозвідка.{0,65}затримала\b',s,re.I)),None)
    identity = next((s for s in body if s.startswith('Фігурантом виявився')),None)
    custody = next((s for s in body if re.search(r'^Зловмисник перебуває під вартою',s,re.I)),None)
    if not action or not links:
        return None
    return ' '.join(dict.fromkeys(s for s in [action,identity,links[0],custody] if s))


def prevention_without_event(text):
    """Instructions and lessons are not assertions of a discovered item or
    an enforcement operation. Require a finite affirmative event statement.
    """
    body = clean_lines(text)
    educational = re.search(r'нагадує|закликає|правила.{0,20}безпеки|як діяти|заняття|школяр|не торкайтеся',body,re.I)
    asserted = re.search(r'\b(?:затримал[аи]|затримано|виявил[аи]|виявлено|вилучил[аи]|вилучено|'
                         r'знешкодил[аи]|знешкоджено|викрил[аи]|викрито|ліквідувал[аи]|'
                         r'повідомили.{0,35}підозр|засудил[аи]|засуджено)\b',body,re.I)
    return bool(educational and not asserted)


def official_damage_excerpt(post):
    """An attributed city official's damage statement, not the whole article.

    The exact source sentences remain auditable. Use only one unambiguous
    official quote and an explicit district/date sentence from the article;
    otherwise decline this route instead of guessing a location or quantity.
    """
    if post.get('channel','').casefold() != 'dniprocityofficial':
        return None
    from fallback_report import sentences
    raw=post.get('text','')
    quotes=[]
    for match in re.finditer(r'«([^«»]+)»\s*,?\s*[—–-]\s*([^\n]+)',raw,re.S):
        attribution=match[2]
        if re.search(r'заступниц|голов|начальник|речник',attribution,re.I) and re.search(r'адміністрац|міськ|ДСНС|ОВА',attribution,re.I):
            quotes.append((match[1],attribution))
    quotes=list(dict.fromkeys(quotes))
    if len(quotes)!=1:
        return None
    quotes=[quotes[0][0]]
    locality=next((s for line in raw.splitlines() for s in sentences(clean_lines(line))
                   if re.search(r'\b\d{1,2}\s+(?:'+ '|'.join(MONTHS)+r')\b',s,re.I)
                   and re.search(r'район\w* Дніпра.{0,35}під ударом',s,re.I)),None)
    if not locality:
        return None
    # A school-damage article has the same explicit district/date and a
    # uniquely attributed factual quotation as the private-house route.
    quote_sentences=sentences(clean_lines(quotes[0]))
    school_quote=(re.search(r'пошкоджено два заклади освіти',clean_lines(quotes[0]),re.I) and
                  re.search(r'шести багатоповерхових будинках',clean_lines(quotes[0]),re.I))
    if school_quote:
        outside=raw.replace(quotes[0],'')
        if re.search(r'евакуйовано|врятовано|загинул[аи]|\d+[- ]річн|поранено \d+',outside,re.I):
            return None  # Never discard an independent clinical/rescue fact.
        administrative=[r'Щодо допомоги: жителі можуть звертатися безпосередньо до Лівобережної адміністрації\.',
            r'Зараз на місцях працюють представники нашої адміністрації, поліції та волонтерських організацій, які надають усю необхідну допомогу\.']
        facts=[s for s in quote_sentences if not any(re.fullmatch(p,s) for p in administrative)]
        return ' '.join(dict.fromkeys([locality]+facts))
    facts=[s for s in sentences(clean_lines(quotes[0])) if re.search(
        r'пошкоджено|зруйновано|Горів|Горіла|Горіли|загин|поран|без постраждалих|пожеж.{0,30}ліквід',s,re.I)]
    if not facts or not any(re.search(r'пошкоджено\s+\d+\s+приватних будинків',s,re.I) for s in facts):
        return None
    return ' '.join(dict.fromkeys([locality]+facts))


def current_attack_piece(text, published, start, end):
    """Separate explicit incident dates/clocks from the publication timestamp.

    Single clearly out-of-window incidents are excluded. A newer explicitly
    dated incident survives an older prefix. Unseparable mixed intervals are
    flagged for review instead of silently dropping current consequences.
    """
    from fallback_report import sentences
    body = clean_lines(text)
    # A recap of the completed preceding night, published on the window's
    # start date, is not a newly timed incident after 08:00. An explicit later
    # attack clock/date still follows the incident-anchor path below.
    if completed_chronological_day_recap(body,published,start):
        return None,'completed_chronological_previous_day_recap'
    prior_night=(published.date()==start.date() and
                 re.search(r'Протягом ночі|Упродовж ночі|Цієї ночі|З вечора до ранку',body,re.I))
    if prior_night:
        later_clock=re.search(r'(?:після|о)\s+(0?8|0?9|1\d|2[0-3])(?:[:.](\d{2})|-ї(?: години)?)',body,re.I)
        if later_clock:
            at=published.replace(hour=int(later_clock[1]),minute=int(later_clock[2] or 0),second=0,microsecond=0)
            if at>published or not start<=at<end:
                return text,'mixed_incident_times_requires_review'
            offset=0
            for sentence in sentences(body):
                pos=body.find(sentence,offset)
                if pos<=later_clock.start()<pos+len(sentence):
                    if has_operational_attack_assertion(sentence):
                        return body[pos:],'explicit_new_episode_after_prior_night'
                    break
                offset=pos+len(sentence)
            return text,'mixed_incident_times_requires_review'
        dates=list(DATE.finditer(body))
        if not dates or all((MONTHS.index(m[2].lower())+1,int(m[1])) <= (start.month,start.day) for m in dates):
            return None,'completed_prior_night_recap'
    relative_old = bool(re.search(r'вчорашн\w*.{0,35}(?:атак|удар|обстріл)', body, re.I)
                        and published.date()-timedelta(days=1) < start.date())
    anchors = []
    for match in DATE.finditer(body):
        after = body[match.end():match.end()+100]
        if not ATTACK.search(after):
            continue
        # A dated publication label is not an incident anchor.
        if re.search(r'(?:повідомлення від|опубліковано)\s*$', body[:match.start()], re.I):
            continue
        try:
            day = datetime(published.year, MONTHS.index(match[2].lower())+1, int(match[1])).date()
            if (day-published.date()).days > 180:
                day = day.replace(year=day.year-1)
            clock = re.match(r'\s*(?:(?:вранці|увечері|вночі)\s+)?'
                             r'(?:(о|близько|приблизно)\s+)(\d{1,2})[:.](\d{2})', after, re.I)
            at = (datetime(day.year,day.month,day.day,int(clock[2]),int(clock[3]),tzinfo=start.tzinfo)
                  if clock else None)
        except ValueError:
            continue
        if clock and clock[1].lower() != 'о' and (at <= start or at >= end):
            return text, 'approximate_boundary_time_requires_review'
        inside = (start <= at < end) if at else (start.date() <= day <= end.date())
        anchors.append((match, day, inside, at))
    if anchors and not any(inside for _,_,inside,_ in anchors):
        return None, 'explicit_incident_outside_window'
    current = [(m,d,i,t) for m,d,i,t in anchors if i]
    if current and (relative_old or not anchors[0][2]):
        match = current[0][0]
        # Include the new sentence's own place phrase. Never carry an old
        # geographic heading into a later episode or discard a new one.
        offset, cut = 0, match.start()
        for sentence in sentences(body):
            pos = body.find(sentence, offset)
            if pos <= match.start() < pos+len(sentence):
                if any(pos <= old.start() < match.start() for old,_,inside,_ in anchors if not inside):
                    return text, 'mixed_incident_times_requires_review'
                cut = pos
                break
            offset = pos+len(sentence)
        if any(not inside and m.start() >= cut for m,_,inside,_ in anchors):
            return text, 'mixed_incident_times_requires_review'
        return body[cut:], 'explicit_new_episode_after_history'
    if relative_old:
        return None, 'explicit_previous_day_incident'
    if anchors and any(not inside for _,_,inside,_ in anchors):
        return text, 'mixed_incident_times_requires_review'
    return text, None


def warehouse_supplement(text, selected, published, linked_update=False):
    """Keep nonnumeric additions to a matching dated warehouse synopsis.

    This is a bounded synopsis rule, not a new incident identity. Different
    numeric roles, explicit separate clocks or another attack require review.
    Nothing is added to a bulletin's casualty count.
    """
    from fallback_report import sentences
    from report_rules import NUMBER, number_value
    body = clean_lines(text)
    if not (re.search(r'склад', body, re.I) and re.search(r'\bДніпр(?:о|і|а)\b', body)):
        return None
    targets = [r for r in selected if r.get('reporting_period')
               and r['reporting_period'][:10] == published.date().isoformat()
               and re.search(r'склад', r['source_text'], re.I)
               and re.search(r'\bДніпр(?:о|і|а)\b', r['source_text'])]
    if len(targets) != 1:
        return None
    from report_rules import PLACE_PATTERNS, community_stems
    def places(value):
        return {name for name,pattern in PLACE_PATTERNS.items() if re.search(pattern,value,re.I)}
    source_places = places(body)
    target_places = places(targets[0]['source_text'])
    if source_places - target_places - {'Дніпропетровська область'}:
        return {'conflict': True, 'display': None}
    if set(community_stems(body)) - set(community_stems(targets[0]['source_text'])):
        return {'conflict': True, 'display': None}
    # Unknown quantities and differences must not disappear behind the summary.
    def roles(value):
        result = set()
        for m in re.finditer(r'\b('+NUMBER+r')\s+(?:[а-яіїєґ]+\s+){0,4}(загин\w*|поран\w*|дістал\w*)', value, re.I):
            result.add(('death' if m[2].lower().startswith('загин') else 'injured', number_value(m[1].lower())))
        for m in re.finditer(r'\bдо\s+('+NUMBER+r')\s+зросла кількість поранених', value, re.I):
            result.add(('injured', number_value(m[1].lower())))
        return result
    asserted, allowed = roles(body), roles(targets[0]['source_text'])
    superseded = (linked_update and all(any(role == other and count <= latest for other, latest in allowed)
                                         for role, count in asserted))
    if asserted and not asserted.issubset(allowed) and not superseded:
        return {'conflict': True, 'display': None}
    if re.search(r'\b(?:о|близько)\s+\d{1,2}[:.]\d{2}|(?:окрем\w*|повторн\w*)\s+(?:атак|удар)', body, re.I):
        return {'conflict': True, 'display': None}
    fire_clauses = re.split(r'(?=\b(?:Виникла|Сталася|Спалахнула|Рятувальники)\b)', body)
    additions = [s for part in fire_clauses for s in sentences(part) if re.search(r'пожеж', s, re.I)
                 and not re.search(r'поран|загин|рятувальник\w*\s+та\s+\d', s, re.I)]
    if not additions:
        return {'conflict': False, 'display': None}
    location = re.search(r'у передмісті Дніпра', body, re.I)
    label = 'У передмісті Дніпра, на складах' if location else 'У Дніпрі, на складах'
    return {'conflict': False, 'display': label+': '+' '.join(additions),
            'target_id': targets[0]['id'], 'detail_label': label, 'detail_sentences': additions}


def warehouse_generic_statement(sentence):
    return bool(re.fullmatch(
        r'(?:Після обстрілу )?(?:Виникла|Сталася|Спалахнула) (?:масштабна )?пожежа'
        r'(?:, (?:яку ліквідували вогнеборці|пошкоджені склади))?[.!]?|'
        r'Рятувальники (?:загасили|ліквідували) пожежу(?: та виявили тіла)?[.!]?',sentence.strip(),re.I))


def consolidate_warehouse_details(selected):
    """Collapse only enumerated generic fire statements, never unfamiliar facts.

    Casualty numbers stay verbatim in the dated bulletin. Every contributing
    record retains its original text and source key in the audit registry.
    """
    groups = {}
    by_id = {r['id']: r for r in selected}
    for rec in selected:
        target = rec.get('warehouse_target')
        if target in by_id and rec.get('display'):
            groups.setdefault(target, []).append(rec)
    for target_id, records in groups.items():
        recognized, unknown = [], []
        for rec in records:
            for sentence in rec['detail_sentences']:
                (recognized if warehouse_generic_statement(sentence) else unknown).append((rec, sentence))
        if not recognized:
            continue
        target = by_id[target_id]
        # A warehouse damage phrase may be omitted only if the dated block
        # already states this damage. Otherwise retain that source sentence.
        if not re.search(r'(?:пошкоджен|понівечен)\w*\s+склад', target['source_text'], re.I):
            unknown += [(r,s) for r,s in recognized if 'пошкоджені склади' in s]
        def score(item):
            text = item[1].lower()
            return (bool(re.search(r'ліквід|загас', text)), 'масштабна' in text,
                    bool(re.search(r'виникла|сталася|спалахнула', text)))
        winner, sentence = max(recognized, key=score)
        sentence = re.sub(r' та виявили тіла(?=[.!]?$)', '', sentence)
        details = [winner['detail_label']+': '+sentence]
        if any('виявили тіла' in s for _,s in recognized):
            details.append('Рятувальники виявили тіла.')
        for rec, body in unknown:
            detail = rec['detail_label']+': '+body
            if detail not in details:
                details.append(detail)
        target['display'] += ' '+' '.join(details)
        target['detail_source_refs'] = sorted({r['source_key'] for r in records})
        for rec in records:
            rec['state'], rec['reason'], rec['display'] = 'supplement', 'fire_details_in_bulletin_block', None
    return selected


def dated_power_interruption(post):
    """Keep a provider's explicit start AND end date, not an inferred duration."""
    if post.get('channel','').casefold()!='cek_info':
        return None
    body=clean_lines(post.get('text',''))
    match=re.search(r'з (\d{1,2}:\d{2}) (\d{2}\.\d{2}\.\d{4}) до (\d{1,2}:\d{2}) (\d{2}\.\d{2}\.\d{4}) буде припинено подачу електроенергії за адресами:',body,re.I)
    city=re.search(r'Шановні споживачі м\.\s*([А-ЯІЇЄҐ][А-ЯІЇЄҐа-яіїєґ’\x27-]+)',body)
    if not match or not city:
        return None
    from fallback_report import unique_texts
    if len(re.findall(r'\b(?:м\.|с\.)\s*',post['text']))!=1:
        return None
    try:
        begin=datetime.strptime(match[2]+' '+match[1],'%d.%m.%Y %H:%M')
        finish=datetime.strptime(match[4]+' '+match[3],'%d.%m.%Y %H:%M')
        if finish<=begin:
            return None
    except ValueError:
        return None
    addresses=body[match.end():].strip()
    footer='Дякуємо за розуміння та перепрошуємо за тимчасові незручності'
    if addresses.endswith(footer):
        addresses=addresses[:-len(footer)].strip()
    house=r'\d+(?:/\d+)?[А-ЯІЇЄҐA-Zа-яіїєґa-z]?(?:\s*[-–]\s*\d+[А-ЯІЇЄҐA-Zа-яіїєґa-z]?)?(?:\s*\((?:непарні|парні)\))?'
    names=[]
    for item in addresses.rstrip('.').split(';'):
        address=re.fullmatch(r'\s*((?:вул\.|пров\.|пр-т\.|бульвар|проїзд)\s+[^:;]+):\s*('+house+r'(?:\s*,\s*'+house+r')*)\s*',item)
        if not address:
            return None
        names.append(address[1])
    streets=unique_texts(names)
    if not streets or re.search(r'загин|поран|пожеж|пошкоджен|відновлено',body,re.I):
        return None
    cause=('через термінові аварійно-відновлювальні роботи ' if 'терміновими аварійно-відновлювальними роботами' in body else '')
    return (city[1].capitalize()+': '+cause+'анонсовано припинення електропостачання з '+
            match[1]+' '+match[2]+' до '+match[3]+' '+match[4]+
            ' для окремих будинків на '+', '.join(streets)+'.')


def has_operational_attack_assertion(text):
    """Positive event admission: an attack keyword alone is insufficient.

    Require an asserted action, physical consequence or casualty statement.
    Generic references to a city living under threat are not incident facts.
    """
    body=clean_lines(text)
    from report_rules import asserted_counts
    if asserted_counts(body):
        return True
    if re.search(r'без (?:світла|води) залиш(?:илися|ився|илася)|знеструмлен[оі]|припинено подачу електроенергії',body,re.I):
        return True
    if re.search(r'(?:ворог|росіяни|противник|окупанти|російські війська)\s+(?:знову\s+)?(?:атакува[вл]\w*|вдар[ивл]\w*|завда[вл]\w*\s+удар|обстріля[вл]\w*)',body,re.I):
        return True
    if re.search(r'\b(?:пошкоджено|пошкоджені|пошкоджена|пошкоджений|понівечено|понівечені|понівечена|зруйновано|зруйнований|зруйновані|вигоріла|горів|горіла|травмовано)\b',body,re.I):
        return True
    return bool(re.search(r'(?:виникла|сталася|зайнялася|спалахнула) пожежа|ліквідувал\w*.{0,25}(?:пожеж|загорян)|тіло загибл|під ударом|потерпали',body,re.I))


def queue_power_schedule(post, details=False):
    """A complete operator queue table, with its declared and row intervals.

    Keep both when a row crosses the declared midnight boundary. Never infer
    that all oblast residents or all addresses belong to this operator.
    Unrecognised appended consequences decline this bounded formatter.
    """
    if post.get('channel','').casefold()!='cek_info':return None
    body=clean_lines(post.get('text',''))
    match=re.fullmatch(
        r'Шановні споживачі! Повідомляємо, що за розпорядженням диспетчерського центру НЕК ["«]Укренерго["»], '
        r'(\d{1,2}) ('+'|'.join(MONTHS)+r') з (\d{1,2}:\d{2}) до (\d{1,2}:\d{2}) '
        r'застосовуватимуться відключення наступних черг:\s*(.+?)\s*'
        r'Попереджаємо, що протягом доби, за розпорядженням НЕК ["«]Укренерго["»], графік може змінюватися[.!]?',body,re.I)
    is_update=False
    if match:
        day_number,month,start_clock,end_clock,table=match.groups()
    else:
        updated=re.fullmatch(
            r'Шановні споживачі! Повідомляємо про зміни у ГПВ з (\d{1,2}:\d{2}) до (\d{1,2}:\d{2}) на '
            r'(\d{1,2}) ('+'|'.join(MONTHS)+r'), за розпорядженням диспетчерського центру НЕК ["«]Укренерго["»]\s*'
            r'(.+?)\s*Попереджаємо, що протягом доби, за розпорядженням НЕК ["«]Укренерго["»], графік може змінюватися[.!]?',body,re.I)
        if not updated:return None
        start_clock,end_clock,day_number,month,table=updated.groups();is_update=True
    entries=list(re.finditer(r'Черга (\d+\.\d+)\s+(\d{1,2}:\d{2})\s*[–—-]\s*(\d{1,2}:\d{2})',table,re.I))
    if not entries or re.sub(r'Черга \d+\.\d+\s+\d{1,2}:\d{2}\s*[–—-]\s*\d{1,2}:\d{2}','',table,flags=re.I).strip():return None
    def clock(value):
        h,m=map(int,value.split(':'))
        if not (0<=h<=24 and 0<=m<60 and (h<24 or m==0)):raise ValueError('clock')
        return f'{h:02}:{m:02}'
    try:
        year=datetime.fromisoformat(post['published_at']).year
        day=datetime(year,MONTHS.index(month.lower())+1,int(day_number))
        declared=(clock(start_clock),clock(end_clock));groups={}
        for entry in entries:
            interval=(clock(entry[2]),clock(entry[3]))
            groups.setdefault(interval,[]).append(entry[1])
        if len({e[1] for e in entries})!=len(entries):return None
    except (ValueError,KeyError):return None
    rows=[]
    for (a,b),queues in groups.items():
        row='черги '+', '.join(queues)+' — '+a+'–'+b
        if b<a:row+=' наступної доби'
        rows.append(row)
    rendered=('ЦЕК: '+('оновлені ' if is_update else '')+'графіки відключення електроенергії для споживачів оператора на '+day.strftime('%d.%m.%Y')+
            '; заявлений період '+declared[0]+'–'+declared[1]+'. За таблицею оператора: '+
            '; '.join(rows)+'. За повідомленням оператора, графік протягом доби може змінюватися.')
    if details:
        return dict(text=rendered,date=day.date().isoformat(),declared=list(declared),
                    queues=sorted(e[1] for e in entries),is_update=is_update,operator='cek_info')
    return rendered


def completed_chronological_day_recap(body,published,start):
    """Bounded past-tense completed-day chronology on the window start day.

    The last explicit clock is later than publication, hence belongs to the
    previous day. Require an ordered series linked by 'за кілька годин' and
    a completed police daily tally; a mere publication date/count never fits.
    Explicit dates/today/new episodes disable this inference.
    """
    if published.date()!=start.date():return False
    if not (re.search(r'Упродовж доби армія рф завдала',body,re.I) and
            re.search(r'За кілька годин російські війська повторно вдарили',body,re.I) and
            re.search(r'Загалом за добу до поліції надійшло \d+ повідомлень',body,re.I)):
        return False
    if DATE.search(body) or re.search(r'сьогодні|щойно|після 08:|після 8:|завтра|очікується|планується',body,re.I):return False
    times=[int(m[1])*60+int(m[2] or 0) for m in re.finditer(r'\b(?:Після|Близько|о) (\d{1,2})(?::(\d{2})|-ї(?: години)?)',body,re.I)]
    return (len(times)==2 and times[0]<times[1] and times[1]>published.hour*60+published.minute and
            'ворог знову атакував' in body)
