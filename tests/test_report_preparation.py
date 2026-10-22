import json
import unittest
from datetime import date
from pathlib import Path

import collector
from ai_report import linked_casualty_locations
from fallback_report import brief_attacks, brief_service, brief_transport
from report_preparation import prepare_evidence, deduplicate_source_body

FIXTURE = json.loads((Path(__file__).parent/'fixtures/report_reserve_20261020.json').read_text())


class ReportPreparationTests(unittest.TestCase):
    def test_exact_parser_repetition_removed_without_changing_source(self):
        body = 'У Дніпрі пошкоджені будинки.\nГоспіталізована людина.\nНа місці працюють рятувальники.'
        self.assertEqual(deduplicate_source_body(body+'\n'+body), body)
        original = {'text': body+'\n'+body, 'published_at':'2026-10-19T08:00:00Z'}
        self.assertEqual(prepare_evidence([original])[0]['text'], body)
        self.assertEqual(original['text'], body+'\n'+body)

    def test_different_numeric_update_is_not_deduplicated(self):
        text = 'У Дніпрі поранені двоє.\nУ Дніпрі поранені троє.'
        self.assertEqual(deduplicate_source_body(text), text)

    def test_energy_promotion_is_not_an_outage(self):
        p = next(p for p in FIXTURE['posts'] if str(p['post_id'])=='14975')
        self.assertIsNone(collector.classify_post(p))
        self.assertEqual(prepare_evidence([p]), [])

    def test_real_outage_and_its_repair_update_are_selected(self):
        for post in FIXTURE['posts']:
            if str(post['post_id']) in {'4255','4257','4259'}:
                self.assertEqual(collector.classify_post(post), '1.4')

    def test_reserve_uses_latest_bulletins_not_casualty_counter_history(self):
        posts = [p for p in FIXTURE['posts'] if p['channel']=='dnipropetrovskaODA']
        earlier = dict(posts[0], text='У Кривому Розі кількість поранених зросла до семи.',
                       published_at='2026-10-19T09:31:00Z')
        body = brief_attacks([earlier]+posts)
        self.assertNotIn('зросла до семи', body)
        self.assertIn('Десятеро', body)
        self.assertIn('55-річного', body)
        self.assertIn('15 років', body)

    def test_restored_routes_do_not_keep_the_old_detour(self):
        posts = [p for p in FIXTURE['posts'] if str(p['post_id']) in {'14997','15002'}]
        body = brief_transport(posts)
        self.assertIn('Відновлюється рух', body)
        self.assertNotIn('призупинив свою роботу', body)
        self.assertNotIn('курсує за скороченим', body)
        self.assertNotIn('Інститут фізкультури', body)
        self.assertNotIn('Добровольців', body)
        self.assertIn('№35', body)

    def test_power_places_are_not_combined_with_each_others_streets(self):
        post = next(p for p in FIXTURE['posts'] if str(p['post_id'])=='4259')
        body = brief_service(post, date(2026,10,20))
        self.assertIn('ОБУХІВКА (з 08:00 до 18:00): окремі будинки на вул. Рибальська', body)
        self.assertIn('НОВОПІЛЛЯ (з 08:00 до 18:00): окремі будинки на вул. Шкільна', body)
        self.assertIn('08:00 до 18:00', body)

    def test_real_false_city_casualty_link_is_not_forced(self):
        posts = [dict(p,category_hint='2.1') for p in FIXTURE['posts']
                 if str(p['post_id'])=='32693']
        earlier = dict(posts[0], text='55-річний чоловік дістав поранень через атаку на Дніпро. У Кривому Розі двоє людей загинули.',
                       published_at='2026-10-19T14:31:00Z')
        self.assertNotIn('Дніпро', linked_casualty_locations([earlier]+posts))

    def test_production_reserve_has_public_structure_and_no_promotion(self):
        from report_layout import render_report
        raw = collector.build_morning_report(FIXTURE['posts'], {},
              collector.parse_datetime(FIXTURE['checked_at']), brief=True)
        result = render_report(raw, '08:00 19.10.2026','08:00 20.10.2026','08:01 20.10.2026')
        self.assertLess(len(result.split()), 520)
        self.assertIn('2.3. Виявлення', result)
        self.assertNotIn('як у Дніпрі підвищують', result)
        self.assertNotIn('Загроза триває', result)


if __name__ == '__main__':
    unittest.main()
