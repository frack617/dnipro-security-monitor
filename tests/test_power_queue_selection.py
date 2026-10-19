import json
import unittest
from datetime import date
from pathlib import Path

import collector as c
from fallback_report import build_sections


class PowerQueueSelectionTests(unittest.TestCase):
    def setUp(self):
        self.posts={p['key']:p for p in json.loads((Path(__file__).parent /
            'fixtures/power_queue_20261019.json').read_text())}

    def test_real_reassignment_goes_to_service_section_without_alert(self):
        p=self.posts['cek_info/4256']
        self.assertEqual(c.classify_post(p),'1.4')
        self.assertFalse(c.is_resonant(p))

    def test_real_addresses_and_both_subqueues_survive_fallback(self):
        p=self.posts['cek_info/4256']
        text=build_sections({'1.4':[p]},date(2026,10,20))['1.4']
        for value in ('ВІЛЬНОГІРСЬК','Центральна','Миру','Молодіжна','4.2','2.2'):
            self.assertIn(value,text)

    def test_other_numbers_inflections_and_official_reposts(self):
        for text in ('Будинки переведені до графіку підчерги 5.1.',
                     'Повідомляємо про зміни графіка черги 3.2.'):
            with self.subTest(text=text):
                self.assertEqual(c.classify_post({'channel':'cek_info','text':text}),'1.4')
                self.assertEqual(c.classify_post({'channel':'adm_dp',
                    'text':'Електропостачання Дніпра. '+text}),'1.4')

    def test_non_power_queues_are_not_electricity_notices(self):
        p={'channel':'DniproCityOfficial',
           'text':'Зміни графіка черги прийому документів у Дніпрі.'}
        self.assertFalse(c.is_power_queue_change(p))
        self.assertIsNone(c.classify_post(p))

    def test_existing_fault_alert_and_energy_story_are_unchanged(self):
        p=self.posts['cek_info/4255']
        self.assertEqual(c.classify_post(p),'1.4')
        self.assertTrue(c.is_resonant(p))
        self.assertFalse(c.is_resonant(self.posts['DniproCityOfficial/14975']))


if __name__=='__main__':
    unittest.main()
