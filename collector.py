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
CHANNELS_FILE = ROOT / "channels.txt"

LOOKBACK_HOURS = int(os.getenv("LOOKBACK_HOURS", "72"))
KEEP_HOURS = int(os.getenv("KEEP_HOURS", "72"))
MAX_PAGES = int(os.getenv("MAX_PAGES", "12"))
KYIV = ZoneInfo("Europe/Kyiv")

LOCAL_CHANNELS = {"adm_dp", "dniprocityofficial", "gunpvdp", "cek_info"}
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
    "обстріл", "атакував", "атакувала", "атакували", "ворожа атака",
    "ракетний удар", "ракетна атака", "ударний безпілотник", "бпла",
    "шахед", "влучання", "ворог завдав удару",
)
ROAD_TERMS = (
    "перекрито рух", "перекриття руху", "обмежено рух", "обмеження руху",
    "зміни у русі", "тимчасово не курсуват", "змінено маршрут",
)
BLAST_WORK_TERMS = (
    "планові вибух", "вибухові роботи", "контрольований вибух",
    "буде чутно вибух", "можна почути вибух",
)
SERVICE_TERMS = (
    "аварійне відключення", "екстрене відключення", "відсутнє водопостачання",
    "припинено водопостачання", "теплопостачання", "знеструмлен",
    "масштабна пожежа", "аварія на", "затримка руху", "не курсуватиме",
)
WEAPON_TERMS = ("збро", "гранат", "вибухівк", "боєприпас")
ENFORCEMENT_TERMS = ("незакон", "вилуч", "затрим", "підозр", "обшук", "збут")
MINING_TERMS = ("замінуван", "псевдомінув", "повідомлення про мінування")
UXO_TERMS = ("вибухонебезпечн", "нерозірван", "боєприпас")
DISCOVERY_TERMS = ("виявил", "знайшл", "знешкодил", "знищил")

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


def parse_page(channel, html):
    soup = BeautifulSoup(html, "html.parser")
    posts = []

    for node in soup.select(".tgme_widget_message[data-post]"):
        data_post = node.get("data-post", "")
        if "/" not in data_post:
            continue

        post_channel, post_id_text = data_post.rsplit("/", 1)
        if not post_id_text.isdigit():
            continue

        time_node = node.select_one("time[datetime]")
        published_at = time_node.get("datetime") if time_node else None
        published_dt = parse_datetime(published_at)
        if published_dt is None:
            continue

        text_node = node.select_one(".tgme_widget_message_text")
        text = text_node.get_text("\n", strip=True) if text_node else "[Медіа без тексту]"
        text = re.sub(r"[ \t]+", " ", text).strip()

        post_id = int(post_id_text)
        posts.append(
            {
                "key": f"{post_channel}/{post_id}",
                "channel": post_channel or channel,
                "post_id": post_id,
                "published_at": published_dt.isoformat(),
                "url": f"https://t.me/{post_channel}/{post_id}",
                "text": text,
            }
        )

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
    return True


def is_resonant(post):
    text = post.get("text", "").lower()
    channel = post.get("channel", "").lower()
    has_event = any(term in text for term in ALERT_TERMS)
    if not has_event:
        return False
    return channel in LOCAL_CHANNELS or any(term in text for term in REGION_TERMS)


def process_alerts(new_posts, checked_at):
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

    recent_after = checked_at - timedelta(hours=2)
    for post in sorted(new_posts, key=lambda item: item["published_at"]):
        if post["key"] in alerted or parse_datetime(post["published_at"]) < recent_after:
            continue
        if not is_resonant(post):
            continue
        local_time = parse_datetime(post["published_at"]).astimezone(KYIV)
        excerpt = post["text"][:2500]
        send_bot_message(
            "⚠️ Оперативне повідомлення щодо Дніпропетровщини\n\n"
            f"Джерело: @{post['channel']}\n"
            f"Час публікації: {local_time.strftime('%d.%m.%Y %H:%M')} за Києвом\n\n"
            f"{excerpt}\n\n{post['url']}"
        )
        alerted.add(post["key"])

    keep_keys = {
        post["key"] for post in new_posts
        if parse_datetime(post["published_at"]) >= checked_at - timedelta(hours=KEEP_HOURS)
    }
    state["alerted_keys"] = sorted(alerted & keep_keys)
    ALERT_STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


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
    return channel in LOCAL_CHANNELS or any(term in text for term in REGION_TERMS)


def contains_any(text, terms):
    return any(term in text for term in terms)


def classify_post(post):
    text = post.get("text", "").lower()
    if contains_any(text, MINING_TERMS):
        return "2.3"
    if contains_any(text, UXO_TERMS) and contains_any(text, DISCOVERY_TERMS):
        return "2.4"
    if contains_any(text, WEAPON_TERMS) and contains_any(text, ENFORCEMENT_TERMS):
        return "2.2"
    if contains_any(text, ATTACK_TERMS):
        return "2.1"
    if contains_any(text, BLAST_WORK_TERMS):
        return "1.3"
    if contains_any(text, ROAD_TERMS):
        return "1.2"
    if contains_any(text, SERVICE_TERMS):
        return "1.4"
    return None


def compact_text(value, limit=420):
    text = re.sub(r"\s+", " ", value or "").strip()
    if len(text) <= limit:
        return text
    shortened = text[:limit].rsplit(" ", 1)[0].rstrip(" ,;:")
    return shortened + "…"


def fact_line(post):
    published = parse_datetime(post["published_at"]).astimezone(KYIV)
    return (
        f"• {published.strftime('%d.%m %H:%M')} · @{post['channel']}: "
        f"{compact_text(post.get('text'))}\n{post['url']}"
    )


def section_text(posts):
    if not posts:
        return "У перевірених джерелах повідомлень за звітний період не виявлено."
    return "\n".join(fact_line(post) for post in posts[:6])


def build_morning_report(posts, statuses, checked_at):
    start_local, end_local, start_utc, end_utc = completed_report_window(checked_at)
    report_posts = [
        post for post in posts
        if start_utc <= parse_datetime(post.get("published_at")) < end_utc
        and is_regional(post)
    ]
    groups = {key: [] for key in ("1.2", "1.3", "1.4", "2.1", "2.2", "2.3", "2.4")}
    for post in sorted(report_posts, key=lambda item: item["published_at"]):
        category = classify_post(post)
        if category:
            groups[category].append(post)

    failed = [f"@{channel}" for channel, state in statuses.items() if not state.get("ok")]
    if groups["2.1"]:
        general = (
            f"У перевірених офіційних Telegram-джерелах виявлено "
            f"{len(groups['2.1'])} повідомлень про атаки або їхні наслідки "
            "у Дніпропетровській області. Деталі наведено у пункті 2.1."
        )
    else:
        general = "У перевірених джерелах повідомлень про підтверджені зміни безпекової ситуації за звітний період не виявлено."
    if failed:
        general += " Обмеження перевірки: не отримано актуальні дані з " + ", ".join(failed) + "."

    return (
        "Доброго дня.\n\n"
        f"Звіт по Дніпропетровській області станом на 08:00 {end_local.strftime('%d.%m.%Y')}.\n"
        f"Звітний період: з 08:00 {start_local.strftime('%d.%m.%Y')} до 08:00 "
        f"{end_local.strftime('%d.%m.%Y')}, за Києвом.\n"
        f"Фактичний час автоматичної перевірки: {checked_at.astimezone(KYIV).strftime('%H:%M %d.%m.%Y')}.\n\n"
        "1. Загальна ситуація в області:\n"
        f"1.1. {general}\n\n"
        f"1.2. {section_text(groups['1.2'])}\n\n"
        f"1.3. {section_text(groups['1.3'])}\n\n"
        f"1.4. {section_text(groups['1.4'])}\n\n"
        "2. Події:\n"
        f"2.1. {section_text(groups['2.1'])}\n\n"
        f"2.2. {section_text(groups['2.2'])}\n\n"
        f"2.3. {section_text(groups['2.3'])}\n\n"
        f"2.4. {section_text(groups['2.4'])}\n\n"
        "Примітка: це автоматичний огляд офіційних Telegram-джерел станом на вказаний час. "
        "Для негайних дій слід стежити за офіційними сповіщеннями про повітряну тривогу."
    )


def send_long_bot_message(text, limit=3900):
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
        prefix = f"Частина {index}/{len(parts)}\n\n" if len(parts) > 1 else ""
        send_bot_message(prefix + part)


def process_morning_report(posts, statuses, checked_at):
    local_now = checked_at.astimezone(KYIV)
    if local_now.hour != 8:
        return
    state = read_alert_state()
    report_date = completed_report_window(checked_at)[1].date().isoformat()
    if state.get("last_daily_report") == report_date:
        return
    send_long_bot_message(build_morning_report(posts, statuses, checked_at))
    state["last_daily_report"] = report_date
    ALERT_STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def channel_range(posts, channel):
    channel_posts = [p for p in posts if p.get("channel", "").lower() == channel.lower()]
    if not channel_posts:
        return None, None
    dates = [parse_datetime(p["published_at"]) for p in channel_posts]
    return min(dates).isoformat(), max(dates).isoformat()


def write_outputs(posts, statuses, checked_at):
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
    report_posts = [
        post
        for post in posts
        if start_utc <= parse_datetime(post["published_at"]) < end_utc
    ]
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


def main():
    checked_at = utc_now()
    cutoff = checked_at - timedelta(hours=LOOKBACK_HOURS)
    keep_after = checked_at - timedelta(hours=KEEP_HOURS)
    channels = load_channels()
    session = requests.Session()

    existing = {post["key"]: post for post in read_existing() if "key" in post}
    existing_keys = set(existing)
    statuses = {}

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
            if known_channel_dates:
                channel_cutoff = max(cutoff, max(known_channel_dates) - timedelta(hours=2))

            found = collect_channel(channel, session, channel_cutoff)
            for post in found:
                existing[post["key"]] = post
            oldest, newest = channel_range(list(existing.values()), channel)
            statuses[channel] = {
                "ok": True,
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
    write_outputs(posts, statuses, checked_at)
    process_alerts([post for post in posts if post["key"] not in existing_keys], checked_at)
    process_morning_report(posts, statuses, checked_at)


if __name__ == "__main__":
    main()

