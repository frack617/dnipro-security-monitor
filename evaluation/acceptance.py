"""Offline end-product acceptance, separate from implementation unit tests.

Exit 1 means this candidate must not be called release-ready. This runner is
not wired into collection: a failing candidate test must not stop monitoring.
It copies the repo, strips credentials and blocks HTTP and socket connections.
It never invokes collector.main, generation providers or real delivery.
"""
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import random
import re
import shutil
import subprocess
import sys
import tempfile

HERE=Path(__file__).resolve().parent


def norm(text):
    return ' '.join(text.casefold().replace('ʼ','’').replace("'",'’').split())


def section(text, key):
    # Deliberately no production helpers or production classification rules.
    m=re.search(r'(?m)^'+re.escape(key)+r'\.[^\n]*\n',text)
    if not m:return ''
    end=re.search(r'(?m)^[12]\.\d\.',text[m.end():])
    return text[m.end():m.end()+end.start()] if end else text[m.end():]


def scoped(text, requirement):
    body=section(text,requirement['section'])
    place=requirement.get('scope')
    if not place:return body
    m=re.search(r'(?m)^'+re.escape(place)+r':\n([^\n]+)',body)
    return m[1] if m else ''


def oracle(text, spec):
    failures=[]
    for item in spec.get('required',[]):
        options=[item['fragment']]+item.get('alternatives',[])
        if not any(norm(value) in norm(scoped(text,item)) for value in options):
            failures.append(dict(code='missing_required_fact',**item))
    for item in spec.get('forbidden',[]):
        if norm(item['fragment']) in norm(scoped(text,item)):
            failures.append(dict(code='forbidden_claim',**item))
    for item in spec.get('max_occurrences',[]):
        count=norm(scoped(text,item)).count(norm(item['fragment']))
        if count>item['count']:
            failures.append(dict(code='duplicate_fact',actual=count,**item))
    if len(text.split())>500:failures.append(dict(code='over_500_words',actual=len(text.split())))
    if re.findall(r'(?m)^([12]\.\d)\.',text)!=['1.1','1.2','2.1','2.2','2.3']:
        failures.append(dict(code='public_format'))
    return failures


def evaluate(spec, compile_registry, render_registry, publication_issues):
    statuses=spec.get('statuses',{})
    registry=compile_registry(spec['posts'],statuses,datetime.fromisoformat(spec['checked_at']))
    text=render_registry(registry)
    local=publication_issues(registry,text,statuses)
    failures=oracle(text,spec)
    blocked=bool(registry['review_required'] or local)
    if spec.get('expect_publishable') and blocked:
        failures.append(dict(code='unexpected_publication_block',issues=local))
    return text,dict(id=spec['id'],passed=not failures,words=len(text.split()),
                     local_gate_accepted=not blocked,failures=failures,
                     report_sha256=hashlib.sha256(text.encode()).hexdigest())


def archived_specs(repo):
    expectations={
        '20': [('Кривий Ріг','Двоє людей загинули'),('Кривий Ріг','У важкому стані'),('Нікопольщина','25-річна жінка'),
               ('Синельниківський район','Українській')],
        '21': [('Дніпро','Четверо людей дістали поранень'),('Синельниківський район','65-річного'),
               ('Криворіжжя','66-річний')],
        '22': [('Кам’янський район','П’ятихатській'),('Нікопольщина','Мирівській')],
        '23': [('Дніпро','11 приватних будинків'),('Дніпро','360 м кв'),
               ('Нікопольщина','51-річного'),('Синельниківський район','26-річна жінка')],
        '24': [('Дніпро','щонайменше 5 приватних осель'),('Дніпро','восьмеро поранених'),
               ('Передмістя Дніпра','26-річний чоловік у вкрай тяжкому стані'),
               ('Дніпровський район','66 і 46 років'),('Синельниківський район','Васильківській')],
    }
    for day,items in expectations.items():
        data=json.loads((HERE/'archives'/f'source_core_202610{day}.json').read_text())
        required=[dict(section='2.1',scope=p,fragment=f) for p,f in items]
        if day=='20':required[1]['alternatives']=['тяжкому стані','важкий стан','тяжкий стан']
        yield dict(id='archive_202610'+day,posts=data['posts'],
                   statuses=data['status']['channels'],checked_at=data['status']['checked_at'],
                   required=required,
                   expect_publishable=True)


def worker(repo,out):
    sys.path.insert(0,str(repo))
    from unittest.mock import patch
    # Defence in depth: tests must not spend quota or send anything even if a
    # future import accidentally takes a live path.
    with patch('requests.sessions.Session.request',side_effect=AssertionError('HTTP forbidden in acceptance')), \
         patch('socket.socket.connect',side_effect=AssertionError('Network forbidden in acceptance')):
        from fact_registry import compile_registry,render_registry
        from report_contract import publication_issues
        out.mkdir(parents=True,exist_ok=True)
        reports=out/'reports';reports.mkdir(exist_ok=True)
        groups={};renders={}
        manifest=json.loads((HERE/'cases/SHA256SUMS.json').read_text())
        for name,expected in manifest.items():
            if hashlib.sha256((HERE/name).read_bytes()).hexdigest()!=expected:
                raise ValueError('Frozen cases changed: '+name)
        sets={'archive_regression':list(archived_specs(repo))}
        sets.update({name:json.loads((HERE/'cases'/f'{name}.json').read_text())
                     for name in ['discovery','validation','qualification']})
        for name,specs in sets.items():
            results=[]
            for spec in specs:
                text,result=evaluate(spec,compile_registry,render_registry,publication_issues)
                results.append(result);renders[spec['id']]=(text,spec)
                (reports/(spec['id']+'.txt')).write_text(text+'\n')
            groups[name]=results
        # Invariance, tested on complete reports. Exact input duplicates and
        # order changes may not alter a factual result; timestamps/keys remain.
        metamorphic=[]
        for spec in sets['archive_regression']:
            original=renders[spec['id']][0]
            for seed in [17,43,109]:
                changed=dict(spec,posts=list(spec['posts']))
                random.Random(seed).shuffle(changed['posts'])
                text,result=evaluate(changed,compile_registry,render_registry,publication_issues)
                metamorphic.append(dict(id=spec['id']+f'_shuffle_{seed}',passed=text==original))
            changed=dict(spec,posts=spec['posts']+spec['posts'])
            text,result=evaluate(changed,compile_registry,render_registry,publication_issues)
            metamorphic.append(dict(id=spec['id']+'_duplicate_input',passed=text==original))
        groups['metamorphic']=metamorphic
        # Test the evaluator itself: a permissive oracle can make a broken
        # renderer look good. Corrupt actual output and require detection.
        mutants=[]
        for ident,(text,spec) in renders.items():
            for index,item in enumerate(spec.get('required',[])):
                fragment=item['fragment']
                # Controlled missing-fact mutation; changes all occurrences.
                altered=re.sub(re.escape(fragment),'[вилучено]',text,flags=re.I)
                if altered==text:continue
                detected=any(f['code']=='missing_required_fact' for f in oracle(altered,spec))
                mutants.append(dict(id=f'{ident}_remove_{index}',passed=detected))
            places={r.get('scope') for r in spec.get('required',[]) if r.get('scope')}
            for place in sorted(places):
                altered=text.replace(place+':\n','Інша територія:\n')
                if altered!=text:
                    mutants.append(dict(id=f'{ident}_wrong_scope_{place}',
                                        passed=bool(oracle(altered,spec))))
        groups['oracle_mutations']=mutants
        summary={name:dict(total=len(rows),passed=sum(r['passed'] for r in rows),
                           failed=sum(not r['passed'] for r in rows)) for name,rows in groups.items()}
        ready=all(r['passed'] for rows in groups.values() for r in rows)
        runtime=hashlib.sha256()
        for path in sorted(repo.glob('*.py'))+sorted((repo/'reference').glob('*.json')):
            runtime.update(str(path.relative_to(repo)).encode()+b'\0'+path.read_bytes())
        report=dict(baseline_repository_commit='4eb466afc6c29c46baf07e82d1beacca3610ca0f',
                    evaluated_runtime_sha256=runtime.hexdigest(),
                    evaluation_code_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                    python_version=sys.version,corpus_sha256=manifest,
                    release_ready=ready,groups=groups,summary=summary,
                    limits=['Synthetic validation is fictional, not independent verification of real sources.',
                            '20–24 October are development regressions, not held-out days.',
                            'AI and Telegram are disabled; this does not establish live delivery or punctuality.'])
        (out/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps(dict(release_ready=ready,summary=summary),ensure_ascii=False,indent=2))
        return 0 if ready else 1


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--repo',type=Path,default=HERE.parent)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--worker',action='store_true',help=argparse.SUPPRESS)
    args=parser.parse_args();repo=args.repo.resolve();out=args.output.resolve()
    if args.worker:return worker(repo,out)
    env={k:v for k,v in os.environ.items() if not(k.endswith('_KEY') or k.endswith('_TOKEN')
          or k in {'TELEGRAM_CHAT_ID','PYTHONPATH','GITHUB_ACTIONS','GITHUB_RUN_ID'})}
    env.update(SEND_MORNING_REPORT='false',SEND_OPERATIONAL_ALERTS='false',REPORT_CORE_REVIEW='false')
    with tempfile.TemporaryDirectory(prefix='dnipro-acceptance-') as td:
        copied=Path(td)/'candidate'
        shutil.copytree(repo,copied,ignore=shutil.ignore_patterns('.git','__pycache__','.venv','venv'))
        # Also works when the acceptance kit is outside the candidate repo.
        # The frozen input corpus comes from this kit, not editable candidate
        # test fixtures. Only production modules come from --repo.
        shutil.copytree(HERE,copied/'evaluation',dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns('__pycache__'))
        return subprocess.run([sys.executable,str(copied/'evaluation/acceptance.py'),
                               '--worker','--repo',str(copied),'--output',str(out)],
                              cwd=copied,env=env).returncode


if __name__=='__main__':raise SystemExit(main())
