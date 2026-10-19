import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import collector as c


FIXTURE = Path(__file__).parent / 'fixtures' / 'operational_selection_20261019.json'


class OperationalSelectionTests(unittest.TestCase):
    def setUp(self):
        self.posts = {p['key']: p for p in json.loads(FIXTURE.read_text())}

    def test_real_casualty_update_with_inflected_hostile_attack(self):
        self.assertTrue(c.is_resonant(self.posts['adm_dp/44996']))

    def test_real_unscheduled_utility_fault(self):
        self.assertTrue(c.is_resonant(self.posts['cek_info/4255']))

    def test_inflections_are_not_tied_to_one_city_or_count(self):
        for phrase in ('ворожа атака', 'ворожої атаки', 'ворожу атаку', 'ворожою атакою'):
            with self.subTest(phrase=phrase):
                self.assertTrue(c.is_resonant({'channel': 'adm_dp',
                    'text': 'Дніпропетровщина: ' + phrase + '. Троє постраждалих.'}))
        self.assertTrue(c.is_resonant({'channel': 'adm_dp',
            'text': 'Через атаку рф на Нікополь постраждала людина.'}))

    def test_national_other_region_still_excluded(self):
        self.assertFalse(c.is_resonant(self.posts['dsns_telegram/78115']))
        self.assertFalse(c.is_resonant({'channel': 'dsns_telegram',
            'text': 'Через ворожу атаку на Львів четверо постраждалих.'}))

    def test_routine_energy_story_and_scheduled_notice_are_not_fault_alerts(self):
        self.assertFalse(c.is_resonant(self.posts['DniproCityOfficial/14975']))
        for text in ('Графік погодинних відключень у Дніпрі на завтра.',
                     'Технологічне порушення не спричинило знеструмлення будинків.',
                     'Технологічне порушення може спричинити знеструмлення будинків.'):
            with self.subTest(text=text):
                self.assertFalse(c.is_resonant({'channel': 'cek_info', 'text': text}))

    def test_already_selected_real_attack_still_selected(self):
        self.assertTrue(c.is_resonant(self.posts['dnipropetrovskaODA/32691']))

    def test_delivery_cursor_and_repeated_scan_for_newly_recognized_posts(self):
        posts = [self.posts[k] for k in ('adm_dp/44996', 'cek_info/4255')]
        now = c.parse_datetime('2026-10-19T12:00:00Z')
        state = {'initialized': True, 'alerted_keys': [],
                 'last_alert_scan_at': '2026-10-19T06:00:00Z'}
        with tempfile.TemporaryDirectory() as d, \
             patch.object(c, 'ALERT_STATE_FILE', Path(d) / 'state.json'), \
             patch.dict(os.environ, {'TELEGRAM_BOT_TOKEN': 'test-only',
                 'TELEGRAM_CHAT_ID': 'test-only', 'SEND_OPERATIONAL_ALERTS': 'true'}), \
             patch.object(c, 'send_bot_message', return_value=True) as send:
            c.save_alert_state(state)
            self.assertEqual(c.process_alerts(posts, now), [])
            self.assertEqual(send.call_count, 2)
            self.assertEqual(set(c.read_alert_state()['alerted_keys']), {p['key'] for p in posts})
            c.process_alerts(posts, now)
            self.assertEqual(send.call_count, 2)


if __name__ == '__main__':
    unittest.main()
