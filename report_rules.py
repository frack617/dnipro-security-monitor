"""Offline source checks. These reject detectable errors, not certify every fact."""
import re


NUMBER_WORDS = {
    "один": 1, "одна": 1, "одну": 1, "одного": 1,
    "два": 2, "дві": 2, "двоє": 2, "двох": 2,
    "три": 3, "троє": 3, "трьох": 3,
    "чотири": 4, "четверо": 4, "чотирьох": 4,
    "п'ять": 5, "п’ять": 5, "п'ятеро": 5, "п’ятеро": 5,
    "шість": 6, "шестеро": 6, "шістьох": 6,
    "сім": 7, "семеро": 7, "вісім": 8, "восьмеро": 8,
    "дев'ять": 9, "дев’ять": 9, "дев'ятеро": 9, "дев’ятеро": 9,
    "десять": 10, "десятеро": 10,
}
NUMBER = r"(?:\d+|" + "|".join(sorted(map(re.escape, NUMBER_WORDS), key=len, reverse=True)) + r")"
CASUALTY = r"(?:поран\w*|травм\w*|постраждал\w*|потерпіл\w*|госпіталіз\w*|доправ\w*|загин\w*|загибл\w*)"
PEOPLE = r"(?:люд\w*|осіб|особ\w*|цивільн\w*)"


def normalize(text):
    return re.sub(r"\s+", " ", text).lower().strip()


def number_value(token):
    return int(token) if token.isdigit() else NUMBER_WORDS[token]


def casualty_counts(text):
    text = normalize(text)
    # Counts must be grammatically attached to people/casualties, not ages,
    # house numbers, attack totals or numbers in adjacent sentences.
    patterns = (
        rf"\b({NUMBER})\s+(?:{PEOPLE}\s+)?(?:(?:дістал\w*|зазнал\w*|отримал\w*)\s+поран\w*|{CASUALTY})",
        rf"\b{CASUALTY}\s+({NUMBER})\s+{PEOPLE}",
        rf"\b({NUMBER})\s+{PEOPLE}\s+(?:бул\w*\s+)?(?:до лікарні\s+)?{CASUALTY}",
    )
    return {number_value(m.group(1)) for pattern in patterns for m in re.finditer(pattern, text)}


def attack_counts(text):
    return {int(n) for n in re.findall(r"\b(\d+)\s+(?:разів|рази|атак\w*|обстріл\w*)\b", normalize(text))}


def report_section(report, section):
    match = re.search(rf"(?ms)^{re.escape(section)}\.\s+(.*?)(?=^\d+\.\d+\.\s|^Це огляд|\Z)", report)
    return match.group(1) if match else ""


COMMUNITY_NAME = r"\b([А-ЯІЇЄҐ][а-яіїєґ’'-]+(?:ськ|цьк)(?:ій|ої|у|а|ою))\b"


def community_stems(text):
    return {re.sub(r"(?:ій|ої|у|а|ою)$", "", name.lower())
            for name in re.findall(COMMUNITY_NAME, text)}


def casualty_location_problems(section, posts):
    # Source bullet boundaries are essential: a summary's opening casualty
    # total must not attach itself to every community in following bullets.
    records = {}
    for post in posts:
        blocks = re.split(r"[▪●]\ufe0f?", post.get("text", ""))
        header_counts = casualty_counts(blocks[0]) if len(blocks) > 1 else set()
        positive_blocks = [block for block in blocks[1:]
                           if re.search(CASUALTY, block, re.I)
                           and not re.search(r"немає|без\s+(?:загиблих|поранених)", block, re.I)]
        for block in blocks:
            if "громад" not in block.lower():
                continue
            for stem in community_stems(block):
                counts = casualty_counts(block)
                # An explicit opening total can belong to the sole regional
                # casualty paragraph, even if that paragraph lists patients
                # individually instead of repeating the count.
                if not counts and len(positive_blocks) == 1 and block == positive_blocks[0]:
                    counts = header_counts
                records.setdefault(stem, set()).update(counts)
    markers = []
    for stem in records:
        for match in re.finditer(rf"\b{re.escape(stem)}\w*", section):
            markers.append((match.start(), match.end(), stem))
    markers.sort()
    problems = []
    for index, (start, end, stem) in enumerate(markers):
        stop = markers[index+1][0] if index+1 < len(markers) else len(section)
        counts = casualty_counts(section[end:stop])
        if counts - records[stem]:
            problems.append("casualties assigned to unsupported community: " + stem)
    return problems


def source_problems(report, posts):
    problems = []
    attacks = [p for p in posts if p.get("category_hint") == "2.1"]
    attack_text = normalize(" ".join(p.get("text", "") for p in attacks))
    section21 = normalize(report_section(report, "2.1"))
    section11 = normalize(report_section(report, "1.1"))
    if attacks and "повідомлень за звітний період не виявлено" in section11:
        problems.append("overview denies available attack reports")
    problems.extend(casualty_location_problems(section21, attacks))
    allowed_counts = set().union(*(casualty_counts(p.get("text", "")) for p in attacks))
    unsupported = casualty_counts(section21) - allowed_counts
    if unsupported:
        problems.append("unsupported casualty count: " + ", ".join(map(str, sorted(unsupported))))
    unsupported_attacks = attack_counts(section21 + " " + section11) - attack_counts(attack_text)
    if unsupported_attacks:
        problems.append("unsupported attack total")
    if attack_counts(section11):
        problems.append("attack counts belong in section 2.1 with their source periods")
    # Never manufacture a day/window total from separate source summaries.
    total_pattern = rf"(?:загалом|усього|всього)\s+(?:за\s+(?:добу|звітний період)\s+)?({NUMBER})\s+(?:{PEOPLE}\s+)?{CASUALTY}"
    for match in re.finditer(total_pattern, section21):
        if not any(number_value(m.group(1)) == number_value(match.group(1))
                   for m in re.finditer(total_pattern, attack_text)):
            problems.append("casualty total not explicitly supported by source")
    for label, pattern in (("children", r"\bдіт\w*|\bдитин\w*"),
                           ("rescuer", r"\bрятувальник\w*")):
        if re.search(pattern, section21) and not re.search(pattern, attack_text):
            problems.append("unsupported casualty/event detail: " + label)
    # Keep named communities from eligible attack reports, including lists
    # like 'Зеленодольська та Грушівська громади'. Inflections may change.
    for post in attacks:
        text = post.get("text", "")
        if not re.search(r"громад", text, re.I):
            continue
        for name in re.findall(r"\b([А-ЯІЇЄҐ][а-яіїєґ’'-]+(?:ськ|цьк)(?:ій|ої|у|а|ою))\b", text):
            stem = re.sub(r"(?:ій|ої|у|а|ою)$", "", name.lower())
            if not re.search(rf"\b{re.escape(stem)}\w*", section21):
                problems.append("missing attack community: " + name)
    for label, pattern in (
        ("culture centre", r"будин\w*\s+культур\w*"),
        ("kindergarten", r"дитяч\w*\s+сад\w*"),
        ("gas pipeline", r"газог[іо]н\w*"),
        ("power line", r"ліні\w*\s+електропередач\w*|\bлеп\b"),
    ):
        if re.search(pattern, attack_text) and not re.search(pattern, section21):
            problems.append("missing specific attack consequence: " + label)
    services = normalize(" ".join(p.get("text", "") for p in posts if p.get("category_hint") == "1.4"))
    section14 = normalize(report_section(report, "1.4"))
    for label, pattern in (
        ("power restrictions", r"\bгпв\b|відключен\w*|обмеження електропостачання"),
        ("weather warning", r"гроз\w*|штормов\w*|рівень небезпечності"),
    ):
        if re.search(pattern, services) and not re.search(pattern, section14):
            problems.append("missing service fact: " + label)
    return list(dict.fromkeys(problems))


EDITORIAL_RULES = """
Додатковий контроль точності:
- у 1.1 не наводь числову кількість атак; денні та нічні показники залишай у 2.1
  з окремим позначенням періодів. Не складай їх у власний добовий підсумок;
- кількості загиблих, поранених і госпіталізованих відтворюй точно, разом із
  місцем та епізодом. Не обчислюй власну загальну кількість постраждалих;
- не перенось до поточного вікна тижневі огляди, старі евакуації та старі атаки;
- для кожного району збережи названі громади, конкретні пошкоджені об’єкти та
  наслідки. Не скорочуй будинок культури, дитячий садок, газогін або ЛЕП до
  порожнього слова «інфраструктура». Час удару вказуй лише коли він є у джерелі;
- не розподіляй типи зброї або наслідки між громадами, якщо джерело дає лише
  загальний перелік. Не вигадуй точні кількості пошкоджених будинків;
- 1.1 — стислий регіональний огляд, без загальнодержавних політичних звернень;
- у 1.4 збережи повідомлення про ГПВ та обмеження електропостачання, а також
  погодні попередження. Завершені графіки описуй у минулому часі; опубліковані
  до 08:00 попередження на поточний день подавай як чинні після 08:00;
- наслідки удару й ліквідацію спричиненої ним пожежі об'єднуй у 2.1;
- збережи структуру, але не повторюй шаблонну назву категорії після номера пункту.
"""
