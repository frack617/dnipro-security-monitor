"""Conservative relational checks for explicitly scoped numeric facts.

Unknown source fields are not evidence of a contradiction. This does not
identify incidents or prove facts correct; it rejects detectable reassignment.
"""
from dataclasses import dataclass
import re

from report_rules import (DATE_WORDS, MONTHS, NUMBER, PLACE_PATTERNS,
                          attack_counts, community_stems, downed_drone_counts,
                          house_counts, normalize, number_value, asserted_counts)


@dataclass(frozen=True)
class NumericFact:
    kind: str
    count: int
    places: object = None
    communities: object = None
    day: object = None
    periods: object = None
    clock: object = None
    districts: object = None
    ambiguous: bool = False


def period_words(text):
    result = set()
    for name, pattern in (
        ('night', r'\b(?:уночі|вночі|за ніч|у ніч|в ніч)\b'),
        ('day', r'\b(?:удень|вдень|за день|упродовж дня|протягом дня)\b'),
        ('morning', r'\b(?:вранці|зранку)\b|\bранков\w*\s+(?:атак|удар)'),
        ('evening', r'\b(?:ввечері|увечері)\b|\bвечірн\w*\s+(?:атак|удар)'),
    ):
        if re.search(pattern, text, re.I):
            result.add(name)
    return frozenset(result) or None


def extract_numeric_facts(text):
    # New lines matter for a source bulletin's location-only labels. Protect
    # abbreviations so 'м. Дніпро' does not terminate its location scope.
    text = re.sub(r'\b(м|обл|вул|пл)\.', lambda m: m[1]+'\u2024', text, flags=re.I)
    initial = re.split(r'[▪●]\ufe0f?|\n|(?<=[.!?;])\s+|,\s*(?:а|натомість)\s+(?=[УВНувн])', text)
    chunks = []
    for item in initial:
        # Split independently quantified clauses, including comma-separated
        # city updates. A joint place list BEFORE its single count stays joint.
        rest = item
        while True:
            boundary = None
            for match in re.finditer(r'(?:,\s*(?:(?:та|також)\s+)?|\s+(?:та|і)\s+)(?=(?:у|в|на)\s+)', rest, re.I):
                prefix = rest[:match.start()]
                if (any(house_counts(prefix).values()) or attack_counts(prefix)
                    or downed_drone_counts(prefix) or asserted_counts(prefix)):
                    boundary = match
                    break
            if boundary is None:
                chunks.append(rest)
                break
            chunks.append(rest[:boundary.start()])
            rest = rest[boundary.end():]
    places = communities = day = periods = clock = None
    facts = []
    for chunk in chunks:
        raw_chunk = chunk.replace('\u2024', '.')
        chunk = normalize(raw_chunk)
        if not chunk:
            continue
        publication_heading = bool(re.match(r'повідомлення від\s+'+DATE_WORDS, chunk))
        bulletin_heading = bool(re.match(r'(?:за\s+.*?зведенням|зведення(?:\s+станом)?)\b', chunk))
        if publication_heading or bulletin_heading:
            places = communities = day = periods = clock = None
        dates = list(re.finditer(DATE_WORDS, chunk)) if not publication_heading else []
        if dates:
            new_day = (int(dates[-1][1]), MONTHS.index(dates[-1][2])+1)
            if day != new_day:
                periods = clock = None
            day = new_day
        new_places = {name for name, pattern in PLACE_PATTERNS.items() if re.search(pattern, chunk, re.I)}
        if re.search(r'\bдніпропетровщин\w*|\bдніпропетровськ\w*\s+област\w*|\bнад област\w*', chunk):
            new_places.add('Дніпропетровська область')
        new_communities = set(community_stems(raw_chunk)) if 'громад' in chunk else set()
        if new_places or new_communities:
            places = frozenset(new_places) or None
            communities = frozenset(new_communities) or None
        new_periods = period_words(chunk)
        if new_periods:
            periods = new_periods
        explicit_clock = re.findall(r'\b(?:о|близько)\s+(\d{1,2}:\d{2})\b', chunk)
        if explicit_clock:
            clock = frozenset(explicit_clock)
        district_counts = frozenset(number_value(m[1]) for m in
                                    re.finditer(r'\b('+NUMBER+r')\s+район\w*', chunk)) or None
        values = house_counts(chunk)
        values.update(attacks=attack_counts(chunk), downed=downed_drone_counts(chunk))
        for kind, numbers in values.items():
            fact_places, fact_communities = places, communities
            if kind == 'attacks' and district_counts:
                # A multi-district summary after a city paragraph does not
                # belong to that preceding city/community, or the first
                # regional example following its colon, by proximity.
                count_match = re.search(r'\b\d+\s+(?:разів|рази|атак\w*|обстріл\w*)', chunk)
                prefix = chunk[:count_match.start()] if count_match else ''
                before = {name for name, pattern in PLACE_PATTERNS.items() if re.search(pattern, prefix, re.I)}
                if before:
                    fact_places = frozenset(before)
                    fact_communities = frozenset(c for c in new_communities if re.search(re.escape(c), prefix)) or None
                else:
                    fact_places = (frozenset({'Дніпропетровська область'})
                                   if re.search(r'район\w*\s+област\w*', chunk)
                                   or places == frozenset({'Дніпропетровська область'}) else None)
                    fact_communities = None
            ambiguous = bool(fact_places and len(fact_places)>1 and len(numbers)>1)
            for number in numbers:
                facts.append(NumericFact(kind, number, fact_places, fact_communities, day, periods,
                                         clock, district_counts if kind=='attacks' else None, ambiguous))
    return facts


def compatible(output, source):
    if source.ambiguous:
        return True
    for key in ('places', 'communities', 'day', 'clock', 'districts'):
        given, known = getattr(output, key), getattr(source, key)
        if given is not None and known is not None and given != known:
            return False
    if output.periods and source.periods and not output.periods.intersection(source.periods):
        return False
    # Source evidence for a regional count does not establish that count in a
    # newly named community. A parent-only output can remain a generalization.
    if output.communities and not source.communities and source.places:
        return False
    return True


def numeric_scope_problems(section, posts):
    sources = [fact for post in posts for fact in extract_numeric_facts(post.get('text', ''))]
    problems = []
    for fact in extract_numeric_facts(section):
        if fact.ambiguous:
            continue
        candidates = [s for s in sources if s.kind==fact.kind and s.count==fact.count]
        # Unsupported numbers and missing numbers are handled by the existing
        # global checks; this check tests only their explicit associations.
        if candidates and not any(compatible(fact, candidate) for candidate in candidates):
            problems.append('unsupported numeric scope: '+fact.kind)
    return list(dict.fromkeys(problems))
