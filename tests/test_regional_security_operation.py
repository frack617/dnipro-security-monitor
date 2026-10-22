import copy
import json
import unittest
from datetime import datetime
from pathlib import Path

from fact_registry import compile_registry,render_registry
from operational_facts import regional_security_operation
import collector as c

F=json.loads((Path(__file__).parent/'fixtures/source_core_20261022.json').read_text())
NOW=datetime.fromisoformat(F['status']['checked_at'])


class RegionalSecurityOperationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.post=next(p for p in F['posts'] if p['key']=='SBUkr/18890')
        cls.registry=compile_registry(F['posts'],F['status']['channels'],NOW)
        cls.text=render_registry(cls.registry)

    def test_real_collected_operation_is_in_22_and_not_declared_absent(self):
        block=self.text.split('2.2. Незаконне')[1].split('2.3. Виявлення')[0]
        self.assertNotIn('повідомлень за звітний період не виявлено',block)
        self.assertIn('затримала у Києві',block)
        self.assertIn('18-річний одесит',block)
        self.assertIn('з’їздив до Дніпра',block)
        self.assertIn('під вартою без права внесення застави',block)
        self.assertNotIn('затримала у Дніпрі',block)
        self.assertLessEqual(len(self.text.split()),500)
        self.assertFalse(self.registry['review_required'])

    def test_original_source_and_dates_survive(self):
        rec=next(r for r in self.registry['records'] if r['source_key']=='SBUkr/18890')
        self.assertEqual(rec['state'],'included')
        self.assertEqual(rec['section'],'2.2')
        self.assertEqual(rec['published_at'],'2026-10-21T07:00:10+00:00')
        self.assertIn('у серпні',rec['source_text'])
        self.assertIsNone(rec['incident_time'])

    def test_before_planned_action_is_not_yesterday(self):
        start=c.completed_report_window(NOW)[0]
        self.assertFalse(c.is_historical_context(self.post,start))
        keys={p['key'] for p in c.report_window_posts(F['posts'],NOW)}
        self.assertIn('SBUkr/18890',keys)
        old=dict(self.post,text='Учора у Києві затримали агента, який розвідував цілі у Дніпрі.')
        self.assertTrue(c.is_historical_context(old,start))

    def test_no_old_odessa_attack_or_target_types_transferred_to_dnipro(self):
        out=regional_security_operation(self.post)
        for phrase in ('у серпні','ППО','оборонних підприємств','логістичному поштовому терміналу'):
            self.assertNotIn(phrase,out)

    def test_generic_origin_or_office_location_is_not_a_regional_operation_link(self):
        for link in ('Він народився у Дніпрі.',
                     'Комплексні заходи проводили співробітники Головного управління СБУ у Дніпропетровській області.'):
            post=dict(self.post,text='СБУ затримала агента рф\nКонтррозвідка Служби безпеки затримала у Києві агента.\n'+link)
            self.assertIsNone(regional_security_operation(post))

    def test_unrelated_national_story_not_admitted(self):
        post=dict(self.post,text=self.post['text'].replace('Дніпра','Львова').replace('Дніпру','Львову').replace('Дніпропетровській','Львівській'))
        self.assertIsNone(regional_security_operation(post))

    def test_channel_and_clear_action_are_required(self):
        self.assertIsNone(regional_security_operation(dict(self.post,channel='other')))
        self.assertIsNone(regional_security_operation(dict(self.post,text=self.post['text'].replace('Контррозвідка Служби безпеки затримала','Зустріч обговорила'))))

    def test_same_input_still_keeps_all_periods_and_communities(self):
        for phrase in ('Понад 50','Понад 20','Мирівській','П’ятихатській','Зеленодольській','понад 30 тисяч'):
            self.assertIn(phrase,self.text)
        attack=self.text.split('2.1. Обстріли')[1].split('2.2. Незаконне')[0]
        self.assertNotIn('18-річний одесит',attack)


if __name__=='__main__':
    unittest.main()
