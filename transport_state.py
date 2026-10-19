"""Explicit route restoration and its coverage, without inventing causes."""
import re


def transport_routes(text):
    markers = list(re.finditer(r"\b(?:трамва\w*|тролейбус\w*|автобус\w*)\s*№", text, re.I))
    result = set()
    for index, marker in enumerate(markers):
        kind = "трамвай" if marker[0].lower().startswith("трамва") else "тролейбус" if marker[0].lower().startswith("тролейбус") else "автобус"
        stop = markers[index+1].start() if index+1 < len(markers) else len(text)
        for match in re.finditer(r"№\s*(\d+(?:\s*[А-ЯІЇЄҐA-Z](?![а-яіїєґa-z]))?)", text[marker.start():stop]):
            result.add((kind, re.sub(r"\s+", "", match[1]).upper()))
    return result


def restored_routes(text):
    text = re.sub(r"\s+", " ", text)
    result = set()
    for match in re.finditer(r"\b(?:відновлюється|відновлено|відновився|відновлюють)\s+рух\b[^.!?]*", text, re.I):
        if re.search(r'\bне\s+(?:було\s+)?$', text[max(0, match.start()-20):match.start()], re.I):
            continue
        result.update(transport_routes(match[0]))
    return result


def latest_restored_routes(posts):
    latest = {}
    for post in sorted(posts, key=lambda p: p.get('published_at', p.get('published_local', ''))):
        if post.get('category_hint', '1.2') != '1.2':
            continue
        text = post.get('text', '')
        restored = restored_routes(text)
        for route in transport_routes(text):
            latest[route] = route in restored
    return {route for route, restored in latest.items() if restored}


def restoration_problems(body, posts):
    required = latest_restored_routes(posts)
    if not required:
        return []
    problems = []
    if required - restored_routes(body):
        problems.append('missing source transport restoration')
    # Preserve historical restrictions only with an explicit time/context label.
    if (re.search(r'призупин\w*|припини\w*\s+(?:свою\s+)?роботу', body, re.I)
        and not re.search(r'раніше|попередн\w*\s+повідомлен|згодом|пізніше|було\s+призупин', body, re.I)):
        problems.append('outdated transport restriction presented as current')
    return problems
