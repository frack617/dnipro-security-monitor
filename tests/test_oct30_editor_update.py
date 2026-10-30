"""Real-input regression and adversarial boundaries for the Oct 30 failures."""
import copy
import json
import re
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from fact_registry import compile_registry, render_registry
from report_contract import publication_issues
from operational_facts import has_operational_attack_assertion
from operational_notices import emergency_transport, notice_kind
from source_claims import selected_text

ROOT=Path(__file__).parents[1]


def render(posts=None,day='30'):
    f=json.loads((ROOT/f'tests/fixtures/source_core_202610{day}.json').read_text())
    with patch('requests.sessions.Session.request',side_effect=AssertionError('No HTTP in replay')):
        r=compile_registry(copy.deepcopy(f['posts'] if posts is None else posts),f['status']['channels'],datetime.fromisoformat(f['status']['checked_at']))
        return r,render_registry(r)


class Oct30EditorTests(unittest.TestCase):
    def test_latest_mortality_is_admitted_and_earlier_counts_archived(self):
        r,t=render()
        self.assertIn('Кількість загиблих унаслідок цієї атаки зросла до 15.',t)
        self.assertNotIn('13 людей загинули',t)
        self.assertNotIn('14 людей загинули',t)
        self.assertNotIn('Ще десять людей постраждали',t)
        self.assertIn('14 поранених через атаку росіян на залізничний вокзал',t)
        original=next(x for x in r['records'] if x['source_key']=='dnipropetrovskaODA/32950')
        self.assertIn('помер 40-річний чоловік',original['source_text'])
        self.assertNotEqual(original['state'],'excluded')
        self.assertTrue(any(x.get('assessment_history') for x in r['records']))
        self.assertNotIn('lost_source_claim',publication_issues(r,t,{}))

    def test_no_arithmetic_on_a_patient_who_later_dies(self):
        r,t=render()
        self.assertNotIn('13 поранених через атаку',t)
        self.assertNotIn('29 людей',t)
        self.assertNotIn('32 людини',t)
        changed=t.replace('Кількість загиблих унаслідок цієї атаки зросла до 15.','')
        self.assertIn('lost_source_claim',publication_issues(r,changed,{}))

    def test_current_utility_and_transport_survive_without_ai(self):
        r,t=render()
        general=t.split('1.2. Сповіщення')[0]
        for value in ['Дніпро знову знеструмлений','від генераторів','діють екстрені відключення','не діють','Метро працює з інтервалом 16 хвилин','призупинено рух низки']:
            self.assertIn(value,general)
        self.assertNotIn('ВАЖЛИВА ІНФОРМАЦІЯ',general)
        self.assertIn('contradictory_route_status_in_one_notice',[x.get('detail') for x in r['diagnostics']])
        self.assertNotIn('всіх трамвайних та тролейбусних маршрутів зупинено',general)
        self.assertNotIn('автономним ходом',general)

    def test_boilerplate_removed_but_water_period_and_evacuation_stay(self):
        _,t=render()
        for bad in ['App Store','Google Play','«Соціальні послуги»','санкції проти Москви','Час нових','Мої співчуття','дякує своїм абонентам']:
            self.assertNotIn(bad,t)
        for value in ['22:00 години 30 жовтня','22:00 години 1 листопада','12:00 години 2 листопада','Новокодацькому','Чечелівському','Студентів переселятимуть','осколкові поранення','11-річний хлопчик','15 та 16 років']:
            self.assertIn(value,t)
        self.assertEqual(re.findall(r'(?m)^([12]\.\d)\.',t),['1.1','1.2','2.1','2.2','2.3'])

    def test_new_fact_after_app_footer_is_never_cut_off(self):
        text='Мешканці, чиє майно постраждало, можуть подавати заявки щодо пошкодження у застосунку «єДніпро».\nЗавантажити застосунок можна у\nApp Store\nта\nGoogle Play\nЕвакуйовано 12 людей. Людині потрібна термінова операція.'
        result=selected_text(text)
        self.assertIn('Евакуйовано 12 людей.',result)
        self.assertIn('Людині потрібна термінова операція.',result)
        self.assertNotIn('застосунок',result)

    def test_unknown_consequence_after_courtesy_formula_stays(self):
        text='Мої співчуття рідним і близьким. Пошкоджена підпірна стіна. Евакуйовано 8 людей.'
        value=selected_text(text)
        self.assertIn('Пошкоджена підпірна стіна.',value)
        self.assertIn('Евакуйовано 8 людей.',value)
        combined='Мої співчуття рідним і близьким, пошкоджено 7 будинків.'
        self.assertIn('7 будинків',selected_text(combined))

    def test_abstract_casualty_warning_is_not_an_event(self):
        self.assertFalse(has_operational_attack_assertion('Дніпро. Під час війни кількість загиблих може зростати.'))
        self.assertTrue(has_operational_attack_assertion('Кількість загиблих унаслідок цієї атаки зросла до 17.'))
        self.assertIsNone(notice_kind('У Дніпрі можливі екстрені відключення наступної зими.'))
        self.assertIsNone(notice_kind('Генератори допоможуть водопостачанню працювати у разі відключень.'))

    def test_second_station_attack_disables_chain_merge(self):
        f=json.loads((ROOT/'tests/fixtures/source_core_20261030.json').read_text())
        p=copy.deepcopy(next(x for x in f['posts'] if x['key']=='dnipropetrovskaODA/32901'))
        p.update(key='dnipropetrovskaODA/second-station',published_at='2026-10-29T15:00:00+00:00',
                 text='Ворог знову атакував залізничний вокзал у Дніпрі. Пошкоджено іншу платформу. Загинули двоє людей.')
        r,t=render(f['posts']+[p])
        self.assertIn('іншу платформу',t)
        self.assertIn('Загинули двоє людей',t)
        self.assertFalse(any(x.get('reason')=='unique_station_update_chain' for x in r['records']))
        self.assertIn('зросла до 15',t)

    def test_different_station_incident_date_disables_merge(self):
        f=json.loads((ROOT/'tests/fixtures/source_core_20261030.json').read_text())
        p=copy.deepcopy(next(x for x in f['posts'] if x['key']=='dnipropetrovskaODA/32901'))
        p.update(key='dnipropetrovskaODA/another-day',published_at='2026-10-30T05:30:00+00:00',
                 text='30 жовтня ворог атакував залізничний вокзал у Дніпрі. Пошкоджено іншу платформу.')
        r,t=render(f['posts']+[p])
        self.assertFalse(any(x.get('reason')=='unique_station_update_chain' for x in r['records']))
        self.assertIn('іншу платформу',t)

    def test_unknown_clinical_consequence_survives_chain_and_visibility_check(self):
        f=json.loads((ROOT/'tests/fixtures/source_core_20261030.json').read_text())
        next(x for x in f['posts'] if x['key']=='dnipropetrovskaODA/32913')['text']+=' Пацієнту необхідна трансплантація.'
        r,t=render(f['posts'])
        self.assertIn('Пацієнту необхідна трансплантація.',t)
        self.assertIn('lost_source_claim',publication_issues(r,t.replace('Пацієнту необхідна трансплантація.',''),{}))

    def test_transport_conflict_does_not_hide_new_rescue_fact(self):
        post={'text':'Через знеструмлення тягових підстанцій роботу всіх трамвайних та тролейбусних маршрутів зупинено.\nТролейбуси з автономним ходом курсують.\nЕвакуйовано 12 людей.'}
        self.assertIn('Евакуйовано 12 людей.',emergency_transport(post))

    def test_older_snapshots_keep_claim_coverage(self):
        for day in ['27','28','29']:
            r,t=render(day=day)
            self.assertNotIn('lost_source_claim',publication_issues(r,t,{}),day)

    def test_lost_current_notices_are_visible_in_advisory_audit(self):
        r,t=render()
        changed=t.replace('Метро працює з інтервалом 16 хвилин.','')
        self.assertIn('lost_current_transport_notice',publication_issues(r,changed,{}))
        changed=t.replace('Дніпро знову знеструмлений.','')
        self.assertIn('lost_current_utility_notice',publication_issues(r,changed,{}))

    def test_latest_death_number_elsewhere_does_not_certify_city_update(self):
        r,t=render()
        changed=t.replace('Кількість загиблих унаслідок цієї атаки зросла до 15.','')
        changed+='\n\nПавлоград:\nКількість загиблих унаслідок цієї атаки зросла до 15.'
        self.assertIn('lost_source_claim',publication_issues(r,changed,{}))

    def test_two_incident_clocks_in_same_hour_do_not_merge(self):
        f=json.loads((ROOT/'tests/fixtures/source_core_20261030.json').read_text())
        p=copy.deepcopy(next(x for x in f['posts'] if x['key']=='dnipropetrovskaODA/32901'))
        p.update(key='dnipropetrovskaODA/another-clock',published_at='2026-10-29T10:30:00+00:00',
                 text='29 жовтня о 11:50 ворог атакував залізничний вокзал у Дніпрі. Пошкоджено іншу платформу.')
        r,t=render(f['posts']+[p])
        self.assertFalse(any(x.get('reason')=='unique_station_update_chain' for x in r['records']))
        self.assertIn('іншу платформу',t)

    def test_repeat_consequence_with_two_clocks_survives(self):
        text='О 10:00 ворог атакував Дніпро. Пошкоджено будинок. О 12:00 ворог атакував Дніпро. Пошкоджено будинок.'
        self.assertEqual(selected_text(text).count('Пошкоджено будинок.'),2)

    def test_earlier_clinical_update_retains_unique_patients_without_old_totals(self):
        r,t=render()
        self.assertTrue(any(x['source_key']=='dnipropetrovskaODA/32911' for x in r['records']))
        self.assertIn('чоловіки 40 і 53 років та 26-річна жінка',t)
        for old in ['Вже 13 поранених через ворожий удар','До 10 зросла кількість поранених','Троє людей госпіталізовані у важкому стані','Четверо людей у тяжкому стані']:
            self.assertNotIn(old,t)
        changed=t.replace('Шестеро - у тяжкому стані.','')
        self.assertIn('lost_source_claim',publication_issues(r,changed,{}))

    def test_reduced_death_assessment_requires_review_instead_of_max(self):
        f=json.loads((ROOT/'tests/fixtures/source_core_20261030.json').read_text())
        next(x for x in f['posts'] if x['key']=='dnipropetrovskaODA/32950')['text']=next(x for x in f['posts'] if x['key']=='dnipropetrovskaODA/32950')['text'].replace('зросла до 15','зросла до 12')
        r,t=render(f['posts'])
        self.assertFalse(any(x.get('reason')=='unique_station_update_chain' for x in r['records']))
        self.assertTrue(r['review_required'])
        self.assertIn('station_mortality_count_decreased',[x.get('detail') for x in r['diagnostics']])
        self.assertIn('зросла до 12',t)
        self.assertIn('14 людей загинули',t)
        self.assertTrue(any('До 14 зросла кількість загиблих' in x['source_text'] for x in r['records']))

    def test_named_other_station_prevents_unproven_merge(self):
        f=json.loads((ROOT/'tests/fixtures/source_core_20261030.json').read_text())
        p=copy.deepcopy(next(x for x in f['posts'] if x['key']=='dnipropetrovskaODA/32901'))
        p.update(key='dnipropetrovskaODA/named-other',published_at='2026-10-29T15:00:00+00:00',
                 text='Ворог атакував залізничний вокзал «Інший» у Дніпрі. Пошкоджено іншу платформу.')
        r,t=render(f['posts']+[p])
        self.assertFalse(any(x.get('reason')=='unique_station_update_chain' for x in r['records']))
        self.assertIn('іншу платформу',t)

    def test_competing_fatal_object_prevents_linking_generic_city_count(self):
        f=json.loads((ROOT/'tests/fixtures/source_core_20261030.json').read_text())
        p=copy.deepcopy(next(x for x in f['posts'] if x['key']=='dnipropetrovskaODA/32901'))
        p.update(key='dnipropetrovskaODA/other-fatal',published_at='2026-10-29T10:00:00+00:00',
                 text='Ворог атакував підприємство у Дніпрі. 13 людей загинули.')
        r,t=render(f['posts']+[p])
        generic=next(x for x in r['records'] if x['source_key']=='dnipropetrovskaODA/32900')
        self.assertNotEqual(generic['reason'],'unique_station_update_chain')
        self.assertIn('підприємство у Дніпрі',t)

    def test_same_consequence_on_two_dates_is_not_parser_repetition(self):
        text='29 жовтня ворог атакував Дніпро. Пошкоджено приватний будинок. 30 жовтня ворог атакував Дніпро. Пошкоджено приватний будинок.'
        self.assertEqual(selected_text(text).count('Пошкоджено приватний будинок.'),2)
        from report_preparation import deduplicate_source_body
        paragraph='Ворог атакував Дніпро. Пошкоджено приватний будинок. Є поранені, пошкоджено також автомобіль.'
        self.assertEqual(deduplicate_source_body(paragraph+'\n'+paragraph),paragraph)
