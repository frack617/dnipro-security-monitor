"""Group source updates by publication date and explicit place, without totals.

These are presentation groups, not claims that matching places prove one attack.
Original casualty, damage, uncertainty and explicit episode wording survive.
"""
from collections import OrderedDict
import re

from report_rules import MONTHS, PLACE_PATTERNS, normalize


SERVICES = re.compile(r'^(?:на місці |на місцях ударів )?працюють усі служби[.!]?$', re.I)
NEW_EPISODE = re.compile(r'\bзнову\b|\bнов\w*\s+(?:атак|удар)|\bповторн\w*\s+(?:атак|удар)', re.I)
EPISODE_TIME = re.compile(r'\b\d{1,2}:\d{2}\b|\bвранці\b|\bзранку\b|\bввечері\b|\bуночі\b|\bвночі\b', re.I)


def explicit_place(text):
    found = [name for name, pattern in PLACE_PATTERNS.items() if re.search(pattern, text, re.I)]
    return found[0] if len(found) == 1 else None


def source_records(post):
    from fallback_report import clean_event
    blocks = re.split(r'[▪●]\ufe0f?', post.get('text', ''))
    full = clean_event(post)
    if len(blocks) > 1:
        bodies = [clean_event(dict(post, text=b)) for b in blocks[1:]]
        if bodies and bodies[0] and bodies[0] in full:
            header = full.split(bodies[0], 1)[0].strip()
            return header, [(explicit_place(b), b, True) for b in bodies if b]
    return '', [(explicit_place(full), full, False)] if full else []


def grouped_attack_text(posts):
    from fallback_report import clean_event, publication_date, sentences
    groups = OrderedDict()
    seen_posts = set()
    for index, post in enumerate(sorted(posts, key=lambda p: p.get('published_at', p.get('published_local', '')))):
        day = publication_date(post)
        # Unknown dates remain separate; no inferred incident date is invented.
        key = day if day is not None else ('unknown', index)
        fingerprint = (key, normalize(clean_event(post)))
        if fingerprint in seen_posts:
            continue
        seen_posts.add(fingerprint)
        group = groups.setdefault(key, {'headers': [], 'places': OrderedDict()})
        header, records = source_records(post)
        if header and header not in group['headers']:
            group['headers'].append(header)
        for place, text, bulletin in records:
            # Unrecognized/mixed places stay independent rather than being
            # attached to the nearest recognized city or district.
            slot = place if place is not None else ('separate', index, len(group['places']))
            group['places'].setdefault(slot, []).append((text, bulletin))
    paragraphs = []
    for day, group in groups.items():
        if not isinstance(day, tuple):
            paragraphs.append(f'Повідомлення від {day.day} {MONTHS[day.month-1]}:')
        paragraphs.extend(group['headers'])
        for place, records in group['places'].items():
            parts = []
            service_seen = False
            for index, (text, bulletin) in enumerate(records):
                separate = bool(NEW_EPISODE.search(text))
                if separate:
                    service_seen = False
                kept = []
                for sentence in sentences(text):
                    # A bare generic housing sentence adds no unique detail
                    # when the later same-place bulletin repeats that fact.
                    # Numbers, casualties, qualifiers and separate attacks
                    # are never removed by this rule.
                    if re.fullmatch(r'Пошкоджені приватні будинки[.!]?', sentence, re.I):
                        later = records[index+1:]
                        if (not EPISODE_TIME.search(text)
                            and not any(NEW_EPISODE.search(t) or EPISODE_TIME.search(t) for t, _ in later)
                            and any(b and re.search(r'(?:понівечені|пошкоджені)\s+(?:інфраструктура,\s*)?приватні будинки', t, re.I)
                                    for t, b in later)):
                            continue
                    if SERVICES.fullmatch(sentence.strip()):
                        if service_seen:
                            continue
                        service_seen = True
                    kept.append(sentence)
                text = ' '.join(kept)
                if not text:
                    continue
                if len(records) > 1:
                    if isinstance(place, str):
                        text = re.sub(r'^'+re.escape(place)+r'\s*:\s*', '', text)
                        text = re.sub(r'^(?:У|В|На)\s+(?:'+PLACE_PATTERNS[place]+r')\s+', '', text, flags=re.I)
                        text = text[:1].upper()+text[1:]
                    if bulletin:
                        text = 'Зведення: ' + text
                    elif separate and index:
                        text = 'Окреме повідомлення: ' + text
                    elif index < len(records)-1:
                        text = ('Попередньо: ' if index == 0 else 'Пізніше: ') + text
                parts.append(text)
            if parts:
                # No numeric updates are deduplicated, added, or declared final.
                prefix = place + '. ' if isinstance(place, str) and len(records) > 1 else ''
                paragraphs.append(prefix + ' '.join(parts))
    result = '\n\n'.join(paragraphs)
    # Reordering is presentation only: if it creates a new ambiguity for the
    # existing source checks, retain the original chronological prose instead.
    from report_rules import source_problems
    evidence = [dict(p, category_hint='2.1') for p in posts]
    original = ' '.join(clean_event(p) for p in sorted(posts, key=lambda p: p.get('published_at', p.get('published_local', ''))))
    def checked(body):
        return set(source_problems('1.1. Підтверджені події.\n2.1. '+body+'\n2.2. Інших подій не виявлено.', evidence))
    if checked(result) - checked(original):
        return original
    return result
