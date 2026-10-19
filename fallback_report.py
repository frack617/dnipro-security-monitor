"""Conservative prose from collected text, without generative API calls.

Only exact repetitions are removed. Uncertain updates are not added together
or assumed to be the same attack just because their locations match.
"""
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from report_rules import DATE_WORDS, MONTHS, NUMBER, PLACE_PATTERNS, asserted_counts, normalize
from report_sections import clean_transport_notice


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
    protected = re.sub(r"\b(м|вул|пл|обл|ім|ст)\.", lambda m: m[1]+"\u2024", text, flags=re.I)
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
            texts = unique_texts(clean_transport_notice(p) for p in posts)
            result[section] = " Окремо: ".join(texts) if texts else EMPTY
        elif section == "1.4":
            texts = unique_texts(weather_text(p, end_date) if WEATHER.search(p.get("text", ""))
                                and not SERVICE.search(p.get("text", "")) else clean_event(p) for p in posts)
            result[section] = " ".join(texts) if texts else EMPTY
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
