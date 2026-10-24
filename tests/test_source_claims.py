import copy
import json
import os
from datetime import datetime
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fact_registry import compile_registry,render_registry
from report_contract import publication_issues
from source_claims import select_units,clause_coverage,medical_role_counts

ROOT=Path(__file__).resolve().parents[1]
F=json.loads((ROOT/'tests/fixtures/source_core_20261024.json').read_text())
NOW=datetime.fromisoformat(F['status']['checked_at'])


def make(text):
    post=dict(key='adm_dp/claims-probe',channel='adm_dp',published_at='2026-10-23T11:00:00+00:00',
              url='https://example.invalid/probe',text=text)
    r=compile_registry([post],F['status']['channels'],NOW)
    return r,render_registry(r)


class SourceClaimTests(unittest.TestCase):
    def test_unknown_assertion_is_an_obligation_not_a_keyword_exclusion(self):
        units=select_units('Виведено 13 мешканців. Стався витік хлору.')
        self.assertEqual(len(units),2)
        self.assertTrue(all(u['disposition']=='required' for u in units))
        self.assertIn('opaque',units[1]['predicates'])

    def test_whole_boilerplate_only_not_a_prefix_of_new_consequence(self):
        units=select_units('Медики надають їм допомогу, одну дитину евакуювали.')
        self.assertEqual(units[0]['disposition'],'required')

    def test_sentence_numbers_keep_roles_and_source_coordinates(self):
        units=select_units('Поранено 3 людей. Зруйновано 2 будинки.','adm_dp/example')
        self.assertEqual(units[0]['quantity_roles'],{'injured':3})
        self.assertEqual(units[1]['quantity_roles'],{})
        self.assertEqual(units[0]['numeric_surfaces'],['3'])
        self.assertEqual(units[0]['source_span']['basis'],'normalized_selection')
        self.assertNotEqual(units[0]['id'],units[1]['id'])

    def test_full_source_body_order_does_not_create_same_id_for_two_occurrences(self):
        units=select_units('Пошкоджено будинок. Пошкоджено будинок.','adm_dp/x')
        self.assertEqual(len({u['id'] for u in units}),2)

    def test_a_shared_object_is_not_complete_source_coverage(self):
        self.assertIsNone(clause_coverage('Пошкоджено підприємство. Евакуйовано 5 людей.',
                                         'Пошкоджено підприємство.'))
        self.assertIsNone(clause_coverage('Ворог атакував лікарню.',
                                         'У Дніпрі пошкоджено приватний будинок.'))

    def test_unfamiliar_damage_object_or_modifier_survives(self):
        for text in ['Пошкоджено підприємство та кисневу станцію.',
                     'Пошкоджено 3 підприємства.','Вщент знищено підприємство.']:
            self.assertIsNone(clause_coverage(text,'Пошкоджено підприємство.'))

    def test_negated_damage_does_not_prove_positive_damage(self):
        self.assertIsNone(clause_coverage('Пошкоджено приватні будинки.',
                                         'Приватні будинки не пошкоджено.'))

    def test_both_communities_in_a_list_must_be_covered(self):
        self.assertIsNone(clause_coverage('У Лозуватській та Новопільській громадах пошкоджено приватні будинки.',
                                         'У Новопільській громаді пошкоджено приватні будинки.'))

    def test_street_or_building_number_is_not_generic_city_damage(self):
        self.assertIsNone(clause_coverage('На вул. Центральній пошкоджено приватні будинки.',
                                         'У Дніпрі пошкоджено приватні будинки.'))

    def test_hospitalized_is_not_the_total_injured(self):
        self.assertEqual(medical_role_counts('Четверо людей у лікарні.'),{'hospitalized':4})
        self.assertIsNone(clause_coverage('Четверо людей у лікарні.',
                                         'Поранено 6 людей. Вони лікуватимуться амбулаторно.'))

    def test_severe_status_cannot_be_covered_by_only_moderate_status(self):
        self.assertIsNone(clause_coverage('Поранено двох людей. Один у вкрай тяжкому стані.',
                                         'Поранено двох людей. Вони у стані середньої тяжкості.'))

    def test_an_equal_count_in_another_city_is_not_coverage(self):
        posts=[dict(key='adm_dp/1',channel='adm_dp',published_at='2026-10-23T11:00:00+00:00',
                    text='23 жовтня ворог атакував Нікополь. Евакуйовано 7 людей.',url='https://example.invalid/1'),
               dict(key='adm_dp/2',channel='adm_dp',published_at='2026-10-23T12:00:00+00:00',
                    text='23 жовтня ворог атакував Павлоград. Евакуйовано 7 людей.',url='https://example.invalid/2')]
        r=compile_registry(posts,{},NOW);text=render_registry(r)
        self.assertEqual(text.count('Евакуйовано 7 людей'),2)

    def test_opaque_clause_removed_after_render_is_detected(self):
        r,text=make('23 жовтня ворог атакував Дніпро. Пошкоджено лікарню. Стався витік азоту.')
        self.assertEqual(publication_issues(r,text,{}),[])
        changed=text.replace('Стався витік азоту.','')
        self.assertIn('lost_source_claim',publication_issues(r,changed,{}))

    def test_a_source_pointer_is_not_proof_of_a_missing_rescue_fact(self):
        r,text=make('23 жовтня ворог атакував Дніпро. Пошкоджено лікарню. Врятовано 4 дітей.')
        self.assertTrue(r['public_projection']['provenance'])
        changed=text.replace('Врятовано 4 дітей.','')
        self.assertIn('lost_source_claim',publication_issues(r,changed,{}))

    def test_fact_moved_to_another_place_is_detected(self):
        r,text=make('23 жовтня ворог атакував Дніпро. Пошкоджено лікарню. Евакуйовано 9 пацієнтів.')
        changed=text.replace('Дніпро:\n','Павлоград:\n')
        self.assertIn('lost_source_claim',publication_issues(r,changed,{}))

    def test_real_days_have_no_unresolved_source_obligations(self):
        for d in range(20,25):
            f=json.loads((ROOT/f'tests/fixtures/source_core_202610{d}.json').read_text())
            r=compile_registry(f['posts'],f['status']['channels'],datetime.fromisoformat(f['status']['checked_at']))
            text=render_registry(r)
            self.assertTrue(r['claim_plan'])
            self.assertFalse([u for u in r['claim_plan'] if u['disposition']=='unresolved'],d)
            self.assertLessEqual(len(text.split()),500)

    def test_missing_fact_blocks_before_reviewer_and_delivery(self):
        import collector as c
        posts=copy.deepcopy(F['posts'])
        posts.append(dict(key='adm_dp/claims-new',channel='adm_dp',post_id=999999,
                          published_at='2026-10-23T13:00:00+00:00',url='https://example.invalid/new',
                          text='23 жовтня ворог атакував Дніпро. Пошкоджено лікарню. Евакуйовано 17 пацієнтів.'))
        real_render=render_registry
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            with patch.object(c,'DATA_DIR',root),patch.object(c,'MORNING_REPORT_FILE',root/'morning_report.md'), \
                 patch.object(c,'read_alert_state',return_value={'last_daily_report':'2026-10-23'}), \
                 patch.dict(os.environ,{'SEND_MORNING_REPORT':'true','PRODUCTION_MONITOR':'true','FORCE_MORNING_REPORT':'false'}), \
                 patch('fact_registry.render_registry',side_effect=lambda r:real_render(r).replace('Евакуйовано 17 пацієнтів.','')), \
                 patch('core_review.review_core') as reviewer,patch.object(c,'deliver_morning_report') as delivery, \
                 patch.object(c,'send_bot_message'):
                with self.assertRaises(RuntimeError):c.process_morning_report(posts,F['status']['channels'],NOW)
                reviewer.assert_not_called();delivery.assert_not_called()
                status=json.loads((root/'report_generation_status.json').read_text())
                self.assertIn('lost_source_claim',status['publication_issues'])


class FinishedBriefAcceptanceTests(unittest.TestCase):
    def test_finished_document_acceptance_is_part_of_release_checks(self):
        from evaluation.acceptance import worker
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(worker(ROOT,Path(td)),0)


if __name__=='__main__':unittest.main()
