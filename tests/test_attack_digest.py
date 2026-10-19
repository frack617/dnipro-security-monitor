from datetime import date
import json
from pathlib import Path
import unittest

from ai_report import validate_report
from attack_digest import grouped_attack_text, explicit_place
from fallback_report import build_sections
from report_rules import before_bulletin_boundary, source_problems, place_casualty_problems, casualty_location_problems
from report_sections import recover_attack_section, recover_transport_section
from test_source_accuracy import source, report

F=json.loads((Path(__file__).parent/'fixtures/attack_recovery_20261019.json').read_text())


def post(text,at='2026-10-19T04:00:00Z'):
    return dict(source(text),published_at=at,published_local='19.10.2026 07:00 за Києвом')


class AttackDigestTests(unittest.TestCase):
    def test_real_updates_are_grouped_without_losing_numbers_or_uncertainty(self):
        raw=recover_transport_section(F['debug']['attempts'][1]['validated_text'],F['posts'])
        out=recover_attack_section(raw,F['posts'],'19.10.2026')
        validate_report(out,'19.10.2026',posts=F['posts'])
        text=grouped_attack_text([p for p in F['posts'] if p['category_hint']=='2.1'])
        self.assertEqual(text.count('Повідомлення від 19 жовтня:'),1)
        self.assertEqual(text.count('Дніпро.'),2)
        for phrase in ('один будинок зруйнований','Ще три оселі зруйновані',
                       '84-річна','21 ворожий БпЛА','можуть бути заблоковані люди',
                       'критичної інфраструктури','Зайцівській','Лікуватиметься амбулаторно'):
            self.assertIn(phrase,text)
        self.assertEqual(text.lower().count('понад 20 разів'),2)
        self.assertNotIn('чотири будинки зруйновані',text)
        self.assertIn('Пошкоджені приватні будинки. За попередньою інформацією, у них можуть бути заблоковані люди.',text)
        self.assertIn('Зведення: Понівечені інфраструктура, приватні будинки.',text)
        self.assertEqual(text.count('Працюють усі служби.'),0)
        self.assertEqual(text.count('На місці працюють усі служби.'),1)

    def test_new_attack_and_its_generic_damage_are_preserved(self):
        posts=[post('У Дніпрі пошкоджені приватні будинки.'),
               post('19 жовтня 8:00 Понад 20 разів ворог атакував три райони. '
                    '▪ У Дніпрі ворог знову атакував житло. Понівечені приватні будинки.',
                    '2026-10-19T05:00:17Z')]
        text=grouped_attack_text(posts)
        self.assertIn('Пошкоджені приватні будинки.',text)
        self.assertIn('знову атакував',text)

    def test_dependent_housing_warning_keeps_its_antecedent(self):
        for continuation in ('У них можуть бути заблоковані люди.',
                             'Там можуть залишатися люди.',
                             'Їх обстежують рятувальники.',
                             'У цих будинках можуть бути люди.'):
            with self.subTest(continuation=continuation):
                items=[post('Росіяни завдали удару по Дніпру. Пошкоджені приватні будинки. '+continuation),
                       post('19 жовтня 8:00 Понад 20 разів ворог атакував три райони. '
                            '▪ У Дніпрі понівечені інфраструктура, приватні будинки.',
                            '2026-10-19T05:00:17Z')]
                text=grouped_attack_text(items)
                self.assertIn('Пошкоджені приватні будинки. '+continuation,text)

    def test_independent_generic_repeat_can_still_be_removed(self):
        items=[post('Росіяни завдали удару по Дніпру. Пошкоджені приватні будинки.'),
               post('19 жовтня 8:00 Понад 20 разів ворог атакував три райони. '
                    '▪ У Дніпрі понівечені інфраструктура, приватні будинки.',
                    '2026-10-19T05:00:17Z')]
        self.assertNotIn('Пошкоджені приватні будинки.',grouped_attack_text(items))

    def test_explicit_clocks_and_night_are_not_merged_away(self):
        posts=[post('У Дніпрі о 02:00 пошкоджені будинки. Троє людей поранені.'),
               post('У Дніпрі вранці о 06:30 двоє людей поранені.')]
        text=grouped_attack_text(posts)
        for phrase in ('02:00','06:30','Троє людей','двоє людей','вранці'):
            self.assertIn(phrase.lower(),text.lower())
        self.assertNotIn('п’ятеро',text)

    def test_city_district_and_mixed_places_stay_separate(self):
        self.assertEqual(explicit_place('У Дніпрі є пошкодження.'),'Дніпро')
        self.assertEqual(explicit_place('У Дніпровському районі є пошкодження.'),'Дніпровський район')
        self.assertIsNone(explicit_place('У Дніпрі та Павлограді є пошкодження.'))
        text=grouped_attack_text([post('У Дніпрі пошкоджено аптеку.'),
                                  post('У Дніпровському районі троє людей поранені.')])
        self.assertIn('У Дніпрі пошкоджено аптеку.',text)
        self.assertIn('У Дніпровському районі троє людей поранені.',text)

    def test_same_wording_on_different_dates_remains_present(self):
        items=[post('У Павлограді пошкоджено будинок.','2026-10-18T04:00:00Z'),
               post('У Павлограді пошкоджено будинок.','2026-10-19T04:00:00Z')]
        self.assertEqual(grouped_attack_text(items).count('пошкоджено будинок'),2)

    def test_earlier_injuries_survive_a_later_death(self):
        text=grouped_attack_text([post('У Павлограді четверо людей поранені.'),
                                  post('У Павлограді помер чоловік, поранений внаслідок атаки.',
                                       '2026-10-19T04:30:00Z')])
        self.assertIn('четверо людей поранені',text.lower())
        self.assertIn('помер чоловік',text.lower())
        self.assertNotIn('п’ятеро',text)

    def test_unknown_publication_date_is_not_guessed_from_clock(self):
        p=post('У Дніпрі о 06:30 пошкоджено будинок.')
        p.pop('published_at');p.pop('published_local')
        text=grouped_attack_text([p])
        self.assertIn('06:30',text)
        self.assertNotIn('Повідомлення від',text)

    def test_dated_bulletin_stops_previous_casualty_scope(self):
        section='У Зайцівській громаді Синельниківського району сталася пожежа. '
        section+='Повідомлення від 19 жовтня: За зведенням 19 жовтня: Троє людей поранені. '
        section+='У Дніпрі пошкоджено будинок.'
        items=[post('У Зайцівській громаді Синельниківського району сталася пожежа.'),
               post('Троє людей поранені. ▪ У Дніпрі пошкоджено будинок.')]
        self.assertEqual(place_casualty_problems(section,items),[])
        self.assertEqual(casualty_location_problems(section.lower(),items),[])
        wrong='У Зайцівській громаді Синельниківського району троє людей поранені. '
        wrong+='Повідомлення від 19 жовтня: У Дніпрі пошкоджено будинок.'
        self.assertTrue(place_casualty_problems(wrong,items))
        self.assertTrue(casualty_location_problems(wrong.lower(),items))

    def test_nonduplicate_service_consequence_is_not_removed(self):
        text=grouped_attack_text([post('У Дніпрі працюють усі служби.'),
                                  post('У Дніпрі знеструмлено лікарню. На місці працюють медики.')])
        self.assertIn('знеструмлено лікарню',text.lower())
        self.assertIn('працюють медики',text)

    def test_fallback_builder_uses_the_same_grouping(self):
        items=[post('У Дніпрі троє людей поранені.'),post('У Дніпрі пошкоджено будинок.')]
        text=build_sections({'2.1':items},date(2026,10,19))['2.1']
        self.assertEqual(text.count('Дніпро.'),1)
        self.assertIn('троє людей',text.lower())
        self.assertIn('Пошкоджено будинок',text)
