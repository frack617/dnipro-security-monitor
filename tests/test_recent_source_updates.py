import copy
import json
import re
import unittest
from datetime import datetime
from pathlib import Path

from fact_registry import compile_registry, render_registry
from report_contract import publication_issues

ROOT=Path(__file__).parents[1]

def fixture(day):
    return json.loads((ROOT/f'tests/fixtures/source_core_202610{day}.json').read_text())

def render(day,posts=None):
    f=fixture(day)
    r=compile_registry(copy.deepcopy(f['posts'] if posts is None else posts),f['status']['channels'],datetime.fromisoformat(f['status']['checked_at']))
    return r,render_registry(r)


class RecentSourceUpdateTests(unittest.TestCase):
    def test_previous_night_header_controls_all_dsns_blocks(self):
        r,t=render('28')
        old=[r for r in r['records'] if r['source_key']=='dsns_telegram/78930']
        self.assertTrue(old)
        self.assertTrue(all(r['state']=='excluded' for r in old))
        self.assertNotIn('У Синельниківському районі травмовані 3 людей',t)
        self.assertNotIn('У Дніпрі та Кам’янському районі пошкоджена інфраструктура',t)

    def test_mixed_police_current_pavlograd_does_not_redate_other_blocks(self):
        r,t=render('29')
        blocks=[r for r in r['records'] if r['source_key']=='gunpvdp/37530']
        self.assertTrue(any(r['state']=='review' and 'два заклади освіти' in r['source_text'] for r in blocks))
        self.assertIn('вранці ворог атакував місто безпілотником',t)
        self.assertNotIn('Поранення отримали троє людей',t)
        self.assertNotIn('два заклади освіти',t)
        self.assertNotIn('Дніпровський район:\nДніпровський район',t)

    def test_explicit_current_police_block_is_retained(self):
        f=fixture('29');posts=copy.deepcopy(f['posts'])
        p=next(p for p in posts if p['key']=='gunpvdp/37530')
        p['text']=p['text'].replace('Дніпровський район.', 'Дніпровський район. Сьогодні 28 жовтня ворог атакував район.')
        r,t=render('29',posts)
        self.assertIn('два заклади освіти',t)

    def test_typed_patients_and_unique_diagnosis_survive_once(self):
        r,t=render('29')
        for age in ['15-річний','35-річний','73-річний','54-річна','62-річний']:
            self.assertEqual(t.count(age),1,age)
        for value in ['осколкові поранення','гаражному кооперативі','40 років','важкому стані','середньої тяжкості','амбулаторному лікуванні']:
            self.assertIn(value,t)
        self.assertNotIn('На Нікопольщині постраждали двоє людей',t)
        self.assertNotIn('травмувалися двоє людей',t)
        self.assertNotIn('Попередньо, ніхто не постраждав',t)
        self.assertIn('Його ушпиталили',t)
        changed=t.replace('У нього осколкові поранення.','')
        self.assertIn('lost_source_claim',publication_issues(r,changed,{}))

    def test_repeated_attack_at_same_industrial_site_is_not_one_episode(self):
        f=fixture('29');posts=copy.deepcopy(f['posts'])
        anchor=copy.deepcopy(next(p for p in posts if p['key']=='dnipropetrovskaODA/32895'))
        anchor.update(key='dnipropetrovskaODA/second-site',published_at='2026-10-28T18:10:00+00:00',
                      text='Ворог завдав удару по промисловому підприємству у Дніпрі. Зайнялася пожежа. Ще одна атака.')
        posts.append(anchor);r,t=render('29',posts)
        self.assertIn('Ще одна атака',t)
        records=[x for x in r['records'] if x['source_key']=='dnipropetrovskaODA/32896']
        self.assertTrue(any(x.get('display') for x in records))

    def test_unfamiliar_clinical_consequence_is_never_removed(self):
        f=fixture('29');posts=copy.deepcopy(f['posts'])
        next(p for p in posts if p['key']=='dnipropetrovskaODA/32896')['text']+=' Людині потрібна термінова операція.'
        r,t=render('29',posts)
        self.assertIn('Людині потрібна термінова операція.',t)

    def test_known_name_forms_corrected_without_inventing_unknown_names(self):
        from brief_editor import normalize_names
        for suffix,new in [('ської','цівської'),('ську','цівську'),('ській','цівській')]:
            self.assertIn('Верхів'+new,normalize_names('Верхівцев'+suffix+' громади'))
        self.assertEqual(normalize_names('Невідомська громада'),'Невідомська громада')
        r,t=render('29')
        self.assertFalse(r['review_required'])

    def test_new_contract_flags_empty_or_broken_public_text(self):
        r,t=render('29')
        self.assertIn('empty_geographic_body',publication_issues(r,t+'\n\nДніпровський район:\nДніпровський район.',{}))
        self.assertIn('raw_navigation_or_procedural_text',publication_issues(r,t+'\nЯк курсуватиме транспорт -',{}))

    def test_source_ledger_keeps_original_spelling_and_initial_assessment(self):
        r,t=render('29')
        self.assertTrue(any('Верхівцевську' in x['source_text'] for x in r['records']))
        self.assertTrue(any('Попередньо, ніхто не постраждав' in x['source_text'] for x in r['records']))
        self.assertTrue(any(x.get('assessment_history') for x in r['records']))
        self.assertEqual(t.count('Понад 40'),1)
        self.assertEqual(re.findall(r'(?m)^([12]\.\d)\.',t),['1.1','1.2','2.1','2.2','2.3'])
        for bad in ['Денне зведення','Ранкове зведення','За ранковими даними','їх не додають','описаний вище випадок']:
            self.assertNotIn(bad,t)

    def test_school_article_extracts_facts_without_app_instructions(self):
        from operational_facts import official_damage_excerpt
        f=fixture('28');p=next(p for p in f['posts'] if p['key']=='DniproCityOfficial/15352')
        excerpt=official_damage_excerpt(p)
        self.assertIsNotNone(excerpt)
        for fact in ['два заклади освіти','понад 100 вікон','футбольний стадіон','шести багатоповерхових будинках','близько 100 вікон']:
            self.assertIn(fact,excerpt)
        self.assertNotIn('App Store',excerpt)
        p=copy.deepcopy(p);p['text']+=' Евакуйовано 12 людей.'
        self.assertIsNone(official_damage_excerpt(p))

    def test_recent_replays_retain_all_unknown_claims(self):
        for day in ['27','28','29']:
            r,t=render(day)
            self.assertFalse([c for c in r['claim_plan'] if c['disposition']=='unresolved'],day)
            self.assertNotIn('lost_source_claim',publication_issues(r,t,{}),day)
