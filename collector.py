#!/usr/bin/env python3
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
POSTS_FILE = DATA_DIR / "posts.json"
LATEST_FILE = DATA_DIR / "latest.md"
REPORT_INPUT_FILE = DATA_DIR / "report_input.md"
STATUS_FILE = DATA_DIR / "status.json"
ALERT_STATE_FILE = DATA_DIR / "alert_state.json"
MORNING_REPORT_FILE = DATA_DIR / "morning_report.md"
CHANNELS_FILE = ROOT / "channels.txt"

LOOKBACK_HOURS = int(os.getenv("LOOKBACK_HOURS", "72"))
KEEP_HOURS = int(os.getenv("KEEP_HOURS", "72"))
MAX_PAGES = int(os.getenv("MAX_PAGES", "12"))
PARSER_VERSION = 2
KYIV = ZoneInfo("Europe/Kyiv")

LOCAL_CHANNELS = {
    "adm_dp", "dniprocityofficial", "gunpvdp", "cek_info",
    "borys_filatovv", "dnipropetrovskaoda",
}
REGION_TERMS = (
    "дніпр", "кривий ріг", "нікопол", "павлоград", "кам’янськ", "кам'янськ",
    "синельник", "марган", "покров", "новомосков", "самар", "першотравен",
    "шахтарськ", "тернівк", "жовті води", "апостолов", "зеленодоль",
    "межів", "васильків", "петропавлів",
)
ALERT_TERMS = (
    "ракетна атака", "ракетний удар", "атака бпла", "ворожа атака", "обстріл",
    "влучання", "загинув", "загинули", "поранен", "руйнуван", "евакуац",
    "надзвичайна ситуація", "масштабна пожежа", "аварійне відключення",
    "екстрене відключення", "перекрито рух", "замінуван", "вибухівк",
    "диверсі", "коригувальник",
)

ATTACK_TERMS = (
    "обстріл", "атак", "ворожа атака",
    "ракетний удар", "ракетна атака", "ударний безпілотник", "бпла",
    "шахед", "влучання", "ворог завдав удару", "завдав ударів", "завдали удар",
)
ROAD_TERMS = (
    "перекрито рух", "перекриття руху", "обмежено рух", "обмеження руху",
    "зміни у русі", "тимчасово не курсуват", "змінено маршрут",
    "призупиняється рух", "кінцева зупинка", "перекриття проїзної частини",
    "ремонт колії", "змін у русі", "курсує за скороченим маршрутом",
)
BLAST_WORK_TERMS = (
    "планові вибух", "вибухові роботи", "контрольований вибух",
    "буде чутно вибух", "можна почути вибух",
)
SERVICE_TERMS = (
    "аварійне відключення", "екстрене відключення", "відсутнє водопостачання",
    "припинено водопостачання", "теплопостачання", "знеструмлен",
    "масштабна пожежа", "аварія на", "затримка руху", "не курсуватиме",
    "туман", "видимість", "погодинні відключення", "графік відключень",
    "відключення електроенергії",
    "гпв", "графіки відключення", "відключення світла",
    "обмеження електропостачання", "відключення наступних черг",
    "гроза", "гроз", "рівень небезпечності", "штормове попередження",
)
WEAPON_TERMS = ("збро", "гранат", "вибухівк", "боєприпас")
ENFORCEMENT_TERMS = ("незакон", "вилуч", "затрим", "підозр", "обшук", "збут")
NON_WEAPON_CRIME_TERMS = (
    "вбивств", "наркотик", "наркозб", "психотроп", "метадон", "канабіс",
)
MINING_TERMS = ("замінуван", "псевдомінув", "повідомлення про мінування")
UXO_TERMS = (
    "вибухонебезпечн", "нерозірван", "боєприпас", "бойова частина",
    "бойову частину", "бойової частини", "небезпечного предмета",
)
DISCOVERY_TERMS = ("виявил", "знайшл", "знешкодил", "знищил", "вилучил")
NON_EVENT_CONTEXT_TERMS = (
    "триває відновлення", "відбудов", "відновлення житлов",
    "з візитом прибу", "робочий візит", "прибула делегація",
    "обговорили співпрацю", "війна не поставила на паузу",
    "карта орієнтовного руху",
)
UA_MONTHS = {
    "січня": 1,
    "лютого": 2,
    "березня": 3,
    "квітня": 4,
    "травня": 5,
    "червня": 6,
    "липня": 7,
    "серпня": 8,
    "вересня": 9,
    "жовтня": 10,
    "листопада": 11,
    "грудня": 12,
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 16) AppleWebKit/537.36 "
        "Chrome/155.0 Mobile Safari/537.36"
    ),
    "Accept-Language": "uk-UA,uk;q=0.9,en;q=0.7",
    "Cache-Control": "no-cache",
}


def utc_now():
    return datetime.now(timezone.utc)


def parse_datetime(value):
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def load_channels():
    return [
        line.strip().lstrip("@")
        for line in CHANNELS_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def fetch(url, session):
    response = session.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    return response.text


def own_message_nodes(message, selector):
    result = []
    excluded = {"tgme_widget_message_reply", "tgme_widget_message_link_preview"}
    for candidate in message.select(selector):
        own = True
        for ancestor in [candidate, *candidate.parents]:
            if ancestor is message:
                break
            classes = set(ancestor.get("class", []))
            if classes & excluded or "tgme_widget_message" in classes:
                own = False
                break
        if own:
            result.append(candidate)
    return result


def parse_page(channel, html):
    soup = BeautifulSoup(html, "html.parser")
    posts = []

    for node in soup.select(".tgme_widget_message[data-post]"):
        if node.find_parent(class_="tgme_widget_message") is not None:
            continue
        data_post = node.get("data-post", "")
        if "/" not in data_post:
            continue

        post_channel, post_id_text = data_post.rsplit("/", 1)
        if not post_id_text.isdigit():
            continue

        own_times = own_message_nodes(node, "time[datetime]")
        time_node = own_times[0] if own_times else None
        published_at = time_node.get("datetime") if time_node else None
        published_dt = parse_datetime(published_at)
        if published_dt is None:
            continue

        text_nodes = own_message_nodes(node, ".tgme_widget_message_text")
        text = "\n".join(n.get_text("\n", strip=True) for n in text_nodes) if text_nodes else "[Медіа без тексту]"
        text = re.sub(r"[ \t]+", " ", text).strip()

        post_id = int(post_id_text)
        post = {
                "key": f"{post_channel}/{post_id}",
                "channel": post_channel or channel,
                "post_id": post_id,
                "published_at": published_dt.isoformat(),
                "url": f"https://t.me/{post_channel}/{post_id}",
                "text": text,
            }
        for reply in node.select("a.tgme_widget_message_reply[href]"):
            if reply.find_parent(class_="tgme_widget_message") is not node:
                continue
            match = re.fullmatch(r"https?://t\.me/([A-Za-z0-9_]+/\d+)(?:[?#].*)?", reply["href"])
            if match:
                post["reply_to"] = match[1]
                break
        posts.append(post)

    return posts


def collect_channel(channel, session, cutoff):
    collected = {}
    before = None
    visited = set()

    for _ in range(MAX_PAGES):
        url = f"https://t.me/s/{channel}"
        if before is not None:
            url += f"?before={before}"

        page_posts = parse_page(channel, fetch(url, session))
        if not page_posts:
            break

        signature = tuple(sorted(post["post_id"] for post in page_posts))
        if signature in visited:
            break
        visited.add(signature)

        for post in page_posts:
            collected[post["key"]] = post

        oldest = min(parse_datetime(post["published_at"]) for post in page_posts)
        smallest_id = min(post["post_id"] for post in page_posts)
        if oldest <= cutoff:
            break

        before = smallest_id
        time.sleep(0.8)

    return list(collected.values())


def read_existing():
    if not POSTS_FILE.exists():
        return []
    try:
        posts = json.loads(POSTS_FILE.read_text(encoding="utf-8"))
        return posts if isinstance(posts, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def read_alert_state():
    if not ALERT_STATE_FILE.exists():
        return {"initialized": False, "alerted_keys": []}
    try:
        state = json.loads(ALERT_STATE_FILE.read_text(encoding="utf-8"))
        return state if isinstance(state, dict) else {"initialized": False, "alerted_keys": []}
    except (OSError, json.JSONDecodeError):
        return {"initialized": False, "alerted_keys": []}


def send_bot_message(text):
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        return False
    response = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": True,
        },
        timeout=30,
    )
    response.raise_for_status()
    if response.json().get("ok") is not True:
        raise RuntimeError("Telegram did not confirm message delivery")
    return True


def is_background_notice(text):
    if contains_any(text, NON_EVENT_CONTEXT_TERMS):
        return True
    # A cultural announcement can mention attacks/evacuation as the subject
    # of an exhibition. Those nouns alone do not establish a new incident.
    # Keep mixed notices if they explicitly report an attack or casualties.
    opening = re.sub(r"\s+", " ", text[:350])
    cultural = re.search(
        r"\b(?:відкрили|відкрито|відкрилася|відкрилась|відкриється|відкривають)\b"
        r"[^.!?]{0,100}\b(?:фотовистав\w*|вистав\w*|експозиці\w*)", opening)
    if not cultural:
        return False
    direct_event = re.search(
        r"\b(?:ворог|росіяни|окупанти|війська\s+рф)\s+"
        r"(?:\w+\s+){0,3}(?:атак\w*|вдар\w*|завда\w*)|"
        r"\b(?:внаслідок|унаслідок|через)\s+(?:\w+\s+){0,3}"
        r"(?:атак\w*|обстріл\w*|удар\w*)[^.!?]{0,120}"
        r"(?:пошкодж\w*|зруйн\w*|постражд\w*)|"
        r"\b(?:поранен\w*|загину\w*|госпіталізован\w*)", text)
    return not direct_event


def has_stopped_route(text):
    # An explicit completed suspension of a numbered public route is a
    # practical disruption. Do not treat every route timetable as an alert.
    return bool(re.search(
        r"\b(?:автобус|тролейбус|трамвай)\w*\s*№\s*\d+[а-яіїєґa-z]*\s+"
        r"(?:(?:тимчасово|повністю)\s+)?(?:призупини[вл]\w*|припини[вл]\w*)\s+"
        r"(?:свою\s+)?роботу\b", text))


def is_resonant(post):
    text = post.get("text", "").lower()
    if not is_regional(post) or is_background_notice(text):
        return False
    if re.search(r"президент|головком|перемир|дипломат", text) and not re.search(
        r"дніпропетров|\bдніпр(?:о|і|у)\b|нікопол|синельник|криворі", text):
        return False
    # Inflections such as «атакував» and «завдали удару» were absent from
    # ALERT_TERMS, silently dropping actual attacks even during regular polls.
    attack = classify_post(post) == "2.1" and bool(re.search(
        r"ворог|ворож\w*|росіян|російськ|\bрф\b|окупант|загарбник|влучання|обстріл", text))
    # Unscheduled utility faults may be described without «аварійне
    # відключення». Require an explicit causal statement, not merely a
    # mention of equipment, scheduled outages or a hypothetical risk.
    outage = bool(re.search(r"технологічн\w*\s+порушенн\w*", text) and re.search(
        r"(?<!не )\bспричинил[оаи]\s+знеструмлен\w*", text))
    from transport_state import restored_routes
    return attack or outage or has_stopped_route(text) or bool(restored_routes(text)) or contains_any(text, ALERT_TERMS)


def save_alert_state(state):
    ALERT_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = ALERT_STATE_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(ALERT_STATE_FILE)


def process_alerts(new_posts, checked_at, previous_checked_at=None, recovered_keys=()):
    if os.getenv("SEND_OPERATIONAL_ALERTS", "true").lower() not in {"1", "true", "yes"}:
        print("Operational alerts dry run: Telegram sending disabled; delivery state unchanged")
        return
    state = read_alert_state()
    alerted = set(state.get("alerted_keys", []))
    configured = bool(os.getenv("TELEGRAM_BOT_TOKEN", "").strip()) and bool(
        os.getenv("TELEGRAM_CHAT_ID", "").strip()
    )
    if not configured:
        return

    if not state.get("initialized"):
        send_bot_message(
            "✅ Моніторинг офіційних каналів Дніпропетровщини активовано. "
            "Оперативні повідомлення надходитимуть сюди; ранкова довідка "
            "формуватиметься окремо."
        )
        state["initialized"] = True

    cursor = parse_datetime(state.get("last_alert_scan_at")) or previous_checked_at
    recent_after = max(checked_at - timedelta(hours=KEEP_HOURS),
                       cursor - timedelta(hours=2) if cursor else checked_at - timedelta(hours=2))
    # Called with the entire retained buffer, so a failed send remains pending
    # even after its post has already been saved in posts.json.
    fingerprints = {re.sub(r"\W+", " ", p.get("text", "").lower()).strip()
                    for p in new_posts if p["key"] in alerted}
    recovered_keys = set(recovered_keys)
    pending = set(state.get("pending_alert_keys", [])) | recovered_keys
    failures = []
    sent = 0
    for post in sorted(new_posts, key=lambda item: item["published_at"]):
        if post["key"] in alerted or (parse_datetime(post["published_at"]) < recent_after
                                      and post["key"] not in pending):
            continue
        if not is_resonant(post):
            continue
        if is_historical_context(post, recent_after.astimezone(KYIV)):
            continue
        fingerprint = re.sub(r"\W+", " ", post.get("text", "").lower()).strip()
        if fingerprint in fingerprints:
            alerted.add(post["key"])
            continue
        local_time = parse_datetime(post["published_at"]).astimezone(KYIV)
        excerpt = post["text"][:2500]
        delayed = ("Уточнення після виправлення читання допису.\n" if post['key'] in recovered_keys else
                   "Надіслано після перерви в перевірках.\n"
                   if checked_at - parse_datetime(post["published_at"]) > timedelta(hours=2) else "")
        try:
            delivered = send_bot_message(
                "⚠️ Оперативне повідомлення щодо Дніпропетровщини\n\n"
                + delayed +
                f"Джерело: @{post['channel']}\n"
                f"Час публікації: {local_time.strftime('%d.%m.%Y %H:%M')} за Києвом\n\n"
                f"{excerpt}\n\n{post['url']}"
            )
            if not delivered:
                raise RuntimeError("Telegram sending unavailable")
        except (requests.RequestException, RuntimeError, ValueError) as error:
            failures.append(post["key"])
            print(f"Operational send failed: {post['key']} ({type(error).__name__})")
            continue
        alerted.add(post["key"])
        fingerprints.add(fingerprint)
        sent += 1
        state["alerted_keys"] = sorted(alerted)
        save_alert_state(state)

    keep_keys = {
        post["key"] for post in new_posts
        if parse_datetime(post["published_at"]) >= checked_at - timedelta(hours=KEEP_HOURS)
    }
    state["alerted_keys"] = sorted(alerted & keep_keys)
    if not failures:
        state["last_alert_scan_at"] = checked_at.isoformat()
    state["pending_alert_keys"] = failures
    save_alert_state(state)
    print(f"Operational scan: sent={sent} failed={len(failures)} since={recent_after.isoformat()}")
    return failures


def completed_report_window(checked_at):
    local_now = checked_at.astimezone(KYIV)
    today_at_eight = local_now.replace(hour=8, minute=0, second=0, microsecond=0)
    end_local = today_at_eight if local_now >= today_at_eight else today_at_eight - timedelta(days=1)
    start_local = end_local - timedelta(days=1)
    return (
        start_local,
        end_local,
        start_local.astimezone(timezone.utc),
        end_local.astimezone(timezone.utc),
    )


def is_regional(post):
    channel = post.get("channel", "").lower()
    text = post.get("text", "").lower()
    # «Дніпровський район» alone can be a district of Kyiv. Ambiguous names
    # in national feeds cannot establish a connection to this oblast.
    explicit = re.search(r"дніпропетров|\bдніпр(?:о|і|а|у|ом)\b|криворі|крив(?:ий|ому|ого)\s+р(?:іг|озі|огу)|нікопол|синельник|павлоград", text)
    if explicit:
        return True
    if re.search(r"\bкиїв\w*|\bстолиц\w*|\bдеснянськ\w*|\bсолом['’]янськ\w*", text):
        return False
    if channel in LOCAL_CHANNELS:
        return True
    return bool(re.search(r"марганц|марганец|апостолов|зеленодоль|жовт[іих]+\s+вод", text))


def is_cutoff_bulletin(post, boundary_local):
    published = parse_datetime(post.get("published_at"))
    if published is None:
        return False
    boundary_utc = boundary_local.astimezone(timezone.utc)
    text = post.get("text", "")
    header = text[:180]
    return bool(
        boundary_utc <= published <= boundary_utc + timedelta(minutes=15)
        and post.get("channel", "").lower() in {"adm_dp", "dnipropetrovskaoda"}
        and boundary_local.date() in explicit_event_dates(dict(post, text=header))
        and re.search(r"(?m)^\s*0?8:00\s*$", header)
        and re.search(r"(?:атак\w*|бив)\b", text, re.I)
        and not re.search(r"після\s+0?8:00|щойно|зараз\s+(?:атак|завда)", text, re.I)
    )


def report_window_posts(posts, checked_at):
    start_local, end_local, start_utc, end_utc = completed_report_window(checked_at)
    result = []
    for post in posts:
        published = parse_datetime(post.get("published_at"))
        if published is None or published > checked_at or not is_regional(post):
            continue
        # The same retrospective 08:00 bulletin cannot belong to both
        # adjacent windows merely because it was posted a few seconds late.
        regular = (start_utc <= published < end_utc
                   and not is_cutoff_bulletin(post, start_local))
        # A retrospective official bulletin explicitly headed today's 08:00
        # can be published seconds late. This is NOT a grace period for new
        # attacks or ordinary posts after the cutoff.
        late_bulletin = is_cutoff_bulletin(post, end_local)
        if (regular or late_bulletin) and not is_historical_context(post, start_local):
            result.append(post)
    return dedupe_posts(result)


def contains_any(text, terms):
    return any(term in text for term in terms)


def dedupe_posts(posts):
    result = []
    seen = set()
    for post in sorted(posts, key=lambda item: item["published_at"]):
        fingerprint = re.sub(r"\W+", " ", post.get("text", "").lower()).strip()
        published = parse_datetime(post.get("published_at"))
        context = published.astimezone(KYIV).date() if published else None
        key = (context, fingerprint)
        if fingerprint and key in seen:
            continue
        if fingerprint:
            seen.add(key)
        result.append(post)
    return result


def explicit_event_dates(post):
    text = post.get("text", "").lower()
    published = parse_datetime(post.get("published_at"))
    if published is None:
        return []
    published_local = published.astimezone(KYIV)
    month_pattern = "|".join(UA_MONTHS)
    pattern = rf"\b([0-3]?\d)\s+({month_pattern})(?:\s+(20\d{{2}}))?\b"
    dates = []
    for day_text, month_text, year_text in re.findall(pattern, text):
        try:
            year = int(year_text) if year_text else published_local.year
            dates.append(datetime(year, UA_MONTHS[month_text], int(day_text)).date())
        except ValueError:
            continue
    # Require a year for numeric dates: queue 1.2 and route 6.1 are not dates.
    for day, month, year in re.findall(r"\b([0-3]?\d)\.([01]?\d)\.(20\d{2})\b", text):
        try:
            dates.append(datetime(int(year), int(month), int(day)).date())
        except ValueError:
            continue
    return dates


def is_historical_context(post, report_start_local):
    text = post.get("text", "").lower()
    if re.search(
        r"\b(?:декілька|кілька|декількох|кількох|\d+)\s+"
        r"(?:тижн\w*|місяц\w*|рок\w*)\s+тому\b|"
        r"\b(?:минулого|позаминулого)\s+(?:тижня|місяця|року)\b|"
        r"\bголовні події тижня\b|"
        r"\b(?:від початку|лише|за|упродовж|протягом)\s+(?:цього|поточного)\s+тижня\b",
        text,
    ):
        return True
    if re.search(r"\b(?:напередодні|вчора|учора|минулої доби|за минулу добу)\b", text):
        published = parse_datetime(post.get("published_at"))
        if published and published.astimezone(KYIV).date() - timedelta(days=1) < report_start_local.date():
            return True
    dates = explicit_event_dates(post)
    return bool(dates) and max(dates) < report_start_local.date()


def is_power_queue_change(post):
    text = post.get("text", "").lower()
    power_context = post.get("channel", "").lower() == "cek_info" or re.search(
        r"електро\w*|знеструм\w*|\bгпв\b|погодинн\w*\s+відключ\w*", text)
    return bool(power_context and re.search(r"\bграфік\w*\s+(?:під)?черг\w*", text)
                and re.search(r"\b(?:перевод\w*|переведен\w*|змін\w*)\b", text))


def classify_post(post):
    text = post.get("text", "").lower()
    if is_background_notice(text):
        return None
    if contains_any(text, MINING_TERMS):
        return "2.3"
    if contains_any(text, UXO_TERMS) and contains_any(text, DISCOVERY_TERMS):
        return "2.4"
    if contains_any(text, NON_WEAPON_CRIME_TERMS):
        return None
    if contains_any(text, WEAPON_TERMS) and contains_any(text, ENFORCEMENT_TERMS):
        return "2.2"
    if contains_any(text, ATTACK_TERMS):
        return "2.1"
    if contains_any(text, BLAST_WORK_TERMS):
        return "1.3"
    from transport_state import restored_routes
    if contains_any(text, ROAD_TERMS) or has_stopped_route(text) or restored_routes(text):
        return "1.2"
    if contains_any(text, SERVICE_TERMS) or is_power_queue_change(post):
        return "1.4"
    return None


def compact_text(value, limit=420):
    text = re.sub(r"\s+", " ", value or "").strip()
    if len(text) <= limit:
        return text
    shortened = text[:limit].rsplit(" ", 1)[0].rstrip(" ,;:")
    return shortened + "…"


def fact_line(post):
    from groq_report import clean_source_text
    # The old 420-character cut could remove casualties or the final community.
    # A fallback may be longer, but may not silently drop the end of a fact.
    blocks = [clean_source_text(block) for block in re.split(r"[▪●]\ufe0f?", post.get("text", ""))]
    return "• " + " ".join(block.rstrip() + ("." if block and block[-1] not in '.!?:;' else '')
                            for block in blocks if block)


def section_text(posts):
    if not posts:
        return "У перевірених джерелах повідомлень за звітний період не виявлено."
    return "\n".join(dict.fromkeys(fact_line(post) for post in posts))


def practical_note(section, posts):
    if section == "1.1":
        return (
            "Рекомендація: стежити за офіційними сигналами повітряної тривоги, "
            "тримати зарядженими телефон і павербанк та заздалегідь знати найближче укриття."
        )
    if not posts:
        return ""
    combined_text = " ".join(post.get("text", "").lower() for post in posts)
    if section == "1.4":
        practical = []
        if contains_any(combined_text, ("туман", "видимість", "ожелед")):
            practical.append(
                "гуманітарним місіям варто врахувати можливе збільшення часу в дорозі"
            )
        if contains_any(
            combined_text,
            (
                "відключення", "знеструмлен", "електроенергі", "електропостачання",
                "без світла",
            ),
        ):
            practical.append("мати заряджені телефони та павербанки")
        if contains_any(combined_text, ("водопостачання", "без води")):
            practical.append("підготувати мінімальний запас води")
        if practical:
            return "Практично: " + "; ".join(practical[:2]) + "."
        if contains_any(combined_text, ("гроза", "гроз", "шторм")):
            return "Практично: за грози бути обережними на відкритій місцевості."
        return ""
    if section == "2.1" and contains_any(
        combined_text, ("азс", "автозаправ", "заправн")
    ):
        return (
            "Практично: під час пересування не наближатися до місця удару, "
            "врахувати можливі локальні обмеження та альтернативне місце заправлення."
        )
    notes = {
        "1.2": (
            "Практично: під час пересування враховувати лише підтверджені вище "
            "обмеження та передбачити додатковий час у дорозі."
        ),
        "1.3": (
            "Практично: не наближатися до місця оголошених робіт і виконувати "
            "вказівки відповідальних служб."
        ),
        "2.1": (
            "Практично: реагувати на сигнали тривоги, не наближатися до місць "
            "ударів та не публікувати роботу ППО або місця влучань."
        ),
        "2.2": (
            "Практично: не торкатися підозрілої зброї чи вибухівки та повідомити поліцію за номером 102."
        ),
        "2.3": (
            "Практично: виконувати вказівки адміністрації та поліції; не намагатися "
            "самостійно перевіряти підозрілий об’єкт."
        ),
        "2.4": (
            "Практично: не торкатися знахідки, відійти на безпечну відстань і повідомити 101 або 102."
        ),
    }
    return notes.get(section, "")


def section_with_note(section, posts):
    text = section_text(posts)
    note = practical_note(section, posts)
    return text + ("\n" + note if note else "")


def build_morning_report(posts, statuses, checked_at):
    from fallback_report import build_sections
    start_local, end_local, start_utc, end_utc = completed_report_window(checked_at)
    report_posts = report_window_posts(posts, checked_at)
    groups = {key: [] for key in ("1.2", "1.3", "1.4", "2.1", "2.2", "2.3", "2.4")}
    for post in sorted(report_posts, key=lambda item: item["published_at"]):
        category = classify_post(post)
        if category:
            groups[category].append(post)

    failed = [f"@{channel}" for channel, state in statuses.items() if not state.get("ok")]
    if groups["2.1"]:
        general = (
            "У перевірених офіційних Telegram-джерелах є підтверджені повідомлення "
            "про атаки або їхні наслідки у Дніпропетровській області. Основний "
            "зафіксований ризик за звітний період пов’язаний із повітряними ударами "
            "та їхніми наслідками. Деталі наведено у пункті 2.1."
        )
    else:
        general = "У перевірених джерелах повідомлень про підтверджені зміни безпекової ситуації за звітний період не виявлено."
    if failed:
        general += f" Обмеження перевірки: не отримано актуальні дані з {len(failed)} джерел."
    sections = build_sections(groups, end_local.date())

    return (
        "Доброго дня.\n\n"
        f"Звіт по Дніпропетровській області станом на 08:00 {end_local.strftime('%d.%m.%Y')}.\n"
        f"Звітний період: з 08:00 {start_local.strftime('%d.%m.%Y')} до 08:00 "
        f"{end_local.strftime('%d.%m.%Y')}, за Києвом.\n"
        f"Фактичний час автоматичної перевірки: {checked_at.astimezone(KYIV).strftime('%H:%M %d.%m.%Y')}.\n\n"
        "1. Загальна ситуація в області:\n"
        f"1.1. {general}\n{practical_note('1.1', report_posts)}\n\n"
        f"1.2. {sections['1.2']}\n\n"
        f"1.3. {sections['1.3']}\n\n"
        f"1.4. {sections['1.4']}\n\n"
        "2. Події:\n"
        f"2.1. {sections['2.1']}\n\n"
        f"2.2. {sections['2.2']}\n\n"
        f"2.3. {sections['2.3']}\n\n"
        f"2.4. {sections['2.4']}\n\n"
        "Примітка: це автоматичний огляд офіційних Telegram-джерел станом на вказаний час. "
        "Для негайних дій слід стежити за офіційними сповіщеннями про повітряну тривогу."
    )


def send_long_bot_message(text, limit=3900, start_part=0, part_callback=None):
    paragraphs = text.split("\n\n")
    parts = []
    current = ""
    for paragraph in paragraphs:
        candidate = paragraph if not current else current + "\n\n" + paragraph
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            parts.append(current)
        while len(paragraph) > limit:
            cut = paragraph.rfind("\n", 0, limit)
            if cut < limit // 2:
                cut = limit
            parts.append(paragraph[:cut])
            paragraph = paragraph[cut:].lstrip()
        current = paragraph
    if current:
        parts.append(current)
    for index, part in enumerate(parts, start=1):
        if index <= start_part:
            continue
        prefix = f"Частина {index}/{len(parts)}\n\n" if len(parts) > 1 else ""
        if not send_bot_message(prefix + part):
            raise RuntimeError("Telegram sending unavailable; report not marked as delivered")
        if part_callback:
            part_callback(index)


def deliver_morning_report(report, state, report_date):
    pending = state.get("pending_daily_report", {})
    if pending.get("date") != report_date or pending.get("text") != report:
        pending = {"date": report_date, "text": report, "sent_parts": 0}
    state["pending_daily_report"] = pending
    save_alert_state(state)

    def confirmed(index):
        pending["sent_parts"] = index
        save_alert_state(state)

    send_long_bot_message(report, start_part=pending["sent_parts"], part_callback=confirmed)
    state["last_daily_report"] = report_date
    state.pop("pending_daily_report", None)
    save_alert_state(state)


def process_morning_report(posts, statuses, checked_at):
    local_now = checked_at.astimezone(KYIV)
    today_at_eight = local_now.replace(hour=8, minute=0, second=0, microsecond=0)
    if local_now < today_at_eight:
        return
    state = read_alert_state()
    start_local, end_local, start_utc, end_utc = completed_report_window(checked_at)
    report_date = end_local.date().isoformat()
    force_report = os.getenv("FORCE_MORNING_REPORT", "").lower() in {"1", "true", "yes"}
    send_enabled = os.getenv("SEND_MORNING_REPORT", "true").lower() in {"1", "true", "yes"}
    if state.get("last_daily_report") == report_date and not force_report:
        return
    pending = state.get("pending_daily_report", {})
    if pending.get("date") == report_date and pending.get("text") and not force_report:
        if send_enabled:
            print("Resuming partially delivered morning report without AI calls")
            deliver_morning_report(pending["text"], state, report_date)
        return

    fallback = build_morning_report(posts, statuses, checked_at)
    regional_posts = report_window_posts(posts, checked_at)
    ai_posts = []
    for post in regional_posts:
        category = classify_post(post)
        if category is None or is_historical_context(post, start_local):
            continue
        item = dict(post)
        item["category_hint"] = category
        item["published_local"] = parse_datetime(post["published_at"]).astimezone(KYIV).strftime(
            "%d.%m.%Y %H:%M за Києвом"
        )
        if parse_datetime(post["published_at"]) >= end_utc:
            item["cutoff_bulletin"] = True
        ai_posts.append(item)
    failed_sources = [
        f"@{channel}" for channel, status in statuses.items() if not status.get("ok")
    ]

    try:
        from ai_report import generate_report

        report = generate_report(
            ai_posts,
            start_local.strftime("%H:%M %d.%m.%Y"),
            end_local.strftime("%H:%M %d.%m.%Y"),
            checked_at.astimezone(KYIV).strftime("%H:%M %d.%m.%Y"),
            end_local.strftime("%d.%m.%Y"),
            failed_sources,
        )
        report_kind = "author"
    except Exception as error:
        from ai_report import sanitize_fallback

        print(f"Author report unavailable: {type(error).__name__}: {error}")
        report = sanitize_fallback(fallback)
        report_kind = "fallback"

    MORNING_REPORT_FILE.write_text(report + "\n", encoding="utf-8")
    print(f"Morning report prepared: {report_kind}")
    if not send_enabled:
        print("Morning report dry run: Telegram sending disabled")
        return

    deliver_morning_report(report, state, report_date)


def channel_range(posts, channel):
    channel_posts = [p for p in posts if p.get("channel", "").lower() == channel.lower()]
    if not channel_posts:
        return None, None
    dates = [parse_datetime(p["published_at"]) for p in channel_posts]
    return min(dates).isoformat(), max(dates).isoformat()


def write_outputs(posts, statuses, checked_at, previous_checked_at=None):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    POSTS_FILE.write_text(
        json.dumps(posts, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    recent_cutoff = checked_at - timedelta(hours=48)
    recent = [post for post in posts if parse_datetime(post["published_at"]) >= recent_cutoff]

    lines = [
        "# Останні дописи офіційних каналів",
        "",
        f"Перевірено: {checked_at.isoformat()}",
        "",
    ]
    for post in sorted(recent, key=lambda item: item["published_at"], reverse=True):
        lines.extend(
            [
                f"## @{post['channel']} — {post['published_at']}",
                "",
                post["text"],
                "",
                post["url"],
                "",
            ]
        )
    LATEST_FILE.write_text("\n".join(lines), encoding="utf-8")

    start_local, end_local, start_utc, end_utc = completed_report_window(checked_at)
    report_posts = report_window_posts(posts, checked_at)
    report_lines = [
        "# Вхідні дані для ранкової довідки",
        "",
        f"Фактичний час останнього збору: {checked_at.astimezone(KYIV).isoformat()}",
        (
            "Звітне вікно: "
            f"{start_local.strftime('%d.%m.%Y %H:%M')} — "
            f"{end_local.strftime('%d.%m.%Y %H:%M')} за Києвом"
        ),
        "",
        "## Стан джерел",
        "",
    ]
    for channel, state in statuses.items():
        if state.get("ok"):
            report_lines.append(
                f"- @{channel}: доступ отримано; знайдено під час останнього обходу: "
                f"{state.get('posts_found', 0)}; діапазон локального буфера UTC: "
                f"{state.get('oldest_collected_at') or 'немає даних'} — "
                f"{state.get('newest_collected_at') or 'немає даних'}."
            )
        else:
            report_lines.append(f"- @{channel}: ПОМИЛКА — {state.get('error', 'невідома помилка')}.")

    report_lines.extend(["", "## Дописи у звітному вікні", ""])
    if not report_posts:
        report_lines.append("У локальному буфері дописів для цього вікна немає.")
    else:
        for post in sorted(report_posts, key=lambda item: item["published_at"]):
            local_published = parse_datetime(post["published_at"]).astimezone(KYIV)
            report_lines.extend(
                [
                    f"### @{post['channel']} — {local_published.strftime('%d.%m.%Y %H:%M')} за Києвом",
                    "",
                    post["text"],
                    "",
                    post["url"],
                    "",
                ]
            )
    REPORT_INPUT_FILE.write_text("\n".join(report_lines), encoding="utf-8")

    STATUS_FILE.write_text(
        json.dumps(
            {
                "checked_at": checked_at.isoformat(),
                "previous_checked_at": previous_checked_at.isoformat() if previous_checked_at else None,
                "collection_gap_minutes": round((checked_at-previous_checked_at).total_seconds()/60, 1)
                    if previous_checked_at else None,
                "report_window": {
                    "timezone": "Europe/Kyiv",
                    "start": start_local.isoformat(),
                    "end": end_local.isoformat(),
                },
                "retention_hours": KEEP_HOURS,
                "channels": statuses,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def recovered_restoration_keys(posts, changed_keys, state, checked_at):
    from transport_state import restored_routes, latest_restored_routes
    alerted = set(state.get('alerted_keys', []))
    result = []
    for post in posts:
        published = parse_datetime(post.get('published_at'))
        if (post['key'] not in changed_keys or post['key'] in alerted
            or post.get('reply_to') not in alerted or published is None
            or published > checked_at or published.astimezone(KYIV).date() != checked_at.astimezone(KYIV).date()):
            continue
        routes = restored_routes(post.get('text', ''))
        related = [p for p in posts if p.get('channel', '').lower() == post.get('channel', '').lower()]
        if routes and routes <= latest_restored_routes(related):
            result.append(post['key'])
    return result


def main():
    checked_at = utc_now()
    cutoff = checked_at - timedelta(hours=LOOKBACK_HOURS)
    keep_after = checked_at - timedelta(hours=KEEP_HOURS)
    channels = load_channels()
    session = requests.Session()

    existing = {post["key"]: post for post in read_existing() if "key" in post}
    try:
        previous_status = json.loads(STATUS_FILE.read_text(encoding="utf-8"))
        if not isinstance(previous_status, dict):
            raise ValueError("invalid status structure")
        previous_checked_at = parse_datetime(previous_status.get("checked_at"))
    except (OSError, ValueError, TypeError):
        previous_status = {}
        previous_checked_at = None
    statuses = {}
    parser_changed_keys = set()

    for channel in channels:
        try:
            known_channel_dates = [
                parse_datetime(post["published_at"])
                for post in existing.values()
                if post.get("channel", "").lower() == channel.lower()
                and parse_datetime(post.get("published_at"))
            ]
            # Невелике перекриття підхоплює запізнілі зміни, не змушуючи
            # перечитувати весь 72-годинний буфер кожні 30 хвилин.
            channel_cutoff = cutoff
            if known_channel_dates and previous_status.get("channels", {}).get(channel, {}).get("parser_version") == PARSER_VERSION:
                channel_cutoff = max(cutoff, max(known_channel_dates) - timedelta(hours=2))

            found = collect_channel(channel, session, channel_cutoff)
            for post in found:
                previous = existing.get(post['key'])
                if previous and previous.get('parser_recovered'):
                    post['parser_recovered'] = True
                if (previous_status.get('channels', {}).get(channel, {}).get('parser_version') != PARSER_VERSION
                    and previous and previous.get('text') != post.get('text')):
                    parser_changed_keys.add(post['key'])
                    post['parser_recovered'] = True
                existing[post["key"]] = post
            oldest, newest = channel_range(list(existing.values()), channel)
            statuses[channel] = {
                "ok": True,
                "parser_version": PARSER_VERSION,
                "posts_found": len(found),
                "oldest_collected_at": oldest,
                "newest_collected_at": newest,
            }
            print(f"@{channel}: {len(found)}")
        except Exception as error:
            statuses[channel] = {
                "ok": False,
                "error": f"{type(error).__name__}: {error}",
            }
            print(f"@{channel}: ERROR {type(error).__name__}: {error}")

    posts = [
        post
        for post in existing.values()
        if parse_datetime(post.get("published_at"))
        and parse_datetime(post["published_at"]) >= keep_after
    ]
    posts.sort(key=lambda item: (item["published_at"], item["channel"], item["post_id"]))
    write_outputs(posts, statuses, checked_at, previous_checked_at)
    parser_changed_keys.update(p['key'] for p in posts if p.get('parser_recovered'))
    recovered = recovered_restoration_keys(posts, parser_changed_keys, read_alert_state(), checked_at)
    alert_failures = process_alerts(posts, checked_at, previous_checked_at, recovered_keys=recovered)
    process_morning_report(posts, statuses, checked_at)
    if alert_failures:
        raise RuntimeError("Operational messages remain pending; next run will retry")


if __name__ == "__main__":
    main()
