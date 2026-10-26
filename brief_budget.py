"""Lossless layout compaction toward an advisory 500-word target.

Only editorial prefixes and repeated street-type labels are shortened. No
source assertion is removed, no casualty/address/date/clock is truncated.
If irreducible facts exceed the target, preserve them and allow delivery.
"""
import re


def group_streets(match):
    prefix,body=match.groups()
    if ';' in body or ':' in body:return match[0]
    entries=re.split(r',\s+(?=(?:вул\.|пров\.)\s)',body)
    groups={}
    for entry in entries:
        m=re.fullmatch(r'(вул\.|пров\.)\s+(.+)',entry)
        if not m:return match[0]
        groups.setdefault(m[1],[]).append(m[2])
    if len(entries)<2:return match[0]
    return prefix+'; '.join(('вулицях' if kind=='вул.' else 'провулках')+': '+', '.join(names)
                            for kind,names in groups.items())


def compact_overview(text):
    # This is the formatter's editorial overview, not a source assertion.
    pattern=r'(?m)^Зафіксовано атаки у (.+?), а також у громадах (.+?) районів\.'
    def replace(m):
        cities=m[1]
        for old,new in [('Дніпрі','Дніпро'),('Павлограді','Павлоград'),('Нікополі','Нікополь'),('Кривому Розі','Кривий Ріг'),('Самарі','Самар'),('передмісті Дніпра','передмістя Дніпра')]:
            cities=cities.replace(old,new)
        districts=re.sub(r'ського(?=,|$)', 'ський', m[2])
        districts=re.sub(r'зького(?=,|$)', 'зький', districts)
        return 'Атаки: '+cities+'; '+districts+' райони.'
    return re.sub(pattern,replace,text)


def fit_layout(report,limit=500):
    initial=len(report.split());operations=[]
    from operational_prose import concise
    transforms=[
        ('short_editorial_overview',lambda t:t.replace(
            'Офіційні джерела повідомили про атаки та їхні наслідки','Зафіксовано атаки')),
        ('short_bulletin_labels',lambda t:re.sub(r'(?m)^(?:Денне|Ранкове) зведення за ', 'За ',t)),
        ('short_dated_local_labels',lambda t:re.sub(r'За ранковими даними (\d{1,2} \w+)', r'Вранці \1',t)),
        ('compact_editorial_geography',compact_overview),
        ('bounded_operational_prose',concise),
        ('group_street_type_labels',lambda t:re.sub(
            r'(?m)(для окремих будинків на )((?:вул\.|пров\.)[^\n]+)(?=\.$)',group_streets,t)),
    ]
    for name,transform in transforms:
        if len(report.split())<=limit:break
        candidate=transform(report)
        if len(candidate.split())<len(report.split()):
            report=candidate;operations.append(name)
    return report,dict(limit=limit,initial_words=initial,final_words=len(report.split()),
                       operations=operations,status='fits' if len(report.split())<=limit else 'overflow')
