"""Asserted utility/transport notices independent of attack keyword priority.

Keep publication clocks as notice clocks, never as incident times. Unknown
clauses remain visible; only complete known courtesy/navigation lines go away.
"""
import re
from datetime import datetime
from zoneinfo import ZoneInfo
from fallback_report import clean_lines

KYIV = ZoneInfo('Europe/Kyiv')


def notice_kind(text):
    body = clean_lines(text)
    transport = (re.search(r'знеструмлення тягових підстанцій|аварійним відключенням живлення', body, re.I)
                 and re.search(r'призупинено|зупинено|інтервал руху', body, re.I))
    if transport and not re.search(r'поран|загин|загиб|помер|евакуйовано',body,re.I):
        return '1.2'
    asserted = re.search(
        r'(?:діють|застосовано|запроваджено) екстрені відключення|'
        r'Дніпро (?:знову )?знеструмлений|'
        r'повернули світло частині споживачів|'
        r'без (?:світла|електрики) залишилися|'
        r'(?:водопостачання|водовідведення|життєзабезпечення).{0,100}(?:від генераторів|на роботу від генераторів)', body, re.I)
    # A mixed casualty/damage article remains an attack record. Do not demote
    # a station strike merely because it also mentions an outage.
    mixed = re.search(r'поран|загин|загиб|помер|пошкоджен[аоіий]+ (?:будин|вокзал|підприємств|гуртожит)', body, re.I)
    return '1.4' if asserted and not mixed else None


def service_notice(post):
    if notice_kind(post.get('text', '')) != '1.4':
        return None
    from source_claims import selected_text
    body = selected_text(post['text'])
    at = datetime.fromisoformat(post['published_at']).astimezone(KYIV)
    return f'Станом на {at:%H:%M %d.%m}: '+body


def emergency_transport(post):
    if not (re.search(r'знеструмлення тягових підстанцій|аварійним відключенням живлення',post.get('text',''),re.I)
            and re.search(r'призупинено|зупинено|інтервал руху',post.get('text',''),re.I)):
        return None
    body = clean_lines(post['text'])
    # Conflicting all-stop and autonomous-route exceptions cannot certify
    # either complete suspension or the exceptions as current. The shared
    # fact is the interruption affecting multiple routes. Keep the conflict
    # in audit rather than inventing which order superseded which.
    conflict = bool(re.search(r'всіх трамвайних та тролейбусних маршрутів зупинено', body, re.I)
                    and re.search(r'тролейбуси з автономним ходом.+курсують', body, re.I))
    if conflict:
        result = 'Дніпро: через знеструмлення тягових підстанцій призупинено рух низки трамвайних і тролейбусних маршрутів.'
        interval = re.search(r'Інтервал руху поїздів складає (\d+) хвилин', body, re.I)
        if interval:
            result += ' Метро працює з інтервалом '+interval[1]+' хвилин.'
        # Do not silently discard a new unfamiliar consequence outside the
        # recognised route-status lines.
        known = r'графіком вихідного дня\.|До уваги пасажирів|У зв[’\x27]язку з аварійним відключенням живлення|Інтервал руху|Через знеструмлення|роботу трамваїв|рух тролейбусів|тролейбуси з автономним ходом'
        from source_claims import selected_text
        extra = [line for line in post['text'].splitlines() if re.search(r'\w', line)
                 and not re.match(known, clean_lines(line), re.I)]
        if extra:
            result += ' '+selected_text('\n'.join(extra))
        return result
    from source_claims import selected_text
    return 'Дніпро: '+selected_text(post['text'])
