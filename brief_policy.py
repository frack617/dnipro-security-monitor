"""User's publication scope; original operational evidence stays in the registry."""
import re
from datetime import datetime
from zoneinfo import ZoneInfo

KYIV = ZoneInfo('Europe/Kyiv')
POWER_SUMMARY = 'Для споживачів ЦЕК застосовуються погодинні відключення електроенергії. Графік може змінюватися протягом доби.'


def power_table(text):
    return bool(re.search(r'черг[аи]\s*\d+[.,]\d+', text, re.I)
                and re.search(r'відключ|електро|ГПВ|Укренерго', text, re.I))


def administrative_clause(text):
    """Exclude administrative assistance, never destruction of such a facility."""
    from fallback_report import sentences
    if len(sentences(text)) > 1:
        return False  # Line preprocessing must not discard neighbouring facts.
    administrative = re.search(
        r'пункт\w* (?:поліції|незламності)|штаб\w* (?:з ліквідації|ліквідації|поліції)|'
        r'прийм\w* (?:звернен|заяв|громадян)|компенсаці|відшкодуван|'
        r'єВідновлення|заяв\w* (?:на|щодо|про) (?:державн|пошкоджен)|'
        r'гаряч\w* ліні|телефон\w* для довідок', text, re.I)
    if not administrative:
        return False
    # Physical destruction, danger, victims and evacuation remain evidence.
    hazard = re.search(r'загин|поран|травмован|евакуй|врятован|зруйн|пошкоджено (?!майн)|'
                       r'зайнял|виникла пожеж|пошкоджен[аоіий]+ (?:будівл|будин|пункт|штаб)', text, re.I)
    return not hazard


def weapons_excerpt(text):
    """Keep the seizure in a mixed crime story; omit unrelated bribery details."""
    from fallback_report import sentences, clean_lines
    body = clean_lines(text)
    if not (re.search(r'вилуч|виявил|обшук', body, re.I)
            and re.search(r'арсенал|гранат|автомат|боєприпас|тротил', body, re.I)):
        return None
    # A spent fragment/UXO callout remains discovery, not a weapons seizure.
    if re.search(r'нерозірван|уламк|піротехнік|розмінув', body, re.I):
        return None
    kept = [s for s in sentences(body)
            if re.search(r'арсенал|серед вилученого|вилучил\w*[^.!?]*(?:збро|гранат|боєприпас)|'
                         r'виявил\w*[^.!?]*(?:збро|гранат|боєприпас)', s, re.I)]
    return ' '.join(dict.fromkeys(kept)) or None


def public_utilities(registry):
    """No queue tables or address lists; retain emergency water/power notices."""
    from fallback_report import clean_lines
    from fact_registry import DATE
    from report_rules import MONTHS
    today = datetime.fromisoformat(registry['window']['end']).date()
    schedules = []
    result = []
    for rec in registry.get('records', []):
        if rec['section'] != '1.4' or not rec.get('display'):
            continue
        raw = rec['source_text']
        published=datetime.fromisoformat(rec['published_at']).astimezone(KYIV)
        if published.date()<today and re.search(r'короткотривале|протягом \d+[-–]\d+ годин',raw,re.I):
            continue
        if power_table(raw):
            dates = list(DATE.finditer(raw))
            # An undated publication is not evidence for today's queue table.
            if any(int(m[1]) == today.day and MONTHS.index(m[2].lower())+1 == today.month for m in dates):
                schedules.append(rec)
            # An appended emergency consequence is independent of the table.
            from fallback_report import sentences
            result.extend(s for line in raw.splitlines() for s in sentences(clean_lines(line)) if
                re.search(r'^(?:Аварія|Через аварію|Унаслідок аварії|Пошкоджено|Зруйновано|Евакуйовано)\b',s,re.I))
            continue
        if re.search(r'планов\w* (?:робот|відключ)|у зв[’\x27]язку з проведенням планових', raw, re.I) and re.search(r'вул\.|пров\.|бульвар', raw, re.I):
            continue
        value = rec['display']
        if not administrative_clause(value):
            result.append(value)
    if schedules:
        result.append(POWER_SUMMARY)
    # Preserve parser/formatting identity only; never merge different notices.
    return list(dict.fromkeys(result))
