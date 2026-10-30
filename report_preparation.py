"""Prepare report evidence without changing the collected source archive.

Remove exact HTML/parser repetitions and explicitly background-only articles.
No numeric fact, source date, place or casualty is rewritten here.
"""
import re


def deduplicate_source_body(text):
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    # Telegram copies can repeat the complete own body, including paragraphs.
    # Remove only adjacent identical blocks, never recurring facts in episodes.
    changed = True
    while changed:
        changed = False
        for width in range(len(lines) // 2, 0, -1):
            for start in range(len(lines) - 2 * width + 1):
                block = lines[start:start + width]
                if (block == lines[start + width:start + 2 * width]
                        and len(' '.join(block)) >= 80):
                    del lines[start + width:start + 2 * width]
                    changed = True
                    break
            if changed:
                break
    return '\n'.join(lines)


def background_service_article(text):
    opening = re.sub(r'\s+', ' ', text[:500]).lower()
    background = re.search(
        r'як .{0,100}(?:підвищують енергонезалежність|електронний кабінет)|'
        r'сонячні панелі, резервне живлення та економія тепла|'
        r'медичні довідки без зайвих візитів|'
        r'адресн\w* допомог\w* на оплату житлово-комунальних|'
        r'перевіряю пункти незламності|готуємося до зими', opening)
    if not background:
        return False
    actual = re.search(
        r'(?:сьогодні|зараз|наразі)[^.!?]{0,70}(?:немає світла|знеструмлен)|'
        r'(?:спричинил\w*|через аварі\w*)[^.!?]{0,70}знеструмлен|'
        r'(?:ворог|росіяни)\s+(?:\w+\s+){0,2}(?:завда\w*|атакув\w*)', text, re.I)
    return not actual


def prepare_evidence(posts):
    result, seen = [], set()
    for post in posts:
        item = dict(post)
        item['text'] = deduplicate_source_body(post.get('text', ''))
        if background_service_article(item['text']):
            continue
        # Identical mirror statements on different dates remain independent.
        day = item.get('published_local', item.get('published_at', ''))[:10]
        key = (day, re.sub(r'\s+', ' ', item['text']).casefold())
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result
