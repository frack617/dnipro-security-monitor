"""Delivery-first source drafts. Validation concerns remain visible and auditable."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

KYIV = ZoneInfo('Europe/Kyiv')
HEADINGS = {
    '1.1': 'Загальна ситуація, транспортні та комунальні обмеження',
    '1.2': 'Сповіщення про проведення військових тренувань, навчань чи вибухонебезпечних робіт',
    '2.1': 'Обстріли, ракетні атаки та атаки БпЛА',
    '2.2': 'Незаконне поводження зі зброєю та вибухівкою / Резонансні правоохоронні операції',
    '2.3': 'Виявлення вибухонебезпечних предметів (ВНП)',
}


def draft_notice(report, issues, review, conflict):
    reasons = []
    if any(code.startswith('source_coverage:') for code in issues):
        reasons.append('не підтверджено повне читання всіх джерел')
    if conflict:
        reasons.append('є невирішені питання до джерельних даних')
    if issues:
        reasons.append('є зауваження автоматичних перевірок')
    if review.get('issues'):
        reasons.append('є зауваження модельної перевірки')
    if review.get('state') in {'unavailable', 'invalid_response'}:
        reasons.append('модельна перевірка не завершена')
    notice = ('⚠️ Автоматична довідка для подальшої вичитки. '
              + '; '.join(reasons) + '. Повноту та коректність тексту ще не підтверджено.')
    return report + '\n\n' + notice


def reserve_report(posts, checked_at):
    """Preserve source quotations, explicitly using publication dates, not event dates.

    Only a conservative publication window is used if the main generator fails.
    This is a source brief, not a newly inferred summary of casualties or attacks.
    """
    import collector as c
    end = checked_at.astimezone(KYIV).replace(hour=8, minute=0, second=0, microsecond=0)
    start = end - timedelta(days=1)
    sections = {key: [] for key in HEADINGS}
    seen = set()
    for post in posts:
        try:
            published = datetime.fromisoformat(post['published_at'].replace('Z', '+00:00')).astimezone(KYIV)
            text = post.get('text', '').strip()
            if not (start <= published < end) or not text or not c.is_regional(post):
                continue
            category = c.classify_post(post)
            if not category:
                continue
            public = {'1.1':'1.1', '1.2':'1.1', '1.3':'1.2', '1.4':'1.1',
                      '2.1':'2.1', '2.2':'2.2', '2.3':'2.2', '2.4':'2.3'}[category]
            if text in seen:
                continue
            seen.add(text)
            # No source instruction is interpreted as executable code or as a report rule.
            quoted = '\n'.join('> '+line for line in text.splitlines())
            sections[public].append('Джерело @'+str(post.get('channel','невідоме'))+
                '; опубліковано '+published.strftime('%d.%m.%Y %H:%M')+
                ' за Києвом (це не встановлений час події).\n'+quoted+'\n'+str(post.get('url','')))
        except (ValueError, TypeError, KeyError, AttributeError):
            continue
    lines = ['Станом на '+end.strftime('%d.%m.%Y 08.00'),
             '⚠️ Резервна джерельна довідка: основне формування не завершилося. '
             'Нижче наведено джерельні тексти без узгодження уточнень; вони потребують вичитки. '
             'Відбір за часом публікації не підтверджує дату кожної описаної події.',
             'Звітний період: '+start.strftime('%d.%m.%Y %H:%M')+' — '+end.strftime('%d.%m.%Y %H:%M')+' за Києвом.']
    for key, title in HEADINGS.items():
        if key == '1.1':
            lines.append('1. ЗАГАЛЬНА СИТУАЦІЯ В ОБЛАСТІ (РАЙОНІ)')
        elif key == '2.1':
            lines.append('2. ПОДІЇ У СФЕРІ БЕЗПЕКИ')
        lines.append(key+'. '+title)
        lines.append('\n\n'.join(sections[key]) or
                     'Підтвердженого викладу для цього пункту не сформовано. '
                     'Це не означає відсутності подій; повноту джерел не підтверджено.')
    return '\n\n'.join(lines)
