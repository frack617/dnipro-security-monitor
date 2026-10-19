import json
from pathlib import Path
import unittest

from ai_report import validate_report
from fact_scopes import extract_numeric_facts,numeric_scope_problems
from report_rules import source_problems,report_section
from report_sections import recover_attack_section,recover_transport_section
from test_source_accuracy import source,report


class NumericScopeTests(unittest.TestCase):
    def test_swapped_house_numbers_between_cities_are_rejected(self):
        p=[source('У Дніпрі зруйновано п’ять будинків.'),source('У Павлограді зруйновано сім будинків.')]
        bad='У Дніпрі зруйновано сім будинків. У Павлограді зруйновано п’ять будинків.'
        self.assertIn('unsupported numeric scope: destroyed',source_problems(report(bad),p))

    def test_correct_city_numbers_are_accepted(self):
        p=[source('У Дніпрі зруйновано п’ять будинків.'),source('У Павлограді зруйновано сім будинків.')]
        self.assertEqual(numeric_scope_problems('У Павлограді зруйновано сім будинків. У Дніпрі зруйновано п’ять будинків.',p),[])

    def test_comma_separated_city_counts_cannot_bypass_the_check(self):
        p=[source('У Дніпрі зруйновано п’ять будинків.'),source('У Павлограді зруйновано сім будинків.')]
        self.assertTrue(numeric_scope_problems('У Дніпрі зруйновано сім будинків, у Павлограді зруйновано п’ять будинків.',p))
        self.assertEqual(numeric_scope_problems('У Дніпрі зруйновано п’ять будинків, у Павлограді зруйновано сім будинків.',p),[])

    def test_joint_city_count_is_not_distributed_between_cities(self):
        p=[source('У Дніпрі та у Павлограді зруйновано сім будинків.')]
        self.assertTrue(numeric_scope_problems('У Дніпрі зруйновано сім будинків.',p))

    def test_conjunction_between_independent_city_counts_is_supported(self):
        p=[source('У Дніпрі зруйновано п’ять будинків та у Павлограді зруйновано сім будинків.')]
        self.assertEqual(numeric_scope_problems('У Дніпрі зруйновано п’ять будинків. У Павлограді зруйновано сім будинків.',p),[])

    def test_city_and_district_are_not_interchangeable(self):
        p=[source('У Дніпровському районі зруйновано три будинки.')]
        self.assertTrue(numeric_scope_problems('У Дніпрі зруйновано три будинки.',p))

    def test_joint_community_number_cannot_be_assigned_to_one_community(self):
        p=[source('У Покровській та Марганецькій громадах зруйновано сім будинків.')]
        self.assertTrue(numeric_scope_problems('У Покровській громаді зруйновано сім будинків.',p))

    def test_new_community_cannot_inherit_parent_number(self):
        p=[source('У Синельниківському районі зруйновано три будинки.')]
        self.assertTrue(numeric_scope_problems('У Зайцівській громаді Синельниківського району зруйновано три будинки.',p))

    def test_swapped_attack_count_and_district_scopes_are_rejected(self):
        p=[source('18 жовтня. Понад 20 разів ворог атакував чотири райони.'),
           source('19 жовтня. Понад 10 разів ворог атакував три райони.')]
        bad='18 жовтня понад 10 разів ворог атакував чотири райони. 19 жовтня понад 20 разів ворог атакував три райони.'
        self.assertIn('unsupported numeric scope: attacks',source_problems(report(bad),p))

    def test_equal_attack_counts_do_not_hide_swapped_dates(self):
        p=[source('18 жовтня. Понад 20 разів ворог атакував чотири райони.'),
           source('19 жовтня. Понад 20 разів ворог атакував три райони.')]
        self.assertTrue(numeric_scope_problems('18 жовтня понад 20 разів ворог атакував три райони. 19 жовтня понад 20 разів ворог атакував чотири райони.',p))

    def test_explicit_regional_header_prevents_reassignment_to_city_districts(self):
        p=[source('Дніпропетровщина\n18 жовтня\nПонад 20 разів ворог атакував чотири райони.')]
        self.assertTrue(numeric_scope_problems('18 жовтня у Дніпрі понад 20 разів ворог атакував чотири райони.',p))

    def test_explicit_morning_and_night_counts_cannot_be_swapped(self):
        p=[source('Вранці у Дніпрі зруйновано п’ять будинків.'),source('Вночі у Дніпрі зруйновано сім будинків.')]
        self.assertTrue(numeric_scope_problems('Вночі у Дніпрі зруйновано п’ять будинків. Вранці у Дніпрі зруйновано сім будинків.',p))

    def test_regional_downed_total_is_not_a_city_total(self):
        p=[source('21 ворожий БпЛА збили над Дніпропетровщиною.')]
        self.assertTrue(numeric_scope_problems('У Дніпрі збили 21 ворожий БпЛА.',p))
        self.assertEqual(numeric_scope_problems('Над областю збили 21 ворожий БпЛА.',p),[])

    def test_publication_date_is_not_assumed_to_be_incident_date(self):
        p=[source('У Дніпрі зруйновано три будинки.')]
        self.assertEqual(numeric_scope_problems('18 жовтня у Дніпрі зруйновано три будинки.',p),[])

    def test_bulletin_clock_and_morning_publication_are_not_incident_time(self):
        facts=extract_numeric_facts('19 жовтня\n8:00\nЗа ранковим зведенням станом на 08:00 19 жовтня: Понад 20 разів ворог атакував три райони.')
        self.assertEqual(len(facts),1)
        self.assertIsNone(facts[0].clock)
        self.assertIsNone(facts[0].periods)

    def test_explicit_incident_clock_numbers_cannot_be_swapped(self):
        p=[source('У Дніпрі о 03:00 зруйновано п’ять будинків.'),source('У Дніпрі о 06:30 зруйновано сім будинків.')]
        self.assertTrue(numeric_scope_problems('У Дніпрі о 06:30 зруйновано п’ять будинків. У Дніпрі о 03:00 зруйновано сім будинків.',p))

    def test_multi_district_summary_does_not_inherit_last_city(self):
        p=[source('19 жовтня. Понад 20 разів ворог атакував три райони області.'),source('У Дніпрі пошкоджено будинок.')]
        self.assertEqual(numeric_scope_problems('У Дніпрі пошкоджено будинок. 19 жовтня понад 20 разів ворог атакував три райони області.',p),[])

    def test_age_does_not_become_a_numeric_fact(self):
        self.assertEqual(extract_numeric_facts('У Дніпрі госпіталізована 84-річна жінка.'),[])

    def test_actual_report_with_count_moved_to_another_community_recovers_locally(self):
        f=json.loads((Path(__file__).parent/'fixtures/coverage_20261019.json').read_text())
        text=recover_transport_section(f['delivered_dry_report'],f['posts'])
        text=recover_attack_section(text,f['posts'],'19.10.2026')
        bad=text.replace('Ще три оселі зруйновані. ','').replace(
            'У Зайцівській громаді Синельниківського району сталася пожежа.',
            'У Зайцівській громаді Синельниківського району сталася пожежа. Ще три оселі зруйновані.')
        with self.assertRaisesRegex(ValueError,'unsupported numeric scope: destroyed'):
            validate_report(bad,'19.10.2026',posts=f['posts'])
        out=recover_attack_section(bad,f['posts'],'19.10.2026')
        validate_report(out,'19.10.2026',posts=f['posts'])
        for s in ('1.1','1.2','1.3','1.4','2.2','2.3','2.4'):
            self.assertEqual(report_section(out,s),report_section(text,s))
