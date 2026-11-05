import copy
import json
import unittest
from pathlib import Path
from datetime import datetime
from unittest.mock import patch

from detail_policy import (clean_detail_prose, missing_detail_formula,
                           unsupported_object_types, DETAIL_RULES)
from source_claims import selected_text, select_units
from fact_registry import compile_registry, render_registry
from ai_report import build_prompt, build_review_prompt
from report_rules import source_problems
from report_contract import publication_issues


class DetailPolicyTests(unittest.TestCase):
    def test_exact_user_examples_are_omitted(self):
        for text in [
            'Точний час влучань, населений пункт і назву об’єкта у перевірених повідомленнях не наведено.',
            'Назву підприємства, конкретну локацію і точний час влучань у перевірених повідомленнях не наведено.',
            'Точний час влучань, назви та призначення пошкоджених об’єктів у перевірених повідомленнях не уточнено.',
            'Назву об’єкта не уточнено.', 'Точний час атаки не наведено.',
        ]:
            with self.subTest(text=text):
                self.assertTrue(missing_detail_formula(text))
                self.assertEqual(clean_detail_prose(text), '')

    def test_no_loss_of_adjacent_real_facts_or_medical_uncertainty(self):
        disclaimer='Точний час атаки не наведено.'
        facts='Близько 01:20 БпЛА влучив у склад. Попередньо поранено двох людей. Під завалами можуть перебувати люди.'
        self.assertEqual(clean_detail_prose(disclaimer+' '+facts), facts)
        self.assertEqual(selected_text(disclaimer+' '+facts), facts)
        self.assertFalse(missing_detail_formula(disclaimer+' '+facts))
        self.assertFalse(any(u['disposition']=='required' for u in select_units(disclaimer)))

    def test_unsupported_logistics_is_detected_and_confirmed_logistics_kept(self):
        claim='У Новоолександрівській громаді пошкоджено логістичний комплекс.'
        generic=['У Новоолександрівській громаді пошкоджено інфраструктуру.']
        self.assertIn('unsupported object type: logistics facility',unsupported_object_types(claim,generic))
        self.assertEqual(unsupported_object_types(claim,[claim]),[])

    def test_type_cannot_be_borrowed_from_another_community_or_city(self):
        claim='У Новоолександрівській громаді пошкоджено логістичний комплекс.'
        self.assertTrue(unsupported_object_types(claim,['У Слобожанській громаді пошкоджено логістичний комплекс.']))
        self.assertTrue(unsupported_object_types('У Дніпрі пошкоджено підстанцію.', ['У Павлограді пошкоджено підстанцію.']))
        self.assertEqual(unsupported_object_types('Дніпро:\nПошкоджено підстанцію.', ['У Дніпрі пошкоджено підстанцію.']),[])
        self.assertTrue(unsupported_object_types('Самар:\nПошкоджено підстанцію.', ['У Кам’янському пошкоджено підстанцію.']))

    def test_no_type_inference_from_power_or_water_outage(self):
        for body in ['Пошкоджено енергетичний об’єкт.', 'Пошкоджено водопровідну інфраструктуру.',
                     'Пошкоджено водозабір.', 'Пошкоджено насосну станцію.']:
            self.assertTrue(unsupported_object_types('Самар:\n'+body,['Самар:\nПошкоджено інфраструктуру. Немає світла та води.']))

    def test_rules_reach_author_and_editor(self):
        self.assertIn(DETAIL_RULES,build_prompt([], 'start', 'end', 'checked', []))
        self.assertIn(DETAIL_RULES,build_review_prompt('draft', [], 'start','end'))

    def test_model_source_validation_detects_invented_type(self):
        posts=[dict(text='У Новоолександрівській громаді пошкоджено інфраструктуру.',category_hint='2.1')]
        errors=source_problems('2.1. У Новоолександрівській громаді пошкоджено логістичний комплекс.\n2.2. Немає повідомлень.',posts)
        self.assertIn('unsupported object type: logistics facility',errors)

    def test_frozen_nov05_no_new_facts_or_source_mutation(self):
        f=json.loads((Path(__file__).parent/'fixtures/source_core_20261105.json').read_text())
        before=copy.deepcopy(f)
        with patch('requests.sessions.Session.request',side_effect=AssertionError('No network in replay')):
            r=compile_registry(f['posts'],f['status']['channels'],datetime.fromisoformat(f['status']['checked_at']))
            text=render_registry(r)
        self.assertEqual(f,before)
        self.assertNotIn('логістичний комплекс',text)
        self.assertNotIn('01:20',text)
        for fact in ['Новоолександрівській','Славгородській','Кам’янському','Павлограді','Дубовиківській']:
            self.assertIn(fact,text)
        self.assertFalse(any(x.startswith('unsupported object type:') for x in publication_issues(r,text,{})))
        # A known generic source cannot justify an invented facility type.
        # Insert in the attack section so the check cannot be bypassed by a footer.
        changed=text.replace('2.2. Незаконне', 'У Новоолександрівській громаді пошкоджено логістичний комплекс.\n\n2.2. Незаконне')
        self.assertIn('unsupported object type: logistics facility',publication_issues(r,changed,{}))


if __name__=='__main__':
    unittest.main()
