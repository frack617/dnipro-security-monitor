"""Source-bound records for the morning brief, independent of generative APIs.

Publication, incident time and bulletin reporting time are separate fields.
Uncertain material stays in the audit trail; it never becomes a new casualty.
This is a conservative source synopsis, not an assertion of complete coverage.
"""
import hashlib
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from report_preparation import prepare_evidence
from fallback_report import clean_lines, sentences, brief_service, weather_text, WEATHER, SERVICE
from report_rules import MONTHS

KYIV = ZoneInfo('Europe/Kyiv')
EMPTY = 'У перевірених джерелах повідомлень за звітний період не виявлено.'
REGIONAL = re.compile(r'дніпропетров|\bдніпр(?:о|і|а|у|ом)\b|криворі|крив(?:ий|ому|ого)\s+р(?:іг|озі|огу)|нікопол|синельник|павлоград|марганец|марганц|вільногір|обухів|новопіл', re.I)
NONLOCAL = re.compile(r'\bки(?:їв|єв)\w*|\bстолиц\w*|\bхарків\w*|\bодес\w*|\bльвів\w*|\bполтав\w*|\bзапоріж\w*|\bмиколаїв\w*|\bчеркас\w*|\bчерніг\w*|\bхерсон\w*|\bжитомир\w*|\bсум(?:и|ах|ськ)\w*|\bвінниц\w*|\bтерноп\w*|\bлуцьк\w*|\bужгород\w*', re.I)
BULLETIN_CHANNELS = {'adm_dp', 'dnipropetrovskaoda'}
DATE = re.compile(r'\b(\d{1,2})\s+('+'|'.join(MONTHS)+r')\b', re.I)
TIME = re.compile(r'(?<!\d)(\d{1,2}):(\d{2})(?!\d)')
PLACE = re.compile(r'^(?:(?:У|В|На)\s+)?([^.!?:]{1,100}?)(?=\s+(?:пошкоджен|понівечен|росіяни|ворог|противник|потерпал|загин|постраж|цілив|завдан)|[.:])', re.I)
CASUALTY = re.compile(r'поран|постраждал|загин|загиб|госпітал|до лікарні|лікуватим', re.I)
CONSEQUENCE = re.compile(r'пошкодж|понівеч|зруйн|пожеж|загин|загиб|поран|атак|обстріл|вдар|цілив', re.I)


def digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def normalized(text):
    return re.sub(r'[^\w]+', ' ', text.casefold()).strip()


def public_place(text):
    """Preserve the source's inflection and administrative level."""
    match = PLACE.search(clean_lines(text))
    return match[1].strip() if match else None


def bulletin_header(post):
    blocks = re.split(r'[▪●]\ufe0f?', post.get('text', ''))
    if post.get('channel', '').lower() not in BULLETIN_CHANNELS or len(blocks) < 3:
        return None
    header = clean_lines(blocks[0])
    date = DATE.search(header)
    time = TIME.search(header)
    if not date or not time or 'Дніпропетровщина' not in header:
        return None
    published = datetime.fromisoformat(post['published_at']).astimezone(KYIV)
    try:
        at = datetime(published.year, MONTHS.index(date[2].lower())+1, int(date[1]),
                      int(time[1]), int(time[2]), tzinfo=KYIV)
        if at > published + timedelta(days=1):
            at = at.replace(year=at.year-1)
    except ValueError:
        return None
    body = header[time.end():].strip(' .:')
    # The declared reporting clock identifies a bulletin slot, not a whole
    # publication date. Conflicting header assertions require manual review.
    return at, body, blocks[1:]


def make_record(post, section, text, *, scope=None, period=None, state='included', reason=None):
    from report_rules import asserted_counts
    key = post.get('key') or post.get('url') or digest(post.get('text', ''))
    return {
        'id': digest(key+'\0'+section+'\0'+text)[:20], 'section': section,
        'source_key': key, 'source_url': post.get('url', ''),
        'published_at': post.get('published_at'), 'source_text': text,
        'scope': scope, 'casualty_assertions': sorted(asserted_counts(text)), 'numbers': re.findall(r'\b\d+(?:[–-]\d+)?\b', text),
        'incident_time': None, 'incident_time_status': 'not_established',
        'reporting_period': period, 'state': state, 'reason': reason,
        'source_refs': [key], 'display': None,
    }


def shorter_attack(text):
    """Remove clinical age/status lists, never calculate a city total.

    Other consequence sentences and every community name remain verbatim.
    The original full block remains in the record for review.
    """
    kept, patients, child, patient_slot = [], False, False, None
    for sentence in sentences(clean_lines(text)):
        if re.search(r'\b(?:У важкому стані|У стані середньої тяжкості госпіталізовані|Чоловіки\s+\d)', sentence):
            patients = True
            if patient_slot is None:
                patient_slot = len(kept)
            child |= bool(re.search(r'(?:хлопець|дівчин\w*)\s+1[0-7]\b|дитин', sentence, re.I))
            continue
        if re.search(r'^Вона лікуватиметься амбулаторно', sentence):
            continue
        kept.append(sentence)
    if patients:
        kept.insert(patient_slot, 'Є поранені, зокрема дитина.' if child else 'Є поранені.')
    result = ' '.join(kept)
    return result if result.endswith(('.', '!', '?')) else result+'.'


def mirror_tokens(text):
    tokens = re.sub(r'\bгромад[аи]\b', 'громада', normalized(text)).split()
    return [t for t in tokens if t not in {'і', 'й', 'та', 'у', 'в', 'на', 'області'}]


def ordered_subset(shorter, longer):
    # Order is essential: swapped death/injury numbers have the same token set
    # but must never be accepted as a harmless mirrored statement.
    remaining = iter(longer)
    return all(any(token == candidate for candidate in remaining) for token in shorter)


def merge_mirrors(records, diagnostics):
    """Only same bulletin time/header AND geographic block can be mirrors.

    Prefer a verbatim superset. Non-subset differences are retained as a
    conflict for manual review; omission from a mirror is not a retraction.
    """
    slots, result = {}, []
    for record in records:
        slot = (record['reporting_period'], record['scope'] or record['id'])
        previous = slots.get(slot)
        if previous is None:
            slots[slot] = record
            result.append(record)
            continue
        a, b = mirror_tokens(previous['source_text']), mirror_tokens(record['source_text'])
        negation = lambda t: re.findall(r'\b(?:не|немає|спростовано|помилково|без)\b', t.casefold())
        compatible = negation(previous['source_text']) == negation(record['source_text'])
        if compatible and (ordered_subset(a, b) or ordered_subset(b, a)):
            winner, loser = (record, previous) if len(a) < len(b) else (previous, record)
            refs = sorted(set(previous['source_refs'] + record['source_refs']))
            winner['source_refs'] = refs
            loser['state'], loser['reason'] = 'mirror', 'verbatim_subset_same_bulletin'
            if winner is record:
                result[result.index(previous)] = record
                slots[slot] = record
        else:
            record['state'], record['reason'] = 'conflict', 'different_same_bulletin_scope'
            diagnostics.append({'reason': 'source_conflict', 'sources': previous['source_refs']+record['source_refs']})
            result.append(record)
    return result


def service_display(post, end):
    raw = post.get('text', '')
    # A restoration estimate without its own named affected area adds no useful
    # location-specific information. Do not infer that it updates another post.
    if (re.search(r'плануємо відновити електропостачання', raw, re.I)
        and not re.search(r'вул\.|просп\.|бульвар|проїзд', raw, re.I)):
        return None
    if WEATHER.search(raw) and not SERVICE.search(raw):
        return weather_text(post, end.date())
    text = brief_service(post, end.date())
    if text == EMPTY:
        return None
    # Historical outages are publication-dated, never declared active now.
    day = datetime.fromisoformat(post['published_at']).astimezone(KYIV)
    if re.search(r'повідомлено про знеструмлення', text, re.I):
        text = f'Повідомлення від {day:%d.%m}: '+text
    return text


def transport_display(posts, end):
    """Current notices only. Internal route identity remains untouched."""
    from fallback_report import brief_transport, publication_date
    current, excluded = [], []
    for post in posts:
        day = publication_date(post)
        text = post['text']
        # Expired one-day adjustments and resolved diversions are history, not
        # current travel restrictions. Persistent undated closures survive.
        expired = (day and day < end.date() and
                   re.search(r'сьогодні|відновлюється рух|збільшено кількість|закінчать свою роботу раніше|(?:з|до)\s+\d{1,2}:\d{2}', text, re.I))
        if expired:
            excluded.append(post)
        else:
            current.append(post)
    raw = brief_transport(current) if current else EMPTY
    if raw == EMPTY:
        return raw, excluded
    # Approved public simplifications are applied after exact route recovery.
    raw = re.sub(r'\b(?:автобус\w*|трамва\w*|тролейбус\w*)\s*№\s*\d+[А-Яа-яA-Za-z]*'
                 r'(?:\s*(?:та|і|й|,)\s*№?\s*\d+[А-Яа-яA-Za-z]*)*',
                 lambda m: re.sub(r'\s*№.*', '', m[0]), raw, flags=re.I)
    raw = re.sub(r'Кінцева зупинка автобусів перенесена', 'Кінцеву зупинку частини автобусного сполучення перенесено', raw, flags=re.I)
    raw = re.sub(r'Кінцев(?:а|у) зупинк[^.!?]*(?:пл\.|площу)\s*Успенськ\w*\.', '', raw, flags=re.I)
    raw = re.sub(r'Усі інші маршрути[^.!?]*[.!?]?', '', raw, flags=re.I)
    raw = re.sub(r'Схеми перекриття[^.!?]*[.!?]?', '', raw, flags=re.I)
    raw = re.sub(r'\.\s*Деталі\s*[—–-]?\s*\.', '.', raw)
    raw = re.sub(r'\s+', ' ', raw).strip()
    if re.search(r'обмеж|перекрит|призупин|ремонт', raw, re.I):
        pass
    return raw, excluded


def supplementary_covered(text, selected):
    """A preliminary casualty-only update is not a new independent total.

    Keep distinct new consequences, repeated-attack signals and unfamiliar
    places. No source is declared to describe the same incident here.
    """
    if re.search(r'знову|повторн|нов(?:ий|а|у)\s+(?:атак|удар)|критичн\w*\s+інфраструктур', text, re.I):
        return False
    region_blocks = [r for r in selected if r['scope'] != 'Дніпропетровська область']
    body = clean_lines(text)
    # Never suppress a place which is absent from the selected backbone.
    locality = re.search(r'крив(?:ий|ому|ого)\s+р(?:іг|озі|огу)|нікопол\w*|дніпр(?:о|і|а)\b', body, re.I)
    if not locality:
        return False
    stem = ('крив' if locality[0].casefold().startswith('крив') else
            'нікопол' if locality[0].casefold().startswith('нікопол') else 'дніпр')
    relevant = [r for r in region_blocks if stem in r['source_text'].casefold()]
    if not relevant:
        return False
    # If a unique material consequence is named, it must remain available in
    # the public synopsis rather than being overwritten by a general bulletin.
    consequence_objects = re.findall(r'підприємств\w*|склад\w*|пожеж\w*|будин\w*|магазин\w*|лікарн\w*|школ\w*|мост\w*|церкв\w*|азс\b', body, re.I)
    corpus = ' '.join(r['source_text'] for r in relevant).casefold()
    return all(obj.casefold() in corpus for obj in consequence_objects)


def regional_segments(posts, audit):
    """Do not copy a nationwide multi-region bulletin as one local event."""
    for post in posts:
        if post.get('channel', '').lower() not in {'sbukr', 'dsns_telegram'}:
            yield post
            continue
        pieces = re.split(r'[▪●]\ufe0f?', post.get('text', ''))
        if len(pieces) == 1:
            # A compound national prose story cannot be safely separated by
            # merely finding a regional keyword somewhere in it.
            if NONLOCAL.search(post['text']) and REGIONAL.search(post['text']):
                audit.append(make_record(post, '1.4', post['text'], state='review', reason='mixed_national_prose'))
            else:
                yield post
            continue
        for index, piece in enumerate(pieces):
            if REGIONAL.search(piece) and not NONLOCAL.search(piece):
                yield dict(post, text=piece.strip(), source_block=index)
            elif piece.strip():
                audit.append(make_record(post, '1.4', piece.strip(), state='excluded', reason='outside_or_uncertain_region_block'))


def compile_registry(posts, statuses, checked_at):
    import collector as c
    start, end, start_utc, end_utc = c.completed_report_window(checked_at)
    records, diagnostics = [], []
    candidates = prepare_evidence(c.report_window_posts(posts, checked_at))
    bulletins, ordinary = [], []
    # Retain a source audit entry for every candidate, including all exclusions.
    from operational_facts import background_reason, current_attack_piece, warehouse_supplement
    expanded = []
    for post in candidates:
        # Explicit geographic blocks of non-OVA summaries remain independent.
        pieces = re.split(r'[▪●]\ufe0f?', post['text'])
        if len(pieces) > 1 and post.get('channel','').lower() not in (BULLETIN_CHANNELS | {'sbukr', 'dsns_telegram'}):
            for i, piece in enumerate(pieces[1:]):
                if piece.strip():
                    expanded.append(dict(post, text=piece.strip(), source_block=i+1))
        else:
            expanded.append(post)
    for post in regional_segments(expanded, records):
        reason = background_reason(post['text'])
        if reason:
            records.append(make_record(post, '1.4', post['text'], state='excluded', reason=reason))
            continue
        section = c.classify_post(post)
        if not section:
            continue
        text = post['text']
        if section == '2.1' and not bulletin_header(post):
            published = datetime.fromisoformat(post['published_at']).astimezone(KYIV)
            filtered, reason = current_attack_piece(text, published, start, end)
            if reason:
                records.append(make_record(post, section, text, state='excluded' if filtered is None else 'review', reason=reason))
            if filtered is None:
                continue
            if filtered != text:
                post = dict(post, text=filtered)
                text = filtered
        if NONLOCAL.search(text) and not REGIONAL.search(text):
            records.append(make_record(post, section, text, state='excluded', reason='outside_region'))
            continue
        header = bulletin_header(post) if section == '2.1' else None
        if header:
            at, body, blocks = header
            period = at.isoformat()
            title = f'Обласне зведення на {at:%H:%M %d.%m.%Y}: '
            intro = make_record(post, section, body, scope='Дніпропетровська область', period=period)
            intro['display'] = title + body + ('' if body.endswith('.') else '.')
            intro['incident_time_status'] = 'regional_bulletin_period'
            bulletins.append(intro)
            for block in blocks:
                raw = clean_lines(block)
                rec = make_record(post, section, raw, scope=public_place(raw), period=period)
                rec['display'] = shorter_attack(raw)
                rec['incident_time_status'] = 'regional_bulletin_period'
                bulletins.append(rec)
        else:
            ordinary.append((post, section))
    selected = merge_mirrors(bulletins, diagnostics)
    records.extend(bulletins)
    cutoff_context = [p for p in posts if c.is_cutoff_bulletin(p, start)]
    transport, services = [], []
    for post, section in ordinary:
        text = post['text']
        rec = make_record(post, section, text, scope=public_place(text))
        if section == '2.1':
            # A morning attack on the start date, described later without a
            # clock, may predate 08:00. Matching anchors strengthen the reason
            # for review but are never treated as proof of identity.
            published = datetime.fromisoformat(post['published_at']).astimezone(KYIV)
            morning = re.search(r'ранков\w* атак|вранішньої атаки|зранку|від самого ранку', text, re.I)
            mixed = len(re.split(r'[▪●]', text)) > 1
            if (published.date() == start.date() and morning) or mixed:
                rec['state'], rec['reason'] = 'review', 'incident_time_or_mixed_episode_uncertain'
                rec['possible_prior_sources'] = [p['key'] for p in cutoff_context]
                diagnostics.append({'reason': rec['reason'], 'sources': [rec['source_key']]})
            elif (warehouse := warehouse_supplement(text, selected, published,
                    linked_update=any(p.get('reply_to') == post.get('key') for p in candidates))) is not None:
                if warehouse['conflict']:
                    rec['state'], rec['reason'] = 'review', 'warehouse_numeric_or_episode_conflict'
                    diagnostics.append({'reason':'source_conflict', 'sources':[rec['source_key']]})
                elif warehouse['display']:
                    rec['display'] = warehouse['display']
                    selected.append(rec)
                else:
                    rec['state'], rec['reason'] = 'supplement', 'warehouse_facts_in_dated_bulletin'
            elif selected and supplementary_covered(text, selected):
                # Periodic bulletins form the synopsis. The supplementary post
                # remains auditable and is not silently declared the same event.
                rec['state'], rec['reason'] = 'supplement', 'not_independently_merged_with_bulletin'
                rec['display'] = None
            else:
                body = clean_lines(text)
                kept = [s for s in sentences(body) if CONSEQUENCE.search(s) and not re.search(
                    r'Залишайтеся|Загроза триває|До відбою', s, re.I)]
                if kept:
                    rec['display'] = f'Повідомлення від {published:%H:%M %d.%m}: '+' '.join(kept)
                    rec['display'] = re.sub(r'\bатакує\b', 'атакував', rec['display'])
                    selected.append(rec)
                else:
                    rec['state'], rec['reason'] = 'excluded', 'no_concrete_consequence'
        elif section == '1.2':
            transport.append(post)
            rec['state'] = 'service_input'
        elif section == '1.4':
            display = service_display(post, end)
            if display:
                rec['display'] = display
                selected.append(rec)
                services.append(rec)
            else:
                rec['state'], rec['reason'] = 'excluded', 'no_current_location_specific_information'
        else:
            from fallback_report import clean_event
            attribution = ('За даними СБУ, ' if post.get('channel','').casefold() == 'sbukr' else
                           'За даними поліції, ' if post.get('channel','').casefold() == 'gunpvdp' else '')
            rec['display'] = 'Повідомлення від '+datetime.fromisoformat(post['published_at']).astimezone(KYIV).strftime('%d.%m %H:%M')+': '+attribution+clean_event(post)
            selected.append(rec)
        records.append(rec)
    transport_text, expired = transport_display(transport, end)
    for rec in records:
        if rec['source_key'] in {p['key'] for p in expired}:
            rec['state'], rec['reason'] = 'excluded', 'expired_transport_notice'
    sections = {key: [] for key in ('1.1','1.2','1.3','1.4','2.1','2.2','2.3','2.4')}
    selected.sort(key=lambda r: ((r['reporting_period'] or r['published_at']).split('|')[0], 0 if r['scope'] == 'Дніпропетровська область' else 1))
    for rec in selected:
        if rec.get('display') and rec['state'] != 'mirror':
            sections[rec['section']].append(rec['display'])
    # Bulletins remain chronological; no regrouping by city across dates.
    sections['1.1'] = ['У перевірених джерелах є повідомлення про атаки або їхні наслідки. Деталі наведено у пункті 2.1.'] if sections['2.1'] else [EMPTY]
    sections['1.2'] = [] if transport_text == EMPTY else [transport_text]
    utility = ' '.join(sections['1.4'])
    if re.search(r'знеструмлен|відключен|електроенергі', utility, re.I):
        pass  # General preparedness advice is outside this evidence synopsis.
    if re.search(r'туман|видиміст', utility, re.I) and not sections['1.2']:
        sections['1.4'].append('Під час виїздів врахувати можливе збільшення часу в дорозі через погіршення видимості.')
    missing = [name for name, value in statuses.items() if not value.get('ok')]
    coverage_unproven = not statuses or any(not s.get('coverage_complete') for s in statuses.values())
    return {'version': 1, 'window': {'start': start.isoformat(), 'end': end.isoformat()},
            'checked_at': checked_at.isoformat(), 'records': records, 'diagnostics': diagnostics,
            'sections': sections, 'failed_sources': missing, 'coverage_unproven': coverage_unproven,
            'review_required': any(d['reason'] == 'source_conflict' for d in diagnostics)}


def render_registry(registry):
    """Render immutable paragraphs with fixed geographic and temporal scopes."""
    from report_layout import PUBLIC_TITLES
    end = datetime.fromisoformat(registry['window']['end'])
    lines = ['Станом на '+end.strftime('%d.%m.%Y %H.%M')]
    sections = registry['sections']
    general = list(sections['1.1']) + list(sections['1.2']) + list(sections['1.4'])
    public = {'1.1': general, '1.2': sections['1.3'], '2.1': sections['2.1'],
              '2.2': sections['2.2']+sections['2.3'], '2.3': sections['2.4']}
    for group, heading in ((1, 'ЗАГАЛЬНА СИТУАЦІЯ В ОБЛАСТІ (РАЙОНІ)'), (2, 'ПОДІЇ У СФЕРІ БЕЗПЕКИ')):
        lines += ['', f'{group}. {heading}']
        for key, title in PUBLIC_TITLES.items():
            if key.startswith(str(group)+'.'):
                lines += ['', (key+'. '+title).rstrip(), '\n\n'.join(public[key]) or EMPTY]
    start = datetime.fromisoformat(registry['window']['start'])
    lines += ['', f'Огляд за період {start:%d.%m.%Y %H:%M} — {end:%d.%m.%Y %H:%M}. Для негайних дій слід стежити за офіційними сповіщеннями про тривогу.']
    if registry['failed_sources']:
        lines.append('Обмеження перевірки: не отримано актуальні дані з '+', '.join('@'+n for n in registry['failed_sources'])+'.')
    elif registry['coverage_unproven']:
        lines.append('Повнота охоплення всіх повідомлень каналів не підтверджена.')
    if registry['review_required']:
        lines.append('Є розбіжності між джерелами; довідка потребує перевірки перед надсиланням.')
    return '\n'.join(lines).strip()


def validate_core_text(text, registry):
    """No prose validator is allowed to certify a changed protected core."""
    expected = render_registry(registry)
    if text != expected:
        raise ValueError('protected factual core changed')
    return text
