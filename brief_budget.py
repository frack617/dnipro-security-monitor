"""Lossless layout compaction before the 500-word publication gate.

Only editorial prefixes and repeated street-type labels are shortened. No
source assertion is removed, no casualty/address/date/clock is truncated.
If irreducible facts exceed the agreed budget, the final gate still blocks.
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


def fit_layout(report,limit=500):
    initial=len(report.split());operations=[]
    transforms=[
        ('short_editorial_overview',lambda t:t.replace(
            'Офіційні джерела повідомили про атаки та їхні наслідки','Зафіксовано атаки')),
        ('short_bulletin_labels',lambda t:re.sub(r'(?m)^(?:Денне|Ранкове) зведення за ', 'За ',t)),
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
