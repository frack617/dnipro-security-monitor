"""Presentation of an already checked brief; no inference or fact rewriting."""
import re
from datetime import datetime

from report_rules import PLACE_PATTERNS


TITLES = {
    '1.1': 'Загальна безпекова ситуація та підтверджені ризики',
    '1.2': 'Перекриття, обмеження доріг і зміни руху',
    '1.3': 'Оголошені вибухові роботи та контрольоване знешкодження',
    '1.4': 'Комунальні послуги, пожежі, аварії та практичні фактори',
    '2.1': 'Обстріли, ракетні атаки, атаки БпЛА та наслідки',
    '2.2': 'Незаконне поводження зі зброєю та вибухівкою',
    '2.3': 'Повідомлення про мінування цивільної інфраструктури',
    '2.4': 'Виявлення вибухонебезпечних предметів',
}


def words(text):
    return re.findall(r"[\w’'-]+", text.casefold())


def internal_sections(text):
    points = list(re.finditer(r'(?m)^([12]\.[1-4])\.\s+', text))
    if [m[1] for m in points] != list(TITLES):
        raise ValueError('Report layout requires exactly eight ordered sections')
    result = {}
    for index, point in enumerate(points):
        stop = points[index+1].start() if index+1 < len(points) else len(text)
        body = text[point.end():stop].strip()
        body = re.sub(r'(?m)^2\. Події:\s*$', '', body).strip()
        if point[1] == '2.4':
            body = re.split(r'\n\s*\n(?=Це огляд станом на |Примітка: це автоматичний огляд офіційних Telegram-джерел)', body, maxsplit=1)[0].strip()
        if not body:
            raise ValueError('Report layout cannot invent an empty section: '+point[1])
        result[point[1]] = body
    return result


def geographic_paragraphs(body):
    from fallback_report import sentences
    explicit = '|'.join('(?:'+pattern+')' for pattern in PLACE_PATTERNS.values())
    name = r"[А-ЯІЇЄҐ][А-Яа-яІіЇїЄєҐґ’'-]+"
    admin = (name+r"(?:\s+(?:міськ\w*|селищн\w*|сільськ\w*|територіальн\w*))?\s+(?:район\w*|громад\w*)"
             +r"(?:\s+"+name+r"\s+район\w*)?(?:\s+"+name+r"\s+област\w*)?")
    lead = re.compile(r'^(?:(?:У|В|На)\s+)?(?:'+admin+'|'+explicit+r')', re.I)
    paragraphs = []
    for paragraph in re.split(r'\n\s*\n', body.strip()):
        # Respect explicit author-written geographic headings and their order.
        if re.search(r'(?m)^[^\n:]{1,100}:\s*\n', paragraph):
            paragraphs.append(paragraph.strip())
            continue
        current = []
        for sentence in sentences(paragraph):
            match = lead.match(sentence)
            rest = sentence[match.end():].lstrip() if match else ''
            # A joint list is not evidence for assigning its facts to one place.
            joint = bool(re.match(r'(?:та|і|й)\b|[,/—–]', rest, re.I))
            if match and not joint:
                if current:
                    paragraphs.append(' '.join(current).replace('\n ', '\n').rstrip())
                label = match[0].strip()
                rest = rest.lstrip('.:').lstrip()
                # Keep inflected place phrases as complete sentences. Only a
                # standalone place label receives a colon and its own line.
                current = ([label+':\n'+rest] if sentence[match.end():].lstrip().startswith(('.', ':'))
                           else [sentence])
            else:
                current.append(sentence)
        if current:
            paragraphs.append(' '.join(current).replace('\n ', '\n').rstrip())
    formatted = '\n\n'.join(paragraphs)
    if words(formatted) != words(body):
        raise ValueError('Report layout changed section content')
    return formatted


# A bulletin's district count is not a whole-window total. Keep those numbers
# in 2.1 with their source periods; remove only the count modifier in 1.1.
DISTRICT_COUNT = re.compile(
    r"\b(?:\d+|один|одного|одному|два|двох|двом|три|трьох|трьом|чотири|чотирьох|чотирьом|"
    r"п[’']ять|п[’']яти|шість|шести|сім|семи|вісім|восьми|дев[’']ять|дев[’']яти|десять|десяти)"
    r"\s+(?=район(?:и|ів|ах|ам|ом|у|і)?\b)", re.I)


def polish_body(body, key):
    # Exact editorial corrections, not free rewriting or inferred facts.
    body = re.sub(r'\bупрожовж\b', 'упродовж', body, flags=re.I)
    if key == '1.1':
        body = DISTRICT_COUNT.sub('', body)
    if key == '2.1':
        for old, new in (
            ('Попередньо:', 'Попередньо повідомлялося:'),
            ('Пізніше:', 'Згодом повідомлено:'),
            ('Зведення:', 'У зведенні зазначено:'),
        ):
            body = re.sub(r'(?<!\w)'+re.escape(old), lambda _: '\n\n'+new, body)
        body = re.sub(r'\n[ \t]*\n(?:[ \t]*\n)+', '\n\n', body).strip()
    return body


PUBLIC_TITLES = {
    '1.1': '',
    '1.2': 'Сповіщення про проведення військових тренувань, навчань чи вибухонебезпечних робіт',
    '2.1': 'Обстріли, ракетні атаки та атаки БпЛА',
    '2.2': 'Незаконне поводження зі зброєю та вибухівкою / Резонансні правоохоронні операції',
    '2.3': 'Виявлення вибухонебезпечних предметів (ВНП)',
}
EMPTY = 'У перевірених джерелах повідомлень за звітний період не виявлено.'


def render_report(text, start_label, end_label, checked_label):
    """Map eight checked evidence categories to the user's five public points."""
    sections = internal_sections(text)
    end = datetime.strptime(end_label, '%H:%M %d.%m.%Y')
    # Window/check timestamps stay in diagnostics; the public header is the cutoff.
    lines = ['Станом на '+end.strftime('%d.%m.%Y %H.%M')]
    if text.lstrip().startswith('⚠️ Резервна автоматична версія'):
        lines += ['', '⚠️ Резервна автоматична версія']
        if 'Стислий огляд за останніми офіційними зведеннями' in text:
            lines += ['Стислий огляд за останніми офіційними зведеннями; повні джерела збережені окремо.']
    formatted = {}
    for key, body in sections.items():
        edited = polish_body(body, key)
        result = geographic_paragraphs(edited) if key in ('1.1', '2.1') else edited
        if words(result) != words(edited):
            raise ValueError('Report layout changed facts in '+key)
        formatted[key] = result
    general = [formatted['1.1']]
    for key, label in (('1.2', 'Транспорт і дороги'),
                       ('1.4', 'Комунальні послуги та інші практичні фактори')):
        if sections[key] != EMPTY:
            general.append(label+':\n'+formatted[key])
    law = [formatted['2.2']]
    if sections['2.3'] != EMPTY:
        # Keep the absence statement scoped to weapons when bomb threats exist.
        if sections['2.2'] == EMPTY:
            law = ['Зброя та правоохоронні операції:\n'+formatted['2.2']]
        law.append('Повідомлення про мінування:\n'+formatted['2.3'])
    public = {
        '1.1': '\n\n'.join(general),
        '1.2': formatted['1.3'],
        '2.1': formatted['2.1'],
        '2.2': '\n\n'.join(law),
        '2.3': formatted['2.4'],
    }
    for group, heading in ((1, 'ЗАГАЛЬНА СИТУАЦІЯ В ОБЛАСТІ (РАЙОНІ)'),
                           (2, 'ПОДІЇ У СФЕРІ БЕЗПЕКИ')):
        lines += ['', f'{group}. {heading}']
        for key, title in PUBLIC_TITLES.items():
            if not key.startswith(str(group)+'.'):
                continue
            lines += ['', (key+'. '+title).rstrip(), public[key]]
    return '\n'.join(lines).strip()
