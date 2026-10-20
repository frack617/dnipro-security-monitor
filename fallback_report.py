"""Conservative prose from collected text, without generative API calls.

Only exact repetitions are removed. Uncertain updates are not added together
or assumed to be the same attack just because their locations match.
"""
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from report_rules import DATE_WORDS, MONTHS, NUMBER, PLACE_PATTERNS, asserted_counts, normalize
from report_sections import clean_transport_notice, source_transport_notices


EMPTY = "У перевірених джерелах повідомлень за звітний період не виявлено."
WEATHER = re.compile(r"гроз|туман|ожелед|погод|шторм|видиміст", re.I)
SERVICE = re.compile(r"гпв|відключен|електропостач|водопостач|теплопостач", re.I)
SIGNOFF = re.compile(
    r"^(?:деталі\s*[—:.-]?\s*$|будьте уважні|будьте обережні|"
    r"інформує департамент|розклад руху\s*$|електротранспорту на сайті\s*$)", re.I)
PERSONAL = re.compile(
    r"^(?:виїхав\w*|поспілкував\w*|дяку\w*|вручив\w*|побував\w*|"
    r"обговор\w*|усім постраждалим допомагатимемо|"
    r"після необхідних обстежень.*(?:заявки|компенсац))\b", re.I)


def sentences(text):
    # A street/city abbreviation is not a sentence boundary.
    protected = re.sub(r"\b(м|вул|пл|обл|ім|ст|пров|просп)\.", lambda m: m[1]+"\u2024", text, flags=re.I)
    return [s.replace("\u2024", ".").strip() for s in
            re.split(r"(?<=[.!?])\s+(?=[А-ЯІЇЄҐ0-9])", protected) if s.strip()]


def clean_lines(text):
    from groq_report import clean_source_text
    result = []
    for line in text.splitlines():
        if line.strip().startswith(".") and result and result[-1][-1] not in ".!?;:":
            result[-1] += "."
        cleaned = clean_source_text(line).strip()
        if re.fullmatch(r"[,;:]", line.strip()) and result:
            result[-1] += line.strip()
            continue
        if not re.search(r"[А-Яа-яІіЇїЄєҐґ0-9]", cleaned) or SIGNOFF.search(cleaned):
            continue
        result.append(cleaned)
    return re.sub(r"\s+([.,;:])", r"\1", " ".join(result)).strip()


def unique_texts(texts):
    seen = set()
    result = []
    for text in texts:
        key = re.sub(r"\W+", " ", text.lower()).strip()
        if key and key not in seen:
            seen.add(key)
            result.append(text)
    return result


def clean_event(post):
    blocks = re.split(r"[▪●]\ufe0f?", post.get("text", ""))
    cleaned_blocks = []
    locations = [name for name, pattern in PLACE_PATTERNS.items()
                 if re.search(pattern, post.get("text", ""), re.I)]
    removed_location = False
    for block in blocks:
        kept = []
        for sentence in sentences(clean_lines(block)):
            concrete = (re.search(rf"\b{NUMBER}\b", sentence, re.I)
                        and re.search(r"поран|загин|загиб|зруйн|пошкодж|госпітал|врят|евакуй", sentence, re.I))
            concrete = concrete or re.search(r"поранен\w*\s+(?:жін\w*|чоловік\w*|дитин\w*)", sentence, re.I)
            if PERSONAL.search(sentence) and not concrete:
                # Do not lose the only explicit location with a removed visit.
                if len(locations) == 1:
                    removed_location |= any(re.search(pattern, sentence, re.I)
                        for name, pattern in PLACE_PATTERNS.items() if name in locations)
                elif any(re.search(pattern, sentence, re.I) for pattern in PLACE_PATTERNS.values()):
                    kept.append(sentence)
                continue
            kept.append(sentence)
        text = " ".join(unique_texts(kept))
        text = re.sub(r"\bІнформацію про ([^.!?]+) уточнюємо\.?",
                      lambda m: "Інформація про " + m[1] + " уточнювалася.", text)
        if text:
            cleaned_blocks.append(text)
    if not cleaned_blocks:
        return clean_lines(post.get("text", ""))
    header = cleaned_blocks[0]
    # Remove a duplicated regional opening count only when the sole casualty
    # block explicitly repeats that same count (including 'постраждала жінка').
    if len(blocks) > 1:
        date = re.search(DATE_WORDS, header, re.I)
        label = date.group(0) if date else None
        morning = bool(re.search(r"\b0?8:00\b", header))
        if label:
            header = re.sub(r"^.*?" + re.escape(label) + r"\s*(?:\d{1,2}:\d{2}\s*)?", "", header).strip()
        people = [b for b in cleaned_blocks[1:] if asserted_counts(b)]
        if len(people) == 1 and asserted_counts(header) == asserted_counts(people[0]):
            header = " ".join(s for s in sentences(header) if not asserted_counts(s))
        if label:
            prefix = "За ранковим зведенням станом на 08:00 " if morning else "За зведенням "
            header = prefix + label + ": " + header
        cleaned_blocks[0] = header
    result = " ".join(unique_texts(cleaned_blocks))
    if removed_location and not any(re.search(PLACE_PATTERNS[name], result, re.I) for name in locations):
        result = locations[0] + ": " + result
    return result.strip()


def publication_date(post):
    try:
        return datetime.fromisoformat(post["published_at"].replace("Z", "+00:00")).astimezone(ZoneInfo("Europe/Kyiv")).date()
    except (KeyError, ValueError, TypeError):
        try:
            return datetime.strptime(post.get("published_local", "")[:10], "%d.%m.%Y").date()
        except ValueError:
            return None


def weather_expired(post, end_date):
    text = normalize(post.get("text", ""))
    published = publication_date(post)
    dates = []
    for match in re.finditer(DATE_WORDS, text):
        try:
            year = published.year if published else end_date.year
            candidate = datetime(year, MONTHS.index(match[2])+1, int(match[1])).date()
            if published and candidate < published-timedelta(days=180):
                candidate = candidate.replace(year=year+1)
            elif published and candidate > published+timedelta(days=180):
                candidate = candidate.replace(year=year-1)
            dates.append(candidate)
        except ValueError:
            pass
    if not dates and published and re.search(r"сьогодні|завтра|впродовж дня|упродовж дня|протягом дня", text):
        dates = [published + timedelta(days=1) if "завтра" in text else published]
    if not dates:
        return None
    latest = max(dates)
    if latest < end_date:
        return True
    if latest > end_date:
        return False
    end_words = f"{end_date.day} {MONTHS[end_date.month-1]}"
    night = re.search(r"(?:вночі|уночі|у ніч на|в ніч на)\s*" + re.escape(end_words), text)
    if not night and published == end_date:
        night = re.search(r"сьогодні\s+(?:вночі|уночі)", text)
    if not night and published and published+timedelta(days=1) == end_date:
        night = re.search(r"завтра\s+(?:вночі|уночі)", text)
    # A daytime warning for the report date remains a future risk.
    daytime = re.search(r"(?:впродовж|упродовж|протягом)\s+дня|вдень|удень", text)
    return bool(night) and not bool(daytime)


def weather_text(post, end_date):
    lines = post.get("text", "").splitlines()
    # Repeated banner titles do not carry warning validity or severity.
    lines = [s for s in lines if not (s.strip().isupper() and WEATHER.search(s)
                                     and not re.search(r"\d|рівень", s, re.I))]
    text = clean_lines("\n".join(lines))
    text = re.sub(r"\s*[-–—]\s*інформує[^.!?]+", "", text, flags=re.I)
    published = publication_date(post)
    if published:
        date_words = f"{published.day} {MONTHS[published.month-1]}"
        text = re.sub(r"сьогодні\s+(?:вночі|уночі)", "у ніч на " + date_words, text, flags=re.I)
        text = re.sub(r"\bсьогодні\b", "на " + date_words, text, flags=re.I)
        tomorrow = published+timedelta(days=1)
        tomorrow_words = f"{tomorrow.day} {MONTHS[tomorrow.month-1]}"
        text = re.sub(r"завтра\s+(?:вночі|уночі)", "у ніч на " + tomorrow_words, text, flags=re.I)
        text = re.sub(r"\bзавтра\b", "на " + tomorrow_words, text, flags=re.I)
    if weather_expired(post, end_date) is True:
        for before, after in (("прогнозуються", "прогнозувалися"),
                              ("очікуються", "очікувалися"),
                              ("передбачаються", "передбачалися")):
            text = re.sub(r"\b"+before+r"\b", after, text, flags=re.I)
        feminine = bool(re.search(r"\bгроза\b|\bожеледиця\b", text, re.I))
        for before, male, female in (("прогнозується", "прогнозувався", "прогнозувалася"),
                                      ("очікується", "очікувався", "очікувалася")):
            text = re.sub(r"\b"+before+r"\b", female if feminine else male, text, flags=re.I)
        date = r"\d{1,2}\s+(?:" + "|".join(MONTHS) + ")"
        text = re.sub(r"^У найближчу годину\s+("+date+r")\s+та\s+вночі\s+("+date+r")\s+",
                      lambda m: "Попередження від " + m[1] + " на найближчу годину та ніч на " + m[2] + ": ", text, flags=re.I)
    text = re.sub(r"(?<=[.!?])\s+гроза\b", " Гроза", text)
    return text


def build_sections(groups, end_date):
    result = {}
    for section, posts in groups.items():
        if section == "1.2":
            texts = unique_texts(source_transport_notices(posts))
            result[section] = " Окремо: ".join(texts) if texts else EMPTY
        elif section == "1.4":
            texts = unique_texts(weather_text(p, end_date) if WEATHER.search(p.get("text", ""))
                                and not SERVICE.search(p.get("text", "")) else clean_event(p) for p in posts)
            result[section] = " ".join(texts) if texts else EMPTY
        elif section == "2.1":
            from attack_digest import grouped_attack_text
            result[section] = grouped_attack_text(posts) if posts else EMPTY
        else:
            seen = set()
            texts = []
            for post in posts:
                text = clean_event(post)
                key = (publication_date(post), normalize(text))
                if text and key not in seen:
                    texts.append(text)
                    seen.add(key)
            result[section] = " ".join(texts) if texts else EMPTY
    return result


def source_weather_normalization(report, posts, end_date_label):
    services = [p for p in (posts or []) if p.get("category_hint") == "1.4"]
    if len(services) != 1 or not WEATHER.search(services[0].get("text", "")) or SERVICE.search(services[0].get("text", "")):
        return report
    end = datetime.strptime(end_date_label, "%d.%m.%Y").date()
    if weather_expired(services[0], end) is None:
        return report
    # Use an unambiguous dated weather notice rather than guessing the validity
    # of a model's undated warning. Other service paragraphs are never replaced.
    text = weather_text(services[0], end)
    if not text:
        return report
    result = re.sub(r"(?ms)^1\.4\.\s+.*?(?=^2\.\s+Події:)",
                    lambda _: "1.4. " + text + "\n\n", report)
    if result != report:
        print("Source-based weather validity normalization applied: section 1.4")
    return result


def brief_transport(posts):
    """Keep restoration and current notices, removing explicitly ended routes.

    A direct reply can supersede only the routes it actually restores. Other
    clauses, streets and unrelated restrictions in the old post are retained.
    """
    from transport_state import restored_routes, transport_routes
    ordered = sorted(posts, key=lambda p: p.get('published_at', ''))
    by_key = {p.get('key'): p for p in ordered if p.get('key')}
    ended = {}
    for post in ordered:
        target = by_key.get(post.get('reply_to'))
        if (target and target.get('channel') == post.get('channel')
                and target.get('published_at', '') < post.get('published_at', '')):
            routes = restored_routes(post.get('text', ''))
            if routes:
                ended.setdefault(target['key'], set()).update(routes)
    texts = []
    for post in ordered:
        text = clean_transport_notice(post)
        day = publication_date(post)
        if day:
            # A reserve can cover two calendar dates; "today" must not shift
            # yesterday's completed announcement to the report date.
            label = str(day.day) + ' ' + MONTHS[day.month-1]
            text = re.sub(r'\bСьогодні,?\s*' + re.escape(label) + r',?', label, text, flags=re.I)
            text = re.sub(r'\bсьогодні\b', label, text, flags=re.I)
            text = text.replace('закінчать свою роботу раніше', 'за анонсом мали закінчити роботу раніше')
        if post.get('key') in ended:
            clauses = [c for sentence in sentences(text)
                       for c in re.split(r'(?<=;)\s+', sentence)]
            text = ' '.join(c for c in clauses
                            if not (transport_routes(c) and
                                    transport_routes(c) <= ended[post['key']]))
            text = re.sub(r'^Оновлена інформація[^:]*:\s*', '', text).strip()
        if text:
            texts.append(text)
    return ' '.join(unique_texts(texts)) or EMPTY


def brief_attacks(posts):
    """Use latest dated official regional bulletins as the fallback backbone.

    This deliberately labelled summary is not the full chronological feed.
    Single alerts remain when no regional bulletin exists for that date.
    The source's regional totals and locality paragraphs are never reassigned.
    """
    ordered = sorted(posts, key=lambda p: p.get('published_at', ''))
    bulletins = {}
    for post in ordered:
        text = post.get('text', '')
        if (post.get('channel', '').lower() in {'adm_dp', 'dnipropetrovskaoda'}
                and re.search(r'Дніпропетровщина\s*\n\s*'+DATE_WORDS, text, re.I)
                and len(re.split(r'[▪●]', text)) >= 3):
            bulletins[publication_date(post)] = post
    if not bulletins:
        return build_sections({'2.1': posts}, datetime.now().date())['2.1']
    selected = []
    for post in ordered:
        latest = bulletins.get(publication_date(post))
        critical = re.search(r'критичн\w*\s+інфраструктур\w*', post.get('text', ''), re.I)
        if (latest is None or post is latest or
                (critical and not re.search(r'критичн\w*\s+інфраструктур\w*', latest['text'], re.I))):
            selected.append(post)
    # Preserve the original bulletin blocks and their geographic scopes.
    result = []
    for post in selected:
        body = clean_event(post)
        # Operational instructions in yesterday's alert are not a live alert.
        body = ' '.join(s for s in sentences(body) if not re.match(
            r'Залишайтеся\b|Загроза триває\b|До відбою\b', s, re.I))
        body = re.sub(r'\bВорог атакує\b', 'Ворог атакував', body)
        result.append(body)
    return '\n\n'.join(unique_texts(result))


def build_brief_sections(groups, end_date):
    """Bound the reserve's editorial scope instead of publishing raw history."""
    result = build_sections(groups, end_date)
    if groups.get('1.2'):
        result['1.2'] = brief_transport(groups['1.2'])
    if groups.get('2.1'):
        result['2.1'] = brief_attacks(groups['2.1'])
    if groups.get('1.4'):
        result['1.4'] = '\n\n'.join(unique_texts(brief_service(p, end_date) for p in groups['1.4']))
    return result


def brief_service(post, end_date):
    """Summarize address lists as named streets; keep queues with their streets."""
    text = post.get('text', '')
    if re.search(r'плануємо відновити електропостачання', text, re.I):
        plan = next((s for s in sentences(clean_lines(text))
                     if re.search(r'плануємо відновити електропостачання', s, re.I)), None)
        city = re.search(r'\bм\.\s*([А-ЯІЇЄҐ][А-Яа-яІіЇїЄєҐґ’\'-]+)', text)
        if plan and city:
            day = publication_date(post)
            prefix = ('У повідомленні від ' + str(day.day) + ' ' + MONTHS[day.month-1] + ' ') if day else ''
            return city[1] + ': ' + prefix + re.sub(r'^Плануємо', 'енергетики планували', plan)
    if WEATHER.search(text) and not SERVICE.search(text):
        return weather_text(post, end_date)
    if not re.search(r'знеструмлен|переводяться до графіка|припинено подачу електроенергії', text, re.I):
        return clean_event(post)
    # The named streets are copied, not an invented district or a guessed
    # outage duration. Full house lists remain in report_input and the archive.
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    location_matches = list(re.finditer(r'\b(?:м\.|с\.)\s*([А-ЯІЇЄҐ][А-Яа-яІіЇїЄєҐґ’\'-]+)', text))
    locations = [m[1] for m in location_matches]
    streets = re.findall(r'(?:вул\.|пр-т\.|бульвар|проїзд)\s+[^:\n]+(?=:)', text)
    if not streets:
        return clean_event(post)
    label = ', '.join(unique_texts(locations))
    if not label:
        return clean_event(post)
    if len(location_matches) > 1:
        period = re.search(r'\b(\d{1,2}\s+(?:'+ '|'.join(MONTHS) + r'))\s+з\s+(\d{1,2}:\d{2})\s+до\s+(\d{1,2}:\d{2})', text, re.I)
        prefix = ('Анонсовано відключення ' + period[1] + ' з ' + period[2] + ' до ' + period[3] + ': ') if period else ''
        parts = []
        for index, match in enumerate(location_matches):
            stop = location_matches[index+1].start() if index+1 < len(location_matches) else len(text)
            chunk = text[match.end():stop]
            names = re.findall(r'(?:вул\.|пр-т\.|бульвар|проїзд)\s+[^:\n]+(?=:)', chunk)
            if not names:
                return clean_event(post)
            parts.append(match[1] + ': ' + ', '.join(unique_texts(names)))
        return prefix + '; '.join(parts) + '.'
    queues = re.findall(r'підчерги\s+(\d+\.\d+)', text)
    if queues:
        groups = []
        start = 0
        for match in re.finditer(r'підчерги\s+(\d+\.\d+)', text):
            chunk = text[start:match.start()]
            names = re.findall(r'(?:вул\.|пр-т\.|бульвар|проїзд)\s+[^:\n]+(?=:)', chunk)
            if not names:
                return clean_event(post)
            groups.append(', '.join(unique_texts(names)) + ' — підчерга ' + match[1])
            start = match.end()
        return label + ': змінено підчерги для окремих адрес: ' + '; '.join(groups) + '.'
    action = ('Анонсовано припинення електропостачання' if 'припинено подачу' in text.lower()
              else 'Повідомлено про знеструмлення')
    return label + ': ' + action[:1].lower() + action[1:] + ' за адресами на ' + ', '.join(unique_texts(streets)) + '.'
