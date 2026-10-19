import json
from pathlib import Path
import unittest

from ai_report import validate_report
from report_sections import recover_transport_section,recover_attack_section
from report_rules import house_counts,required_house_counts,source_problems,report_section
from test_source_accuracy import source,report

F=json.loads((Path(__file__).parent/'fixtures/coverage_20261019.json').read_text())


class FactCoverageTests(unittest.TestCase):
    def test_actual_passed_editor_draft_is_rejected_for_both_omissions(self):
        self.assertEqual(F['debug']['attempts'][-1]['validation'],'passed')
        with self.assertRaises(ValueError) as e:
            validate_report(F['delivered_dry_report'],'19.10.2026',posts=F['posts'])
        self.assertIn('missing source transport routes',str(e.exception))
        self.assertIn('missing source housing count: destroyed',str(e.exception))

    def test_actual_report_recovers_routes_road_segment_and_latest_housing(self):
        text=recover_transport_section(F['delivered_dry_report'],F['posts'])
        text=recover_attack_section(text,F['posts'],'19.10.2026')
        validate_report(text,'19.10.2026',posts=F['posts'])
        for phrase in ('№6К','№9К','№23','№18','№134','Харківської','Європейської',
                       'Січеславська Набережна','Ще три оселі зруйновані','84-річна'):
            self.assertIn(phrase,text)
        for section in ('1.1','1.3','1.4','2.2','2.3','2.4'):
            self.assertEqual(report_section(text,section),report_section(F['delivered_dry_report'],section))

    def test_latest_housing_number_is_required_but_older_number_need_not_be_repeated(self):
        items=[source('У Дніпрі зруйновано п’ять будинків.'),source('У Дніпрі зруйновано сім будинків.')]
        self.assertEqual(required_house_counts(items)['destroyed'],{7})
        self.assertIn('missing source housing count: destroyed',source_problems(report('У Дніпрі зруйновано п’ять будинків.'),items))
        self.assertNotIn('missing source housing count: destroyed',source_problems(report('У Дніпрі зруйновано сім будинків.'),items))

    def test_destroyed_and_damaged_numbers_are_not_interchangeable(self):
        items=[source('У Дніпрі три будинки зруйновані, сім будинків пошкоджені.')]
        errors=source_problems(report('У Дніпрі сім будинків пошкоджені.'),items)
        self.assertIn('missing source housing count: destroyed',errors)
        self.assertNotIn('missing source housing count: damaged',errors)

    def test_different_cities_do_not_supersede_each_others_counts(self):
        items=[source('У Дніпрі зруйновано п’ять будинків.'),source('У Павлограді зруйновано сім будинків.')]
        self.assertEqual(required_house_counts(items)['destroyed'],{5,7})

    def test_elliptical_damage_count_after_house_and_conjunction_is_recognized(self):
        counts=house_counts('Один зруйнований будинок і щонайменше три пошкоджені.')
        self.assertEqual(counts,{'destroyed':{1},'damaged':{3}})

    def test_transport_coverage_uses_other_route_numbers_and_road_names(self):
        items=[source('Через ремонт колії на Соборному мосту призупинено трамвай №42.', '1.2'),
               source('Тролейбус №77 курсує через Південний міст; автобус №218 через площу Миру.', '1.2')]
        raw=report('Атак немає.').replace('1.2. У перевірених джерелах повідомлень за звітний період не виявлено.',
                                        '1.2. У місті діють зміни руху.')
        self.assertIn('missing source transport routes',source_problems(raw,items))
        text=recover_transport_section(raw,items)
        for phrase in ('№42','№77','№218','Соборному','Південний','площу Миру'):
            self.assertIn(phrase,text)
        self.assertNotIn('№6К',text)

    def test_complete_route_numbers_do_not_hide_a_missing_closure_segment(self):
        text=recover_transport_section(F['delivered_dry_report'],F['posts'])
        incomplete=text.replace('від вул. Харківської до вул. Європейської','')
        self.assertIn('missing source transport location or closure segment',source_problems(incomplete,F['posts']))
        rebuilt=recover_transport_section(incomplete,F['posts'])
        self.assertIn('від вул. Харківської до вул. Європейської',rebuilt)
