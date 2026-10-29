import copy
import json
import re
import unittest
from datetime import datetime
from pathlib import Path

from fact_registry import compile_registry, render_registry
from report_contract import publication_issues, review_input_digest
from event_brief import tidy

F=json.loads((Path(__file__).parent/'fixtures/source_core_20261023.json').read_text())
NOW=datetime.fromisoformat(F['status']['checked_at'])


def report(posts=None):
    registry=compile_registry(F['posts'] if posts is None else posts,F['status']['channels'],NOW)
    return registry,render_registry(registry)


class EventBriefTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry,cls.text=report()

    def test_one_residential_episode_not_three_source_messages(self):
        block=self.text.split('\nДніпро:\n')[1].split('\n\n')[0]
        self.assertEqual(block.count('11 приватних будинків'),1)
        self.assertNotIn('понад 10 осель',block)
        self.assertNotIn('Наслідки атаки росіян',block)
        self.assertNotIn('У Дніпрі виникла пожежа на території',block)
        self.assertEqual(block.count('Пожежу у приватному будинку ліквідовано'),1)
        self.assertIn('Одна оселя вигоріла вщент',block)

    def test_specific_date_and_new_morning_remain_separate(self):
        block=self.text.split('\nДніпро:\n')[1].split('\n\n')[0]
        self.assertIn('Удень 22 жовтня Новокодацький район Дніпра',block)
        self.assertIn('23 жовтня, у Дніпрі понівечена інфраструктура',block)
        self.assertNotIn('сьогоднішньої',self.text)
        self.assertNotIn('області області',self.text)

    def test_source_labels_are_audit_only_bulletin_clocks_are_not_attack_clocks(self):
        for phrase in ('Повідомлення від','За зведенням на','ОВА 22.10','ОВА 23.10'):
            self.assertNotIn(phrase,self.text)
        self.assertEqual(self.text.count('18:30'),1)
        self.assertEqual(self.text.count('07:30'),1)
        r=next(r for r in self.registry['records'] if r['source_key']=='DniproCityOfficial/15155')
        self.assertEqual(r['published_at'],'2026-10-22T11:55:34+00:00')
        self.assertIn('14:55',r['display'])
        self.assertIsNone(r['incident_time'])

    def test_all_material_numbers_and_severe_patient_survive(self):
        for phrase in ('більше ніж 20 вікон, 2 покрівлі','360 м кв.',
                       'У важкому стані до лікарні доправили 51-річного чоловіка',
                       '44-річний чоловік','26-річна жінка'):
            self.assertIn(phrase,self.text)
        self.assertEqual(self.text.count('Понад 50'),1)
        self.assertEqual(self.text.count('Майже 20'),1)
        self.assertNotIn('70 разів',self.text)

    def test_rescue_only_adds_unique_fire_status(self):
        self.assertEqual(self.text.count('спортивна школа'),1)
        self.assertEqual(self.text.count('Рятувальники ліквідували всі пожежі'),1)
        self.assertIn('Дніпровському, Криворізькому, Синельниківському та Кам’янському районах',self.text)

    def test_solonynska_and_shakhtarska_not_under_unrelated_geography(self):
        dn=self.text.split('\nДніпро:\n')[1].split('\n\n')[0]
        self.assertNotIn('Солонянській',dn)
        sy=self.text.split('\nСинельниківський район:\n')[1].split('\n\n')[0]
        self.assertIn('Раївській',sy)
        self.assertIn('Шахтарській',sy)
        self.assertIn('26-річна',sy)
        self.assertNotIn('44-річний',sy)

    def test_every_included_source_is_accounted_for_and_raw_text_not_overwritten(self):
        provenance=self.registry['public_projection']['provenance']
        accounted={i for p in provenance for i in p.get('record_ids',[])}
        accounted.update(p['covered_record_id'] for p in provenance if 'covered_record_id' in p)
        for r in self.registry['records']:
            if r['section']=='2.1' and r.get('display') and r['state']=='included':
                self.assertIn(r['id'],accounted)
        self.assertTrue(any('понад 10 осель' in r['source_text'] for r in self.registry['records']))
        self.assertTrue(any('сьогоднішньої атаки' in r['source_text'] for r in self.registry['records']))

    def test_equal_house_count_other_district_is_not_merged(self):
        posts=copy.deepcopy(F['posts'])
        for p in posts:
            if p['key']=='borys_filatovv/3741':
                p['text']=p['text'].replace('Новокодацького','Соборного')
        _,text=report(posts)
        self.assertGreaterEqual(text.count('11 приватних будинків'),2)

    def test_new_consequence_in_linked_update_cannot_disappear(self):
        posts=copy.deepcopy(F['posts'])
        for p in posts:
            if p['key']=='borys_filatovv/3741':
                p['text']+=' Пошкоджено дитячий садок.'
        _,text=report(posts)
        self.assertIn('дитячий садок',text)

    def test_additional_attack_marker_prevents_city_consolidation(self):
        posts=copy.deepcopy(F['posts'])
        for p in posts:
            if p['key']=='borys_filatovv/3741':
                p['text']='Повторна атака. '+p['text']
        _,text=report(posts)
        self.assertIn('Повторна атака',text)
        self.assertGreaterEqual(text.count('11 приватних будинків'),2)

    def test_unknown_rescue_fact_is_kept_instead_of_forcing_recap_template(self):
        posts=copy.deepcopy(F['posts'])
        for p in posts:
            if p['key']=='dsns_telegram/78537':
                p['text']+=' Пошкоджено амбулаторію.'
        _,text=report(posts)
        self.assertIn('амбулаторію',text)

    def test_contradictory_rescue_counter_not_silently_replaced(self):
        posts=copy.deepcopy(F['posts'])
        for p in posts:
            if p['key']=='dsns_telegram/78537':
                p['text']=p['text'].replace('понад 50','понад 60')
        _,text=report(posts)
        self.assertIn('понад 60',text)
        self.assertIn('Понад 50',text)

    def test_missing_projection_fact_blocks_publication(self):
        registry=copy.deepcopy(self.registry)
        registry['public_projection']['provenance']=[]
        self.assertIn('unaccounted_attack_fact',publication_issues(registry,self.text,F['status']['channels']))

    def test_raw_prose_regression_blocks_publication(self):
        for bad in ('Повідомлення від 12:55 22.10:','сьогоднішньої атаки','області області'):
            text=self.text.replace('Удень 22 жовтня',bad+' Удень 22 жовтня')
            self.assertIn('source_feed_prose',publication_issues(self.registry,text,F['status']['channels']))

    def test_all_frozen_days_fit_and_preserve_format(self):
        for day in ('20','21','22','23'):
            f=json.loads((Path(__file__).parent/f'fixtures/source_core_202610{day}.json').read_text())
            r=compile_registry(f['posts'],f['status']['channels'],datetime.fromisoformat(f['status']['checked_at']))
            text=render_registry(r)
            self.assertLessEqual(len(text.split()),500)
            self.assertEqual(re.findall(r'(?m)^([12]\.[1-4])\.',text),['1.1','1.2','2.1','2.2','2.3'])
            self.assertEqual(publication_issues(r,text,{}),[])

    def test_rule_uses_facts_not_fixed_house_count_or_calendar_date(self):
        posts=copy.deepcopy(F['posts'])
        for p in posts:
            p['text']=p['text'].replace('11 приватних будинків','13 приватних будинків').replace('2 покрівлі','3 покрівлі').replace('дві покрівлі','три покрівлі')
        _,text=report(posts)
        self.assertEqual(text.count('13 приватних будинків'),1)
        self.assertIn('3 покрівлі',text)
        self.assertIn('Одна оселя вигоріла вщент',text)

    def test_later_fire_update_does_not_lose_completion_status(self):
        posts=copy.deepcopy(F['posts'])
        for p in posts:
            if p['key']=='dnipropetrovskaODA/32743':
                p['published_at']='2026-10-22T14:00:00+00:00'
        _,text=report(posts)
        self.assertEqual(text.count('Пожежу у приватному будинку ліквідовано'),1)
        self.assertEqual(text.count('11 приватних будинків'),1)

    def test_absence_stays_on_regional_header_and_not_a_community(self):
        f=json.loads((Path(__file__).parent/'fixtures/source_core_20261022.json').read_text())
        r=compile_registry(f['posts'],f['status']['channels'],datetime.fromisoformat(f['status']['checked_at']))
        absence=next(x for x in r['records'] if x['source_text'].startswith('Всюди минулося'))
        projections=[p for p in r['public_projection']['provenance'] if absence['id'] in p.get('record_ids',[])]
        self.assertEqual(len(projections),1)
        self.assertEqual(projections[0]['place'],'Область')
        self.assertEqual(projections[0]['reporting_period'],absence['reporting_period'])

    def test_electricity_service_named(self):
        self.assertIn('підчерги електропостачання',self.text)
        self.assertLessEqual(len(self.text.split()),500)


if __name__=='__main__':
    unittest.main()
