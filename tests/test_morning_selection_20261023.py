import json
import os
import re
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import collector as c
from fact_registry import compile_registry,render_registry
from fallback_report import WEATHER
from operational_facts import official_damage_excerpt,prevention_without_event

F=json.loads((Path(__file__).parent/'fixtures/source_core_20261023.json').read_text())
NOW=datetime.fromisoformat(F['status']['checked_at'])


class MorningSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry=compile_registry(F['posts'],F['status']['channels'],NOW)
        cls.text=render_registry(cls.registry)

    def test_real_blocked_input_is_publishable_without_raising_limit(self):
        self.assertEqual(len(F['blocked_report'].split()),916)
        self.assertLessEqual(len(self.text.split()),500)
        self.assertFalse(self.registry['review_required'])
        self.assertFalse(self.registry['coverage_unproven'])

    def test_words_about_danger_or_approval_are_not_weather(self):
        for word in ('загрози','загрозою','погодження','узгоджено'):
            self.assertIsNone(WEATHER.search(word))
        for word in ('гроза','грози','грозу','грозовий','туман','ожеледиця','шторм','видимість'):
            self.assertIsNotNone(WEATHER.search(word))

    def test_school_and_police_instructions_are_not_events(self):
        for key in ('gunpvdp/37302','gunpvdp/37315'):
            record=next(r for r in self.registry['records'] if r['source_key']==key)
            self.assertEqual(record['state'],'excluded')
            self.assertTrue(record['source_text'])
        for text in ('мобільний клас','Школярам пояснили','Не торкайтеся підозрілих предметів','спецлінію 102'):
            self.assertNotIn(text,self.text)

    def test_prevention_word_does_not_hide_affirmative_operation(self):
        self.assertFalse(prevention_without_event('Поліція нагадує правила безпеки. У Дніпрі вилучили гранату.'))
        self.assertTrue(prevention_without_event('Поліція нагадує: у разі виявлення гранати не торкайтеся її.'))

    def test_official_statement_retains_all_material_numbers_and_locality(self):
        for phrase in ('Новокодацький район Дніпра','пошкоджено 11 приватних будинків',
                       'більше ніж 20 вікон, 2 покрівлі','360 м кв.','Обійшлося без постраждалих'):
            self.assertIn(phrase,self.text)
        for text in ('Сервіси','єДніпро','люстри','пані Інна','Телефон для довідок'):
            self.assertNotIn(text,self.text)
        rec=next(r for r in self.registry['records'] if r['source_key']=='DniproCityOfficial/15155')
        self.assertIn('пані Інна',rec['source_text'])

    def test_unknown_or_multiple_official_quotes_are_not_guessed(self):
        post=next(p for p in F['posts'] if p['key']=='DniproCityOfficial/15155')
        self.assertIsNotNone(official_damage_excerpt(post))
        self.assertIsNone(official_damage_excerpt(dict(post,channel='other')))
        second='\n«Пошкоджено 3 будинки», — зазначила заступниця голови адміністрації району.'
        self.assertIsNone(official_damage_excerpt(dict(post,text=post['text']+second)))

    def test_zhovti_vody_is_not_truncated_and_lanes_are_not_lost(self):
        self.assertIn('ЖОВТІ ВОДИ:',self.text)
        self.assertNotIn('ЖОВТІ:',self.text)
        for name in ('Вишневий','Гірницький','Межовий','Удільний','Національної Гвардії України','Олімпійська'):
            self.assertIn(name,self.text)
        self.assertIn('тимчасово',self.text)
        self.assertIn('підчерга 6.1',self.text)

    def test_all_bulletin_scopes_counts_and_communities_survive(self):
        for r in self.registry['records']:
            if r['reporting_period'] and r['state']=='included':
                self.assertIn(r['source_text'] if r['scope']=='Дніпропетровська область' else r['display'],self.text)
        for phrase in ('Понад 50','Майже 20','Одна людина загинула','Двоє людей постраждали',
                       '44-річний','26-річна','Солонянській','Апостолівській','Зеленодольській',
                       'Раївській','Шахтарській','П’ятихатках','Томаківська'):
            self.assertIn(phrase,self.text)

    def test_rescue_fire_locations_and_extinguishing_are_retained(self):
        self.assertIn('Дніпровському, Криворізькому, Синельниківському та Кам’янському районах',self.text)
        self.assertIn('Рятувальники ліквідували всі пожежі.',self.text)

    def test_one_city_update_is_not_added_to_another(self):
        self.assertIn('11 приватних будинків',self.text)
        self.assertIn('понад 10 осель',self.text)
        self.assertNotRegex(self.text,r'21\s+(?:приватних\s+)?будин')
        self.assertNotIn('за добу загинуло троє',self.text)

    def test_actual_morning_entry_reaches_exact_saved_delivery(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            with patch.object(c,'DATA_DIR',root),patch.object(c,'MORNING_REPORT_FILE',root/'morning_report.md'), \
                 patch.object(c,'read_alert_state',return_value={'last_daily_report':'2026-10-22'}), \
                 patch.dict(os.environ,{'SEND_MORNING_REPORT':'true','FORCE_MORNING_REPORT':'false','PRODUCTION_MONITOR':'true'}), \
                 patch('core_review.review_core',return_value={'state':'completed','requests':1,'provider':'gemini','issues':[]}) as reviewer, \
                 patch.object(c,'deliver_morning_report') as send,patch.object(c,'send_bot_message') as notice:
                c.process_morning_report(F['posts'],F['status']['channels'],NOW)
                self.assertEqual(send.call_count,1)
                self.assertEqual(reviewer.call_count,1)
                self.assertEqual(send.call_args.args[0],(root/'morning_report.md').read_text().strip())
                status=json.loads((root/'report_generation_status.json').read_text())
                self.assertEqual(status['delivery_state'],'confirmed')
                self.assertLessEqual(status['report_words'],500)
                self.assertEqual(status['publication_issues'],[])
                notice.assert_not_called()

    def test_five_public_points_and_original_window(self):
        self.assertEqual(re.findall(r'(?m)^([12]\.[1-4])\.',self.text),['1.1','1.2','2.1','2.2','2.3'])
        self.assertIn('22.10.2026 08:00 — 23.10.2026 08:00',self.text)


if __name__=='__main__':
    unittest.main()
