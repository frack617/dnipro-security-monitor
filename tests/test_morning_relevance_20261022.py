import json
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import collector as c
from core_review import review_core
from fact_registry import compile_registry, render_registry, service_display
from operational_facts import background_reason

F = json.loads((Path(__file__).parent/'fixtures/source_core_20261022.json').read_text())
NOW = datetime.fromisoformat(F['status']['checked_at'])


class MorningRelevanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = compile_registry(F['posts'], F['status']['channels'], NOW)
        cls.text = render_registry(cls.registry)

    def test_real_failed_run_fits_without_raising_limit(self):
        self.assertEqual(len(F['blocked_report'].split()), 1200)
        self.assertLessEqual(len(self.text.split()), 500)
        self.assertFalse(self.registry['review_required'])
        self.assertEqual(self.registry['failed_sources'], [])

    def test_background_is_absent_but_retained_in_audit(self):
        keys = {'gunpvdp/37286', 'DniproCityOfficial/15090',
                'DniproCityOfficial/15104', 'DniproCityOfficial/15115',
                'dnipropetrovskaODA/32731', 'dnipropetrovskaODA/32739', 'adm_dp/45091'}
        records = [r for r in self.registry['records'] if r['source_key'] in keys]
        self.assertEqual({r['source_key'] for r in records}, keys)
        self.assertTrue(all(r['state'] == 'excluded' and r['source_text'] for r in records))
        for phrase in ('95 %', '199 генераторів', 'Борису Руге', 'Три рівні', '5 котелень'):
            self.assertNotIn(phrase, self.text)

    def test_every_selected_bulletin_fact_and_original_period_survives(self):
        for r in self.registry['records']:
            if r['reporting_period'] and r['state'] == 'included':
                self.assertTrue(any(r['id'] in p.get('record_ids',[]) for p in self.registry['public_projection']['provenance']))
        self.assertEqual(self.text.count('Понад 50'), 1)
        self.assertEqual(self.text.count('Понад 20'), 1)
        self.assertIn('21 жовтня (станом на 18:30)', self.text)
        self.assertIn('22 жовтня (станом на 07:30)', self.text)
        self.assertIn('Мирівській', self.text)
        self.assertIn('П’ятихатській', self.text)
        self.assertIn('Зеленодольській', self.text)
        self.assertNotIn('Понад 70', self.text)

    def test_outage_geography_count_and_temporary_schedule_survive(self):
        for phrase in ('понад 30 тисяч', 'Павлоградському', 'Синельниківському',
                       'місті Самар', '4 години зі світлом, 4 години без світла',
                       'ВІЛЬНОГІРСЬК (з 08:00 до 18:00)', 'САДКИ (з 07:30 до 18:00)', 'ШИРОКЕ (з 07:30 до 18:00)'):
            self.assertIn(phrase, self.text)

    def test_travel_impact_kept_without_timetables(self):
        for phrase in ('Старому мосту', 'працюватимуть автобуси',
                       'Королеви Єлизавети II', 'Харківської', 'Європейської'):
            self.assertIn(phrase, self.text)
        for phrase in ('21:46', '21:38', 'Останні відправлення', '№'):
            self.assertNotIn(phrase, self.text)

    def test_preparedness_words_do_not_hide_an_actual_attack(self):
        self.assertIsNone(background_reason(
            'Дніпро готується до зими. Ворог атакував місто. Пошкоджено будинки.'))
        self.assertIsNone(background_reason(
            'Медзаклади мають генератори. Через ворожу атаку без світла залишилися будинки.'))

    def test_hypothetical_blackout_is_not_current_service_impact(self):
        post = dict(text='У Дніпрі генератори забезпечать лікарню під час можливих відключень.',
                    published_at=NOW.isoformat())
        self.assertIsNone(service_display(post, NOW))

    def test_corrected_real_fixture_reaches_delivery_with_successful_review(self):
        # No live APIs: exercise the same morning entry point that failed,
        # using a successful bounded reviewer result and a captured delivery.
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch.dict(os.environ, {'SEND_MORNING_REPORT':'true', 'FORCE_MORNING_REPORT':'false'}), \
                 patch.object(c, 'DATA_DIR', root), \
                 patch.object(c, 'MORNING_REPORT_FILE', root/'morning_report.md'), \
                 patch.object(c, 'read_alert_state', return_value={}), \
                 patch('core_review.review_core', return_value={'state':'completed','requests':1,'provider':'gemini','issues':[]}), \
                 patch.object(c, 'deliver_morning_report') as send:
                c.process_morning_report(F['posts'], F['status']['channels'], NOW)
                self.assertEqual(send.call_count, 1)
                self.assertEqual(send.call_args.args[0], self.text)
                status = json.loads((root/'report_generation_status.json').read_text())
                self.assertEqual(status['delivery_state'], 'confirmed')
                self.assertLessEqual(status['report_words'], 500)

    def test_overlong_unknown_report_still_blocks_before_api(self):
        with patch('core_review.request_text') as request:
            self.assertEqual(review_core({}, 'факт '*501)['state'], 'blocked_length')
            request.assert_not_called()


if __name__ == '__main__':
    unittest.main()
