import copy
import json
import re
import unittest
from pathlib import Path
from datetime import datetime
from unittest.mock import patch

from fact_registry import compile_registry, render_registry, bulletin_header
from report_contract import publication_issues
from brief_policy import POWER_SUMMARY, administrative_clause, weapons_excerpt
from source_claims import selected_text
import collector

ROOT=Path(__file__).parents[1]


def replay(day='04',posts=None):
    f=json.loads((ROOT/f'tests/fixtures/source_core_202611{day}.json').read_text())
    with patch('requests.sessions.Session.request',side_effect=AssertionError('No HTTP in replay')):
        r=compile_registry(copy.deepcopy(f['posts'] if posts is None else posts),f['status']['channels'],datetime.fromisoformat(f['status']['checked_at']))
        return r,render_registry(r)


class PublicationPolicyTests(unittest.TestCase):
    def test_current_power_summary_without_queue_tables(self):
        r,t=replay();general=t.split('1.2. Сповіщення')[0]
        self.assertEqual(general.count(POWER_SUMMARY),1)
        self.assertNotIn('Черга 1.1',general)
        self.assertNotIn('15:30-19:00',general)
        self.assertNotIn('03 ЛИСТОПАДА',general)
        self.assertTrue(any('Черга 1.1' in x['source_text'] for x in r['records']))
        self.assertIn('lost_service_schedule',publication_issues(r,t.replace(POWER_SUMMARY,''),{}))

    def test_water_restriction_kept_and_admin_help_removed(self):
        _,t=replay()
        for fact in ['22:00 години 4 листопада','22:00 години 6 листопада','Новокодацькому','Чечелівському']:
            self.assertIn(fact,t)
        for noise in ['пересувний штаб','мобільний пункт незламності','1530','28 тисяч доларів','єВідновлення']:
            self.assertNotIn(noise,t)

    def test_nov04_evening_summary_geography_and_clinical_facts_present(self):
        r,t=replay()
        for fact in ['Любимівській','5 чоловіків','Зеленодольській','Апостолівській','42-річний','72-річна','Богинівській']:
            self.assertIn(fact,t)
        self.assertIn('Дніпровський',t.split('1.2.')[0])
        self.assertNotIn('Загинув 61-річний чоловік',t)
        self.assertTrue(any(x['state']=='review' and '61-річний' in x['source_text'] for x in r['records']))

    def test_latest_completed_counts_replace_interim_but_keep_rescue(self):
        r,t=replay()
        self.assertNotIn('До 15 зросла',t);self.assertNotIn('До 17 зросла',t)
        self.assertNotIn('щонайменше 17 людей отримали поранення',t)
        self.assertNotIn('Підтверджено 18 постраждалих',t)
        for fact in ['20 поранених','11 врятованих','з-під завалів жінку','осколковими пораненнями']:
            # Clinical diagnosis remains in the source archive if admission is
            # conservative; the real draft must retain the rescue evidence.
            if fact!='осколковими пораненнями':self.assertIn(fact,t)
        self.assertTrue(any(x.get('assessment_history') for x in r['records']))
        changed=t.replace('Двоє загиблих, 20 поранених.','')
        self.assertIn('lost_source_claim',publication_issues(r,changed,{}))

    def test_second_attack_and_decreasing_count_are_not_merged(self):
        f=json.loads((ROOT/'tests/fixtures/source_core_20261104.json').read_text())
        for text in ['До 25 зросла кількість поранених через атаку росіян на Дніпро.',
                     'До 15 зросла кількість поранених через атаку росіян на Дніпро. Це друга атака.']:
            posts=copy.deepcopy(f['posts']);p=next(p for p in posts if p['key']=='dnipropetrovskaODA/33068')
            p['text']=text
            _,t=replay(posts=posts)
            self.assertIn(text.split('.')[0],t)

    def test_seized_arsenal_is_weapons_not_uxo_and_no_bribery_story(self):
        r,t=replay();weapons=t.split('2.2. Незаконне')[1].split('2.3. Виявлення')[0]
        for fact in ['АК-47','30 тисяч набоїв','28 гранат','400 грамів']:
            self.assertIn(fact,weapons)
        self.assertNotIn('неправомірну вигоду',weapons)
        self.assertNotIn('АК-47',t.split('2.3. Виявлення')[1])
        self.assertEqual(collector.classify_post({'text':'У Дніпрі поліція вилучила арсенал зброї та боєприпасів.'}),'2.2')

    def test_actual_uxo_is_not_relabelled_as_seizure(self):
        self.assertEqual(collector.classify_post({'text':'У Дніпрі піротехніки виявили нерозірваний боєприпас.'}),'2.4')
        self.assertIsNone(weapons_excerpt('Піротехніки виявили нерозірваний боєприпас.'))

    def test_admin_filter_preserves_adjacent_damage_evacuation_and_danger(self):
        text='На місці атаки розгорнуто мобільний пункт незламності. Пошкоджено дитячий садок. Евакуйовано 12 людей.'
        t=selected_text(text)
        self.assertNotIn('пункт незламності',t)
        self.assertIn('Пошкоджено дитячий садок.',t)
        self.assertIn('Евакуйовано 12 людей.',t)
        self.assertFalse(administrative_clause('Зруйновано пункт незламності.'))

    def test_single_bullet_morning_is_not_lost(self):
        r,t=replay('02')
        for fact in ['57-річного','Майже 30','Васильківській','43-річного']:
            self.assertIn(fact,t)
        self.assertNotIn('Фото_тижня',t)
        self.assertNotIn('15 загиблих',t)
        self.assertNotIn('66-річного',t)

    def test_previous_day_short_outage_estimate_is_not_a_current_notice(self):
        _,t=replay('03')
        self.assertNotIn('Шановні споживачі',t)
        self.assertNotIn('протягом 1-2 годин',t)

    def test_headerless_recognizer_is_bounded_to_native_summary(self):
        f=json.loads((ROOT/'tests/fixtures/source_core_20261104.json').read_text())
        p=next(x for x in f['posts'] if x['key']=='dnipropetrovskaODA/33100')
        self.assertIsNotNone(bulletin_header(p))
        for change in [dict(channel='gunpvdp'),dict(published_at='2026-11-03T10:30:00+00:00')]:
            self.assertIsNone(bulletin_header(dict(p,**change)))

    def test_public_five_section_contract_and_no_delivery_mutations(self):
        _,t=replay()
        self.assertEqual(re.findall(r'(?m)^([12]\.\d)\.',t),['1.1','1.2','2.1','2.2','2.3'])

    def test_unknown_emergency_clause_after_schedule_is_kept(self):
        f=json.loads((ROOT/'tests/fixtures/source_core_20261104.json').read_text())
        p=copy.deepcopy(next(x for x in f['posts'] if x['key']=='cek_info/4314'))
        p['text']+='\nАварія пошкодила резервний кабель на вул. Центральній.'
        _,t=replay(posts=[p]);self.assertIn('Аварія пошкодила резервний кабель',t)
