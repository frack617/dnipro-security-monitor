"""Local publication checks and stable, input-bound review decisions."""
import hashlib
import json
import re
import os
from datetime import datetime
from pathlib import Path


def publication_issues(registry, report, statuses, expected_channels=()):
    issues = []
    if len(report.split()) > 500:
        issues.append('length')
    if re.findall(r'(?m)^([12]\.[1-4])\.', report) != ['1.1','1.2','2.1','2.2','2.3']:
        issues.append('public_format')
    if re.search(r'Шановні\s+(?:споживачі|мешканці)|Перепрошуємо за тимчасові', report, re.I):
        issues.append('raw_address_to_readers')
    if re.search(r'Анонсовано відключення\s+\d', report, re.I):
        issues.append('unnamed_service')
    projection=registry.get('public_projection')
    if any(r.get('claims') for r in registry.get('records',[])):
        from source_claims import claim_plan
        if any(c['disposition']=='unresolved' for c in claim_plan(registry,report)):
            issues.append('lost_source_claim')
    if projection is not None:
        accounted={ident for item in projection['provenance'] for ident in item.get('record_ids',[])}
        accounted.update(item['covered_record_id'] for item in projection['provenance'] if 'covered_record_id' in item)
        if any(r['section']=='2.1' and r.get('display') and r['state'] not in {'mirror','excluded','review'}
               and r['id'] not in accounted for r in registry['records']):
            issues.append('unaccounted_attack_fact')
        attack=report.split('2.1. Обстріли',1)[-1].split('2.2. Незаконне',1)[0]
        if re.search(r'Повідомлення від|За зведенням на|сьогоднішньої атаки|області області',attack,re.I):
            issues.append('source_feed_prose')
    if projection is not None:
        from brief_editor import unsupported_incident_clocks,ALIASES
        if unsupported_incident_clocks(registry,report):
            issues.append('unsupported_incident_clock')
        if any(old in report for old in ALIASES):
            issues.append('unverified_community_spelling')
        if 'За звітний період зафіксовано атаки та їхні наслідки.' in report:
            issues.append('empty_security_overview')
    if expected_channels:
        channels = {k.casefold():v for k,v in statuses.items()}
        start = datetime.fromisoformat(registry['window']['start'])
        end = datetime.fromisoformat(registry['window']['end'])
        for name in expected_channels:
            status = channels.get(name.casefold(), {})
            try:
                covered = (status.get('ok') is True and status.get('coverage_complete') is True
                           and datetime.fromisoformat(status['coverage_from']) <= start
                           and datetime.fromisoformat(status['coverage_until']) >= end)
            except (ValueError, TypeError, KeyError):
                covered = False
            if not covered:
                issues.append('source_coverage:'+name)
    return issues


def review_input_digest(registry, report):
    # Audit records matter: a newly excluded source can change the review,
    # even when the rendered text is identical. Wall-clock/run ID do not.
    settings = {name:os.getenv(name, '') for name in
                ('REPORT_PROVIDER','GEMINI_MODEL','GEMINI_BACKUP_MODEL','GROQ_MODEL','REPORT_CORE_REVIEW')}
    payload = {'window':registry['window'], 'records':registry['records'], 'report':report,
               'review_settings':settings}
    digest = hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True).encode())
    for name in ('collector.py','fact_registry.py','operational_facts.py',
                 'fallback_report.py','core_review.py','report_contract.py','event_brief.py','brief_editor.py','source_claims.py','brief_budget.py','operational_prose.py','reference/communities_dp.json'):
        digest.update((Path(__file__).parent/name).read_bytes())
    return digest.hexdigest()


def reusable_review(previous, input_digest, report_date):
    review = previous.get('review', {})
    if (previous.get('report_date') == report_date
        and previous.get('review_input_sha256') == input_digest
        and review.get('state') in {'completed','concerns','invalid_response'}):
        return dict(review, requests=0, reused=True,
                    reused_from_run_id=previous.get('run_id'))
    return None
