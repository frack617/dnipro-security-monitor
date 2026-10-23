import json
import re
import unittest
from datetime import date, datetime
from zoneinfo import ZoneInfo
from pathlib import Path

from fact_registry import compile_registry, render_registry, transport_display
from operational_facts import temporary_power_schedule

F = json.loads((Path(__file__).parent/'fixtures/source_core_20261022.json').read_text())
NOW = datetime.fromisoformat(F['status']['checked_at'])


class PublicOperationalProseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = compile_registry(F['posts'], F['status']['channels'], NOW)
        cls.text = render_registry(cls.registry)
        cls.utility = next(p for p in F['posts'] if p['key'] == 'cek_info/4264')

    def test_same_day_future_transport_is_not_described_as_past(self):
        self.assertIn('за анонсом закінчать роботу раніше', self.text)
        self.assertNotIn('мали закінчити', self.text)
        self.assertNotIn('21:46', self.text)
        self.assertIn('Старому мосту', self.text)
        self.assertIn('працюватимуть автобуси', self.text)

    def test_expired_transport_announcement_is_not_moved_to_today(self):
        post = next(p for p in F['posts'] if p['key'] == 'DniproCityOfficial/15137')
        out, excluded = transport_display([post], NOW.astimezone(ZoneInfo('Europe/Kyiv')).replace(day=23))
        self.assertNotIn('закінчать роботу раніше', out)
        self.assertEqual(len(excluded), 1)

    def test_recognized_supply_schedule_is_in_public_overview_only(self):
        general, attacks = self.text.split('2.1. Обстріли', 1)
        self.assertIn('4 години зі світлом, 4 години без світла', general)
        self.assertNotIn('4 години зі світлом', attacks)
        self.assertNotIn('Шановні споживачі', self.text)
        self.assertNotIn('587-595', self.text)
        self.assertNotIn('іншого ліцензіата', self.text)
        for phrase in ('для окремих будинків', 'вул. Паркова', 'вул. Тетяни Федерової',
                       'вул. Дніпровська', 'спричинене ворожими атаками'):
            self.assertIn(phrase, general)

    def test_original_houses_and_source_are_retained_in_audit(self):
        records = [r for r in self.registry['records'] if r['source_key'] == 'cek_info/4264']
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['section'], '1.4')
        self.assertIn('587-595', records[0]['source_text'])
        self.assertTrue(records[0]['source_url'].endswith('/4264'))

    def test_unrecognized_extra_consequence_prevents_shortening(self):
        for extra in ('Пошкоджено підстанцію.', 'Двоє людей поранені.',
                      'Електропостачання відновлено.', 'На вул. Парковій сталася пожежа.'):
            post = dict(self.utility, text=self.utility['text']+' '+extra)
            self.assertIsNone(temporary_power_schedule(post))

    def test_unknown_address_or_schedule_not_silently_dropped(self):
        for old, new in [('Паркова: 10', 'Паркова: невідомі адреси'),
                         ('4 години зі світлом', 'від 2 до 4 годин зі світлом'),
                         ('м. ПАВЛОГРАД', 'м. ПАВЛОГРАД та м. САМАР')]:
            post = dict(self.utility, text=self.utility['text'].replace(old, new))
            self.assertIsNone(temporary_power_schedule(post))

    def test_source_channel_is_not_guessed_from_similar_text(self):
        self.assertIsNone(temporary_power_schedule(dict(self.utility, channel='other')))

    def test_absence_of_casualties_is_scoped_to_its_bulletin(self):
        self.assertNotIn('Всюди минулося без постраждалих', self.text)
        night = self.text.split('Ранкове зведення за 22 жовтня')[1].split('\n\n')[0]
        self.assertIn('За цим зведенням, постраждалих немає.', night)
        self.assertNotIn('за добу постраждалих немає', self.text)

    def test_all_bulletin_blocks_still_present_and_counts_not_added(self):
        for r in self.registry['records']:
            if r['reporting_period'] and r['state'] == 'included':
                accounted={i for p in self.registry['public_projection']['provenance'] for i in p.get('record_ids',[])}
                self.assertIn(r['id'],accounted)
        for count in ('Понад 50', 'Понад 20'):
            self.assertEqual(self.text.count(count), 1)
        self.assertIn('понад 30 тисяч', self.text)
        self.assertIn('місті Самар', self.text)
        self.assertNotIn('Понад 70', self.text)

    def test_public_format_and_word_limit_remain(self):
        self.assertEqual(re.findall(r'(?m)^([12]\.[1-4])\.', self.text), ['1.1','1.2','2.1','2.2','2.3'])
        self.assertLessEqual(len(self.text.split()), 500)
        self.assertFalse(self.registry['review_required'])
        self.assertNotIn('Для негайних дій', self.text)

    def test_power_supply_is_named_and_each_location_keeps_its_own_clock(self):
        general = self.text.split('1.2. Сповіщення')[0]
        self.assertIn('Анонсовано відключення електропостачання', general)
        self.assertIn('ВІЛЬНОГІРСЬК (з 08:00 до 18:00)', general)
        for name in ('САДКИ', 'ШИРОКЕ'):
            self.assertIn(name+' (з 07:30 до 18:00)', general)
            self.assertNotIn(name+' (з 08:00', general)

    def test_changed_second_interval_never_changes_first_city(self):
        from fallback_report import brief_service
        post = next(p for p in F['posts'] if p['key'] == 'cek_info/4263')
        post = dict(post, text=post['text'].replace('з 07:30 до 18:00', 'з 10:15 до 16:45'))
        out = brief_service(post, date(2026,10,22))
        self.assertIn('ВІЛЬНОГІРСЬК (з 08:00 до 18:00)', out)
        for name in ('САДКИ', 'ШИРОКЕ'):
            self.assertIn(name+' (з 10:15 до 16:45)', out)

    def test_shared_village_interval_and_streets_do_not_cross_locations(self):
        from fallback_report import brief_service
        post = next(p for p in F['posts'] if p['key'] == 'cek_info/4263')
        out = brief_service(post, date(2026,10,22))
        city, sadky, shyroke = out.split('; ')
        self.assertNotIn('Будівельна', city)
        self.assertNotIn('Захисників України', sadky)
        self.assertIn('вул. Будівельна', sadky)
        self.assertNotIn('Будівельна', shyroke)

    def test_single_oblast_paragraph_and_locality_groups_do_not_create_attack_total(self):
        attack = self.text.split('2.1. Обстріли')[1].split('2.2. Незаконне')[0]
        self.assertEqual(attack.count('Денне зведення за'), 1)
        self.assertEqual(attack.count('Ранкове зведення за'), 1)
        self.assertNotIn('Обласне зведення на', attack)
        self.assertIn('\nДніпро:\n', attack)
        self.assertIn('\nПавлоград:\n', attack)
        self.assertIn('\nНікопольщина:\n', attack)
        self.assertIn('Денне зведення за 21 жовтня (станом на 18:30): Понад 50', attack)
        self.assertIn('Ранкове зведення за 22 жовтня (станом на 07:30): Понад 20', attack)
        self.assertNotIn('70 разів', attack)

    def test_each_local_consequence_remains_under_its_source_bulletin(self):
        for r in self.registry['records']:
            if r['reporting_period'] and r['state'] == 'included' and r['scope'] != 'Дніпропетровська область':
                if r['source_text'].startswith('Всюди минулося'):
                    continue
                at = datetime.fromisoformat(r['reporting_period'])
                facts=[p for p in self.registry['public_projection']['provenance'] if r['id'] in p.get('record_ids',[])]
                self.assertTrue(facts)
                self.assertTrue(all(p['reporting_period']==r['reporting_period'] for p in facts))

    def test_grouping_does_not_label_suburbs_as_city(self):
        from fact_registry import public_attack_paragraphs
        record = dict(next(r for r in self.registry['records'] if r['source_key']=='dnipropetrovskaODA/32729'))
        record['source_text'] = record['display'] = 'У передмісті Дніпра пошкоджені склади.'
        out = '\n\n'.join(public_attack_paragraphs({'records':[record],'sections':{'2.1':[]}}))
        self.assertTrue(out.startswith('Передмістя Дніпра:'))
        self.assertFalse(out.startswith('Дніпро:'))

    def test_multi_district_outage_count_never_assigned_to_one_district(self):
        paragraph = self.text.split('Інші підтверджені наслідки:\n')[1].split('\n\n')[0]
        self.assertIn('понад 30 тисяч', paragraph)
        self.assertIn('Павлоградському, Синельниківському районах і місті Самар', paragraph)
        for heading in ('Синельниківський район:', 'Павлоград:'):
            if '\n'+heading+'\n' in self.text:
                local = self.text.split('\n'+heading+'\n')[1].split('\n\n')[0]
                self.assertNotIn('30 тисяч', local)


if __name__ == '__main__':
    unittest.main()
