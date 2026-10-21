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
DATE = re.compile(r'\b(\d{1,2})\s+('+'|'.join(MONTHS)+r')\b', re.I)


def background_reason(text):
    if BACKGROUND.search(clean_lines(text)[:650]):
        return 'background_without_current_incident'
    if re.search(r'(?:після вибухів|після обстрілів).{0,30}(?:у травні|у червні|минулого року)',
                 clean_lines(text), re.I):
        return 'historical_repair_article'
    return None


def current_attack_piece(text, published, start, end):
    """Only explicit incident anchors permit removing an older episode prefix.

    Uncertain morning clock stays with the existing audit rule. The routine
    never converts a publication clock into an incident clock.
    """
    body = clean_lines(text)
    if re.search(r'вчорашн\w*.{0,35}(?:атак|удар|обстріл)', body, re.I):
        day = published.date()-timedelta(days=1)
        if day < start.date():
            return None, 'explicit_previous_day_incident'
    anchors = []
    for match in DATE.finditer(body):
        after = body[match.end():match.end()+100]
        if not ATTACK.search(after):
            continue
        try:
            day = datetime(published.year, MONTHS.index(match[2].lower())+1, int(match[1])).date()
            if (day-published.date()).days > 180:
                day = day.replace(year=day.year-1)
        except ValueError:
            continue
        anchors.append((match, day))
    if anchors and all(day < start.date() for _, day in anchors):
        return None, 'explicit_old_incident_date'
    if anchors and anchors[0][1] < start.date():
        for match, day in anchors:
            if start.date() <= day <= end.date():
                return body[match.start():], 'explicit_new_episode_after_history'
    # Mixed summaries sometimes have an undated old lead followed by an
    # explicit new attack. Only a repeated-attack marker permits this split.
    for match, day in anchors:
        if (start.date() <= day <= end.date() and match.start() > 0
            and re.match(r'\s*(?:ворог|росіяни).{0,20}знову\s+атак', body[match.end():], re.I)):
            return body[match.start():], 'explicit_new_episode_after_history'
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
    if re.search(r'\bо\s+\d{1,2}:\d{2}|окрем\w* атак|повторн\w* удар', body, re.I):
        return {'conflict': True, 'display': None}
    fire_clauses = re.split(r'(?=\b(?:Виникла|Сталася|Спалахнула|Рятувальники)\b)', body)
    additions = [s for part in fire_clauses for s in sentences(part) if re.search(r'пожеж', s, re.I)
                 and not re.search(r'поран|загин|рятувальник\w*\s+та\s+\d', s, re.I)]
    if not additions:
        return {'conflict': False, 'display': None}
    location = re.search(r'у передмісті Дніпра', body, re.I)
    label = 'У передмісті Дніпра, на складах' if location else 'У Дніпрі, на складах'
    return {'conflict': False, 'display': label+': '+' '.join(additions)}
