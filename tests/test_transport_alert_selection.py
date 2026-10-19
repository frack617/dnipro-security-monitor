import json
import unittest
from pathlib import Path

import collector as c


class TransportAlertSelectionTests(unittest.TestCase):
    def setUp(self):
        self.posts = {p['key']: p for p in json.loads((Path(__file__).parent /
            'fixtures/transport_alert_20261019.json').read_text())}

    def test_real_route_update_included_and_suspension_alerted(self):
        p = self.posts['DniproCityOfficial/14997']
        self.assertEqual(c.classify_post(p), '1.2')
        self.assertTrue(c.is_resonant(p))

    def test_regular_real_notices_stay_in_brief_without_new_alert(self):
        for key in ('DniproCityOfficial/14955', 'DniproCityOfficial/14956'):
            with self.subTest(key=key):
                self.assertEqual(c.classify_post(self.posts[key]), '1.2')
                self.assertFalse(c.is_resonant(self.posts[key]))

    def test_update_inflection_without_full_suspension_is_report_only(self):
        p = {'channel': 'adm_dp', 'text': 'Оновлена інформація щодо змін у русі транспорту Дніпра: автобус №42 курсує за скороченим маршрутом.'}
        self.assertEqual(c.classify_post(p), '1.2')
        self.assertFalse(c.is_resonant(p))

    def test_other_number_and_vehicle_types_not_hardcoded(self):
        for vehicle in ('Автобус №42', 'Тролейбус №12', 'Трамвай №7'):
            with self.subTest(vehicle=vehicle):
                p = {'channel': 'DniproCityOfficial', 'text': vehicle + '\nтимчасово припинив роботу.'}
                self.assertEqual(c.classify_post(p), '1.2')
                self.assertTrue(c.is_resonant(p))

    def test_manufacturer_and_unrelated_business_are_not_routes(self):
        for text in ('Автобусний завод №42 призупинив свою роботу.',
                     'Підприємство №134 призупинило свою роботу.'):
            self.assertFalse(c.has_stopped_route(text.lower()))

    def test_future_suspension_is_not_completed_suspension(self):
        p = {'channel': 'adm_dp', 'text': 'Завтра автобус №42 призупинить свою роботу.'}
        self.assertFalse(c.is_resonant(p))

    def test_other_oblast_suspension_is_excluded(self):
        p = {'channel': 'dsns_telegram', 'text': 'У Львові автобус №42 призупинив свою роботу.'}
        self.assertFalse(c.is_resonant(p))

    def test_background_filter_remains_active(self):
        p = self.posts['DniproCityOfficial/14983']
        self.assertIsNone(c.classify_post(p))
        self.assertFalse(c.is_resonant(p))


if __name__ == '__main__':
    unittest.main()
