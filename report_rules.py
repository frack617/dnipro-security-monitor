"""Offline source checks. These reject detectable errors, not certify every fact."""
import re


NUMBER_WORDS = {
    "один": 1, "одна": 1, "одну": 1, "одного": 1, "однієї": 1, "одній": 1,
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


def explicit_casualty_totals(text):
    totals = set()
    for match in re.finditer(r"\b(?:загалом|усього|всього)\b[^.!?;]{0,180}", normalize(text)):
        totals.update(casualty_counts(match.group(0)))
    return totals


def required_attack_counts(posts):
    """Keep latest comparable multi-district bulletin, without inventing a total."""
    bulletins = {}
    for post in sorted(posts, key=lambda p: p.get("published_at", "")):
        text = normalize(re.split(r"[▪●]", post.get("text", ""))[0])
        counts = attack_counts(text)
        scope = re.search(r"\b(\d+|два|двох|три|трьох|чотири|чотирьох|п'ять|п’ять)"
                          r"\s+район\w*", text)
        if not counts or not scope:
            continue
        if re.search(r"вночі|уночі|за ніч|у ніч|цієї ночі", text):
            period = "night"
        elif re.search(r"вдень|удень|упродовж дня|протягом дня|за день", text):
            period = "day"
        else:
            period = "unspecified"
        date = post.get("published_local", "")[:10] or post.get("published_at", "")[:10]
        key = (date, period, number_value(scope.group(1)))
        bulletins[key] = counts
    return set().union(*bulletins.values()) if bulletins else set()


def required_fact_checklist(posts):
    """Concise source inventory, given BEFORE generation as well as repair."""
    facts = []
    for post in posts:
        if post.get("category_hint") != "2.1":
            continue
        text = re.sub(r"\s+", " ", post.get("text", "")).strip()
        header = re.split(r"[▪●]", text)[0]
        scope = re.search(rf"\b({NUMBER})\s+район\w*", header, re.I)
        date = re.search(DATE_WORDS, header, re.I)
        date_label = date.group(0) if date else post.get("published_local", "")[:10]
        if scope:
            for count in sorted(attack_counts(header)):
                qualifier = "понад " if re.search(rf"понад\s+{count}\b", header, re.I) else ""
                facts.append(f"Зведення {date_label}: {qualifier}{count} атак, {scope.group(0)}. "
                             "Окремий показник зі своїм періодом, навіть якщо число повторюється.")
        for sentence in re.split(r"(?<=[.!?])\s+", text):
            if re.search(r"критичн\w*\s+інфраструктур\w*", sentence, re.I):
                # Keep the actual object and location, not a generic keyword.
                facts.append("Обов'язково зберегти конкретний об'єкт і місце: " + sentence)
    return "\n".join("- " + fact for fact in dict.fromkeys(facts)) or "Окремих обов'язкових показників не виявлено."


def report_section(report, section):
    match = re.search(rf"(?ms)^{re.escape(section)}\.\s+(.*?)(?=^\d+\.\d+\.\s|^Це огляд|\Z)", report)
    return match.group(1) if match else ""


COMMUNITY_NAME = r"\b([А-ЯІЇЄҐ][а-яіїєґ’'-]+(?:ськ|цьк)(?:ій|ої|у|а|ою))\b"


def community_stems(text):
    return {re.sub(r"(?:ій|ої|у|а|ою)$", "", name.lower())
            for name in re.findall(COMMUNITY_NAME, text)}


PLACE_PATTERNS = {
    "Дніпро": r"\bдніпр(?:о|а|і|у|ом)\b",
    "Дніпровський район": r"\bдніпровськ\w*\s+район\w*",
    "Нікопольщина": r"\bнікопольщин\w*|\bнікопольськ\w*\s+район\w*",
    "Криворіжжя": r"\bкриворіж\w*|\bкриворізьк\w*\s+район\w*",
    "Синельниківський район": r"\bсинельниківськ\w*\s+район\w*",
    "Кривий Ріг": r"\bкрив(?:ий|ому|ого)\s+р(?:іг|озі|огу)\b",
    "Нікополь": r"\bнікопол(?:ь|і|я|ю|ем)\b",
    "Павлоград": r"\bпавлоград(?:і|а|у|ом)?\b",
}
MONTHS = "січня лютого березня квітня травня червня липня серпня вересня жовтня листопада грудня".split()
DATE_WORDS = r"\b(\d{1,2})\s+(" + "|".join(MONTHS) + r")\b"


def asserted_counts(text):
    # A named singular person is a casualty assertion even without a numeral.
    result = set()
    for sentence in re.split(r"[.!?;]", normalize(text)):
        if re.search(r"немає|не було|без\s+(?:загиблих|поранених)|уточню|можлив", sentence):
            continue
        result.update(casualty_counts(sentence))
        if re.search(r"\b(?:постраждала|поранена|госпіталізована|загинула)\s+(?:\d+-річна\s+)?жінка\b|"
                     r"\b(?:постраждав|поранений|госпіталізований|загинув)\s+(?:\d+-річний\s+)?чоловік\b|"
                     r"\b(?:жінка|чоловік|людина)\s+(?:дістала|дістав|отримала|отримав)\s+поран", sentence):
            result.add(1)
    return result


def place_casualty_problems(section, posts):
    records = {}
    for post in posts:
        text = post.get("text", "")
        dates = list(re.finditer(DATE_WORDS, text[:180], re.I))
        published = post.get("published_local", "")
        date = (int(dates[0][1]), MONTHS.index(dates[0][2].lower())+1) if dates else None
        if date is None:
            match = re.match(r"(\d{2})\.(\d{2})", published)
            if match:
                date = tuple(map(int, match.groups()))
        blocks = re.split(r"[▪●]\ufe0f?", text)
        for block in (blocks[1:] if len(blocks) > 1 else blocks):
            counts = asserted_counts(block)
            for name, pattern in PLACE_PATTERNS.items():
                if re.search(pattern, block, re.I):
                    records.setdefault((name, date), set()).update(counts)
    markers = sorted((m.start(), m.end(), name) for name, pattern in PLACE_PATTERNS.items()
                     for m in re.finditer(pattern, section, re.I))
    dates = list(re.finditer(DATE_WORDS, section, re.I))
    problems = []
    for index, (start, end, name) in enumerate(markers):
        stop = markers[index+1][0] if index+1 < len(markers) else len(section)
        segment = section[end:stop]
        # Community names also end a city/district scope. Existing community
        # checks handle their own counts; a list within its parent is kept.
        counts = asserted_counts(segment)
        if not counts:
            continue
        preceding = [m for m in dates if m.start() < start]
        date = (int(preceding[-1][1]), MONTHS.index(preceding[-1][2].lower())+1) if preceding else None
        known = [(key, values) for key, values in records.items() if key[0] == name]
        if not known:
            continue
        eligible = [values for (place, day), values in known if date is None or day is None or day == date]
        allowed = set().union(*eligible) if eligible else set()
        if counts - allowed:
            problems.append("casualties assigned to unsupported place/date: " + name)
    return problems


def transport_link_problems(report, posts):
    body = report_section(report, "1.2")
    sources = [p.get("text", "") for p in posts if p.get("category_hint") == "1.2"]
    mode_pattern = r"\b(?:трамва\w*|тролейбус\w*|автобус\w*)\s*№"

    def routes(text):
        markers = list(re.finditer(mode_pattern, text, re.I))
        result = set()
        for index, marker in enumerate(markers):
            kind = "трамвай" if marker[0].lower().startswith("трамва") else "тролейбус" if marker[0].lower().startswith("тролейбус") else "автобус"
            stop = markers[index+1].start() if index+1 < len(markers) else len(text)
            fragment = text[marker.start():stop]
            for match in re.finditer(r"№\s*(\d+(?:\s*[А-ЯІЇЄҐA-Z](?![а-яіїєґa-z]))?)", fragment):
                result.add((kind, re.sub(r"\s+", "", match[1]).upper()))
        return result

    # Learn street/bridge names and route identifiers from the current sources.
    # Ambiguous 'через Центральний міст' is a path, not a causal assertion.
    anchors = {}
    for source in sources:
        names = re.findall(r"(?:вул\.|вулиц\w*)\s+([А-ЯІЇЄҐ][\w’'-]*(?:\s+[А-ЯІЇЄҐIVX][\w’'-]*){0,3})", source)
        bridges = re.findall(r"\b([А-ЯІЇЄҐ][а-яіїєґ’'-]+)\s+(?:міст|мост)\w*", source)
        patterns = [re.escape(name.lower()) for name in names]
        for name in bridges:
            stem = re.sub(r"(?:ому|ого|ий|ім|ої|ій|а|у|е|і)$", "", name.lower())
            patterns.append(re.escape(stem) + r"\w*\s+(?:міст|мост)\w*")
        source_routes = routes(source) if re.search(r"ремонт|перекрит|аварі|обмеженн|пошкоджен", source, re.I) else set()
        for pattern in patterns:
            anchors.setdefault(pattern, set()).update(source_routes)
    problems = []
    for sentence in re.split(r"(?<=[.!?])\s+(?=[А-ЯІЇЄҐ])", body):
        if not re.search(r"(?:через|у зв['’]язку з|внаслідок)\s+(?:тимчасов\w*\s+)?(?:ремонт|перекрит|аварі|обмеженн|пошкоджен)", sentence, re.I):
            continue
        for pattern, supported in anchors.items():
            if re.search(pattern, sentence, re.I) and routes(sentence) - supported:
                problems.append("unsupported causal link between separate transport notices")
    return problems


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
        segment = section[end:stop]
        # An explicitly marked day/window total starts a new scope, rather
        # than extending the preceding community's event. Global count and
        # total-source checks below still apply to the entire section.
        summary = re.search(
            r"(?:^|(?<=[.!?])\s+)(?:загалом|усього|всього)\s+"
            r"(?:протягом дня|упродовж дня|за день|за добу|за звітний період)\b",
            segment, re.I)
        if summary:
            segment = segment[:summary.start()]
        counts = casualty_counts(segment)
        if counts - records[stem]:
            problems.append("casualties assigned to unsupported community: " + stem)
    return problems


def source_problems(report, posts):
    if any(len(re.findall(rf"(?m)^{re.escape(section)}\.\s", report)) > 1
           for section in ("1.1", "1.2", "1.3", "1.4", "2.1", "2.2", "2.3", "2.4")):
        return ["duplicate report sections; factual checks require an unambiguous structure"]
    problems = []
    attacks = [p for p in posts if p.get("category_hint") == "2.1"]
    attack_text = normalize(" ".join(p.get("text", "") for p in attacks))
    section21 = normalize(report_section(report, "2.1"))
    section11 = normalize(report_section(report, "1.1"))
    if attacks and "повідомлень за звітний період не виявлено" in section11:
        problems.append("overview denies available attack reports")
    problems.extend(casualty_location_problems(section21, attacks))
    problems.extend(place_casualty_problems(section21, attacks))
    problems.extend(transport_link_problems(report, posts))
    for sentence in re.split(r"(?<=[.!?])\s+", section21):
        if not re.search(r"\bтакож\b|\bще\b", sentence) or not asserted_counts(sentence):
            continue
        for name, pattern in PLACE_PATTERNS.items():
            match = re.search(pattern, sentence, re.I)
            if match and not re.search(DATE_WORDS, sentence, re.I):
                prior = section21[:section21.find(sentence)]
                prior_positive = False
                for previous in re.finditer(pattern, prior, re.I):
                    tail = prior[previous.end():]
                    boundaries = [m.start() for other in PLACE_PATTERNS.values()
                                  for m in re.finditer(other, tail, re.I)]
                    if asserted_counts(tail[:min(boundaries)] if boundaries else tail):
                        prior_positive = True
                if prior_positive:
                    problems.append("additional casualties need a distinct dated source episode: " + name)
    allowed_counts = set().union(*(casualty_counts(p.get("text", "")) for p in attacks))
    unsupported = casualty_counts(section21) - allowed_counts
    if unsupported:
        problems.append("unsupported casualty count: " + ", ".join(map(str, sorted(unsupported))))
    unsupported_attacks = attack_counts(section21 + " " + section11) - attack_counts(attack_text)
    if unsupported_attacks:
        problems.append("unsupported attack total")
    if attack_counts(section11):
        problems.append("attack counts belong in section 2.1 with their source periods")
    missing_counts = required_attack_counts(attacks) - attack_counts(section21)
    if missing_counts:
        problems.append("missing source attack counts in section 2.1: "
                        + ", ".join(map(str, sorted(missing_counts))))
    # Equal numbers from distinct district bulletins are not one fact.
    scopes = {}
    scope_pattern = rf"\b({NUMBER})\s+район\w*"
    for post in attacks:
        header = normalize(re.split(r"[▪●]", post.get("text", ""))[0])
        district = re.search(scope_pattern, header)
        if district:
            for count in attack_counts(header):
                scopes.setdefault(count, set()).add(number_value(district[1]))
    for count, districts in scopes.items():
        if len(districts) < 2:
            continue
        found = set()
        for sentence in re.split(r"[.!?;]", section21):
            if count in attack_counts(sentence):
                found.update(number_value(m[1]) for m in re.finditer(scope_pattern, sentence))
        if districts - found:
            problems.append("distinct attack bulletins with equal counts were collapsed")
    # Never manufacture a day/window total from separate source summaries.
    if explicit_casualty_totals(section21) - explicit_casualty_totals(attack_text):
        problems.append("casualty total not explicitly supported by source")
    for label, pattern in (("children", r"\bдіт\w*|\bдитин\w*"),):
        if re.search(pattern, section21) and not re.search(pattern, attack_text):
            problems.append("unsupported casualty/event detail: " + label)
    # Mentioning firefighters responding to a fire is not a claim that one
    # was injured. Check casualty assertions about the role, not the noun.
    rescuer_casualty = (
        r"(?:поранен\w*|травмован\w*|постраждав\w*|загинув\w*)\s+(?:(?:один|\d+)\s+)?рятувальник\w*"
        r"|серед\s+(?:поранених|постраждалих|загиблих)[^.!?;]{0,30}\bрятувальник\w*"
        r"|\bрятувальник\w*\s+(?:(?:дістав\w*|дістал\w*|отримав\w*|отримал\w*)\s+"
        r"(?:поран\w*|травм\w*)|був\s+поран\w*|поранен\w*|постраждав\w*|загинув\w*)"
    )
    if re.search(rescuer_casualty, section21) and not re.search(rescuer_casualty, attack_text):
        problems.append("unsupported casualty/event detail: rescuer")
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
        ("critical infrastructure", r"критичн\w*\s+інфраструктур\w*"),
    ):
        if re.search(pattern, attack_text) and not re.search(pattern, section21):
            problems.append("missing specific attack consequence: " + label)
    critical_posts = [p for p in attacks
                      if re.search(r"критичн\w*\s+інфраструктур\w*", normalize(p.get("text", "")))]
    if critical_posts:
        critical_source = normalize(" ".join(p.get("text", "") for p in critical_posts))
        # Do not let abbreviations such as "м." hide the chronological label.
        for label, source_period in (
            ("ніч", r"ніч|ночі|вночі|уночі"),
            ("ранок", r"ранок|вранці|зранку"),
            ("вечір", r"вечір|вечор|ввечері|увечері"),
        ):
            if (re.search(rf"\b\d{{1,2}}\s+[а-яіїєґ]+,\s*{label}\s*:"
                          r".{0,160}?критичн\w*\s+інфраструктур\w*", section21)
                and not re.search(source_period, critical_source)):
                problems.append("unsupported incident period: critical infrastructure")
    incident_clock_source = " ".join(
        re.sub(r"(?m)^\s*\d{1,2}:\d{2}\s*$", "", p.get("text", "")) for p in attacks)
    explicit_clocks = set(re.findall(r"\b\d{1,2}:\d{2}\b", incident_clock_source))
    for match in re.finditer(r"\b(?:о|близько)\s+(\d{1,2}:\d{2})\b", section21):
        after_clock = section21[match.end():match.end()+100]
        if match.group(1) not in explicit_clocks and re.search(r"атак|удар|обстріл|ворог", after_clock):
            problems.append("publication clock used as incident time: " + match.group(1))
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
- відділяй денний епізод від нічного навіть у тому самому місті: число поранених
  з наступної ночі не переноситься на попередній день. Число у вступі обласного
  зведення не належить кожному місту; перевір відповідний регіональний абзац;
- не вигадуй причинний зв'язок між окремими транспортними оголошеннями.
  Якщо причина зміни маршруту не вказана, подай її окремим повідомленням;
- позначене як cutoff_bulletin зведення з заголовком 08:00 є підсумком станом
  на межу вікна, опублікованим трохи пізніше. Врахуй його уточнення без додавання
  подій після 08:00. Слово «ще» у кількості зруйнованих будинків збережи:
  не підміняй ним раніше підтверджену кількість і не складай цифри самостійно;
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
- анонс на поточний день, опублікований до 08:00, не перетворюй на завершену
  подію до 08:00. Для погоди на день пиши «На [дату] прогнозуються...».
  Не пиши «до кінця звітного періоду», якщо попередження стосується дня після 08:00;
- чинні зміни руху передавай як чинні: «рух призупинено», «автобуси працюють»,
  «зупинку перенесено». Минулий час, який означає завершення обмежень,
  використовуй лише за прямим повідомленням про їх скасування або закінчення;
- у 2.1 відокремлюй денний і нічний періоди явними датами та короткими реченнями.
  Назви громади як частину району («у ... громаді ... району»), а не як додаткову
  окрему територію («у районі та громаді»). Не об’єднуй усі райони в одне довге речення;
- у 1.1 не повторюй ту саму думку другим реченням із переліком уже згаданих районів.
"""
