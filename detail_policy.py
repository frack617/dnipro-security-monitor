"""Publication-only detail rules; no guesses or changes to source evidence.

These checks detect a bounded set of invented facility types. They do not
certify a facility name, incident date or exact coordinates.
"""
import re

DETAIL_RULES = """
Конкретизація подій:
- Зберігай прямо названі в джерелі час атаки, населений пункт, тип і назву
  об'єкта. Зберігай слова «близько», «після», «попередньо» та інші уточнення.
- Час допису, тривоги, прольоту БпЛА або звуків вибухів не доводить часу
  влучання в конкретний об'єкт. Не перенось подробиці іншої події чи громади.
- Слово «інфраструктура» не означає логістичний комплекс, склад, підстанцію,
  водозабір або конкретне підприємство. Не додавай призначення без джерела.
- Не пиши «точний час не наведено», «назву об'єкта не уточнено», «населений
  пункт не повідомляється» та подібні коментарі про відсутність подробиць.
  Просто виклади наявні факти. Це не дозвіл приховувати невизначеність
  кількості постраждалих, стану людей, небезпеки чи перебігу рятувальних робіт.
"""


def missing_detail_formula(text):
    """Only complete no-detail sentences, never adjoining casualty/damage facts."""
    text = text.strip()
    topic = (r'(?:(?:(?:Точн\w*|Приблизн\w*)\s+)?час(?:\s+(?:атаки|атак|влучання|влучань|удару|ударів))?'
             r'|населен\w*\s+пункт\w*|назв\w*\s+(?:підприємств\w*|об[’ʼ\x27]єкт\w*)'
             r'|конкретн\w*\s+(?:локаці\w*|об[’ʼ\x27]єкт\w*)'
             r'|назви|призначення(?:\s+пошкоджених)?\s+об[’ʼ\x27]єктів)')
    context = r'(?:\s+(?:у|в)\s+(?:перевірених|доступних|офіційних)\s+(?:повідомленнях|джерелах|публікаціях))?'
    absent = r'(?:не\s+(?:наведено|уточнено|повідомлено|названо|оприлюднено|зазначено)|не\s+повідомляється)'
    return bool(re.fullmatch(topic + r'(?:(?:\s*,\s*|\s+(?:і|та)\s+)' + topic + r'){0,3}'
                             + context + r'\s+' + absent + context + r'[.!]?', text, re.I))


def clean_detail_prose(text):
    from fallback_report import sentences
    return '\n'.join(' '.join(s for s in sentences(line) if not missing_detail_formula(s))
                     for line in text.splitlines())


OBJECT_TYPES = {
    'logistics facility': r'логістичн\w*\s+(?:комплекс\w*|центр\w*|об[’ʼ\x27]єкт\w*|термінал\w*)',
    'warehouse': r'складськ\w*\s+(?:приміщенн\w*|комплекс\w*|термінал\w*)|\bсклад(?:і|у|и|ів|ом|ах)?\b',
    'substation': r'\bпідстанці\w*',
    'water intake': r'\bводозаб[іо]р\w*',
    'pumping station': r'насосн\w*\s+станці\w*',
    'power facility': r'енергетичн\w*\s+(?:об[’ʼ\x27]єкт\w*|інфраструктур\w*)',
    'water facility': r'водопровідн\w*\s+(?:об[’ʼ\x27]єкт\w*|інфраструктур\w*)',
}


def scoped_sentences(text):
    from fallback_report import sentences
    from event_brief import locality
    current = None
    for line in text.splitlines():
        for sentence in sentences(line):
            # A community is a narrower anchor than the district around it.
            community = re.search(r'([А-ЯІЇЄҐ][а-яіїєґ’ʼ\x27-]+)\s+(?:(?:міськ|сільськ|селищн)\w*\s+)?громад\w*', sentence)
            if community:
                current = re.sub(r'(?:ій|ої|ою|у|а)$', '', community[1].casefold())
            else:
                place = locality(sentence)
                if re.search(r'\b(?:Самар|Самарі|Самара|Самару)\b', sentence):
                    place = 'Самар'
                if re.search(r'\bКам[’ʼ\x27]янськ(?:е|ому|ого)\b', sentence):
                    place = 'Кам’янське'
                if place:
                    current = place
            yield current, sentence


def unsupported_object_types(attack_text, source_texts):
    evidence = [unit for source in source_texts for unit in scoped_sentences(source)]
    problems = []
    for scope, sentence in scoped_sentences(attack_text):
        for label, pattern in OBJECT_TYPES.items():
            if not re.search(pattern, sentence, re.I):
                continue
            if not any(re.search(pattern, body, re.I) and source_scope == scope
                       for source_scope, body in evidence):
                problems.append('unsupported object type: ' + label)
    return list(dict.fromkeys(problems))
