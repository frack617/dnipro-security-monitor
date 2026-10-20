"""Explicit route restoration and its coverage, without inventing causes."""
import re


def transport_clauses(text):
    """Split notices without treating street abbreviations as sentence ends."""
    protected = re.sub(r'\b(м|вул|пл|обл|ім|ст|пров|просп)\.',
                       lambda m: m[1]+'\u2024', text, flags=re.I)
    return [part.replace('\u2024', '.').strip() for part in re.split(
        r'(?<=[.!?;])\s+(?=[А-ЯІЇЄҐ0-9])', protected) if part.strip()]


def effective_transport_posts(posts):
    """Remove only clauses ended by a later same-channel direct reply.

    Keep the original notices untouched, restoration itself, unrelated clauses
    and any restrictions announced again later. Route kind is part of identity.
    """
    from report_sections import clean_transport_notice
    ordered = sorted(posts, key=lambda p: p.get('published_at', p.get('published_local', '')))
    targets = {p['key']: p for p in ordered if p.get('key')}
    ended = {}
    for post in ordered:
        target = targets.get(post.get('reply_to'))
        if (target and target.get('channel') == post.get('channel')
                and target.get('published_at', '') < post.get('published_at', '')):
            ended.setdefault(target['key'], set()).update(restored_routes(post.get('text', '')))
    result = []
    for post in ordered:
        item = dict(post)
        if post.get('key') in ended and ended[post['key']]:
            clauses = transport_clauses(clean_transport_notice(post))
            item['text'] = ' '.join(c for c in clauses if not (
                transport_routes(c) and transport_routes(c) <= ended[post['key']]))
            item['text'] = re.sub(r'^Оновлена інформація[^:]*:\s*', '', item['text']).strip()
        if item.get('text', '').strip():
            result.append(item)
    return result


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
    for clause in transport_clauses(body):
        if (transport_routes(clause) & required
            and re.search(r'призупин\w*|припини\w*\s+(?:свою\s+)?роботу', clause, re.I)
            and not re.search(r'раніше|попередн\w*\s+повідомлен|згодом|пізніше|було\s+призупин', body, re.I)):
            problems.append('outdated transport restriction presented as current')
            break
    return problems
