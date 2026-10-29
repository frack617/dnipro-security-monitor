import copy
import json
import os
import re
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from fact_registry import compile_registry,render_registry
from report_contract import publication_issues
from casualty_links import child_signatures,TOTALS_NOTE

ROOT=Path(__file__).resolve().parents[1]
F=json.loads((ROOT/'tests/fixtures/source_core_20261025.json').read_text())
NOW=datetime.fromisoformat(F['status']['checked_at'])


def render(posts=None):
    r=compile_registry(copy.deepcopy(F['posts'] if posts is None else posts),F['status']['channels'],NOW)
    return r,render_registry(r)


def sample(age=9,girl=False,count=4):
    child='дівчинка' if girl else 'хлопець';suffix='а' if girl else 'ий'
    detail=f'24 жовтня ворог атакував Покровську громаду Нікопольщини безпілотником. Поранено {count} людей. {age}-річн{suffix} {child} у тяжкому стані. Пошкоджено лікарню.'
    summary=f'Дніпропетровщина\n24 жовтня\n18:30\nПонад 10 разів ворог атакував два райони області.\n▪️\nУ Дніпрі пошкоджена інфраструктура.\n▪️\nНа Нікопольщині потерпали Покровська та Марганецька громади. Ще четверо людей, серед яких {age}-річн{suffix} {child}, постраждали.'
    return [dict(key='adm_dp/test-event',channel='adm_dp',published_at='2026-10-24T10:00:00+00:00',url='https://example.invalid/event',text=detail),
            dict(key='dnipropetrovskaODA/test-summary',channel='dnipropetrovskaODA',published_at='2026-10-24T15:30:00+00:00',url='https://example.invalid/summary',text=summary)]


class CasualtySummaryTests(unittest.TestCase):
    def test_real_day_mentions_the_child_once_and_keeps_clinical_details(self):
        r,t=render()
        self.assertEqual(len(r['casualty_summary_links']),1)
        self.assertEqual(len(re.findall(r'14-річ',t)),1)
        for fact in ['14-річного хлопчика','обласної лікарні Дніпра','Його стан тяжкий',
                     '46-річний чоловік у тяжкому стані']:
            self.assertIn(fact,t)
        self.assertEqual(publication_issues(r,t,{}),[])
        self.assertFalse([c for c in r['claim_plan'] if c['disposition']=='unresolved'])
        self.assertTrue(any(c['source_text'].startswith('Ще четверо людей, серед яких 14-річний') for c in r['claim_plan']))

    def test_rule_is_not_tied_to_fourteen_or_boy(self):
        for age,girl in [(9,False),(17,True),(12,True)]:
            r,t=render(sample(age,girl))
            self.assertEqual(len(r['casualty_summary_links']),1,(age,girl))
            self.assertEqual(len(re.findall(str(age)+r'-річ',t)),1)
            self.assertIn('у тяжкому стані',t)
            self.assertEqual(publication_issues(r,t,{}),[])

    def test_different_age_sex_count_day_or_community_is_not_deduplicated(self):
        changes=[lambda p:p[1].update(text=p[1]['text'].replace('9-річний','10-річний')),
                 lambda p:p[1].update(text=p[1]['text'].replace('9-річний хлопець','9-річна дівчинка')),
                 lambda p:p[0].update(text=p[0]['text'].replace('Поранено 4','Поранено 5')),
                 lambda p:p[0].update(published_at='2026-10-25T04:00:00+00:00'),
                 lambda p:p[0].update(text=p[0]['text'].replace('Покровську','Мирівську'))]
        for change in changes:
            posts=sample();change(posts);r,t=render(posts)
            self.assertEqual(r['casualty_summary_links'],[])
            self.assertIn('Ще четверо людей, серед яких',t)

    def test_two_distinct_events_with_same_age_are_not_one_person(self):
        posts=sample();other=copy.deepcopy(posts[0]);other['key']='adm_dp/another'
        other['text']=other['text'].replace('24 жовтня ворог','24 жовтня о 16:20 ворог')+' Врятовано 7 мешканців.'
        posts.append(other);r,t=render(posts)
        self.assertEqual(r['casualty_summary_links'],[])
        self.assertIn('Врятовано 7 мешканців.',t)
        self.assertIn('Ще четверо людей, серед яких',t)

    def test_ready_text_gate_rejects_repeat_even_when_it_is_paraphrased(self):
        r,t=render();old=r['casualty_summary_links'][0]['source_text']
        for duplicate in [old,'У районі також постраждав 14-річний хлопець.']:
            changed=t.replace('Нікопольщина:\n', 'Нікопольщина:\n'+duplicate+' ')
            self.assertIn('duplicate_casualty_detail',publication_issues(r,changed,{}))

    def test_reference_without_age_or_hospital_fact_cannot_cover_original(self):
        r,t=render()
        for phrase in ['14-річного хлопчика госпіталізували до обласної лікарні Дніпра.',
                       'Його стан тяжкий.']:
            self.assertIn(phrase,t)
            self.assertIn('lost_source_claim',publication_issues(r,t.replace(phrase,''),{}))
        wrong_date=t.replace('24 жовтня на Нікопольщині','23 жовтня на Нікопольщині')
        self.assertIn('unresolved_casualty_summary',publication_issues(r,wrong_date,{}))

    def test_regional_and_event_totals_are_not_added(self):
        r,t=render()
        for fact in ['Понад 60','Понад 20','14 дорослих і дитина','14 дістали поранень','травмовані 12']:
            self.assertIn(fact,t)
        self.assertNotIn(TOTALS_NOTE,t)
        self.assertEqual(publication_issues(r,t,{}),[])

    def test_duplicate_is_flagged_for_human_review_without_suppressing_delivery(self):
        import collector as c
        real_render=render_registry
        def inject(registry):
            return real_render(registry).replace('Нікопольщина:\n',
                'Нікопольщина:\nУ районі постраждав 14-річний хлопець. ')
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            with patch.object(c,'DATA_DIR',root),patch.object(c,'MORNING_REPORT_FILE',root/'morning_report.md'), \
                 patch.object(c,'read_alert_state',return_value={'last_daily_report':'2026-10-24'}), \
                 patch.dict(os.environ,{'PRODUCTION_MONITOR':'true','SEND_MORNING_REPORT':'true','FORCE_MORNING_REPORT':'false'}), \
                 patch('fact_registry.render_registry',side_effect=inject),patch('core_review.review_core') as reviewer, \
                 patch.object(c,'deliver_morning_report') as send,patch.object(c,'send_bot_message'):
                c.process_morning_report(F['posts'],F['status']['channels'],NOW)
                reviewer.assert_not_called();send.assert_called_once()
                self.assertIn('duplicate_casualty_detail',json.loads((root/'report_generation_status.json').read_text())['publication_issues'])


if __name__=='__main__':unittest.main()
