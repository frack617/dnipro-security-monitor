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


def background_reason(text):
    body = clean_lines(text)
    if (PREPAREDNESS.search(body[:650]) or
        re.search(r'радий вітати.{0,100}(?:посла|посол)|наша зустріч|предметом розмови', body, re.I)):
        if not CURRENT_IMPACT.search(body):
            return 'preparedness_or_meeting_without_current_impact'
    if BACKGROUND.search(clean_lines(text)[:650]):
        return 'background_without_current_incident'
    if re.search(r'(?:після вибухів|після обстрілів).{0,30}(?:у травні|у червні|минулого року)',
                 clean_lines(text), re.I):
        return 'historical_repair_article'
    return None


def current_attack_piece(text, published, start, end):
    """Separate explicit incident dates/clocks from the publication timestamp.

    Single clearly out-of-window incidents are excluded. A newer explicitly
    dated incident survives an older prefix. Unseparable mixed intervals are
    flagged for review instead of silently dropping current consequences.
    """
    from fallback_report import sentences
    body = clean_lines(text)
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
        generic = re.compile(
            r'(?:Після обстрілу )?(?:Виникла|Сталася|Спалахнула) (?:масштабна )?пожежа'
            r'(?:, (?:яку ліквідували вогнеборці|пошкоджені склади))?[.!]?|'
            r'Рятувальники (?:загасили|ліквідували) пожежу(?: та виявили тіла)?[.!]?', re.I)
        recognized, unknown = [], []
        for rec in records:
            for sentence in rec['detail_sentences']:
                (recognized if generic.fullmatch(sentence.strip()) else unknown).append((rec, sentence))
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
