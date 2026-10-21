import json
import os
import re
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import collector as c
from core_review import review_core, validate_review
from fact_registry import compile_registry, render_registry
from operational_facts import current_attack_piece, background_reason, warehouse_supplement

F = json.loads((Path(__file__).parent/'fixtures/source_core_20261021.json').read_text())
NOW = datetime.fromisoformat(F['status']['checked_at'])


class FrozenMorningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.core = compile_registry(F['posts'], F['status']['channels'], NOW)
        cls.text = render_registry(cls.core)

    def test_reproduces_bad_delivered_report_then_removes_unrelated_material(self):
        self.assertGreater(len(F['delivered'].split()), 900)
        for phrase in ('Конгресові діалоги', 'відкрив форум', '72 години', 'вчорашньої',
                       'травні та червні', 'готові не бити', 'павербанки', '№'):
            self.assertNotIn(phrase, self.text)
        self.assertLessEqual(len(self.text.split()), 500)
        self.assertFalse(self.core['review_required'])

    def test_both_bulletin_periods_and_all_communities_survive_once(self):
        self.assertEqual(self.text.count('Майже 70'), 1)
        self.assertEqual(self.text.count('Майже 30'), 1)
        for phrase in ('Петропавлівська', 'Грушівській', 'Томаківська', 'Червоногригорівська',
                       'Миколаївській', 'Дніпровському районі', 'гуртожитку'):
            self.assertIn(phrase.lower()[:9], self.text.lower())
        self.assertNotIn('Майже 100', self.text)

    def test_deaths_and_injuries_stay_local_not_regional_sum(self):
        block=self.text.split('У Дніпрі понівечені склади')[1].split('На Синельниківщині')[0]
        self.assertIn('Двоє чоловіків', block)
        self.assertIn('Четверо людей дістали поранень', block)
        self.assertNotIn('семеро', block)
        for age in ('65-річного','66-річний','41-річний','50-річного'):
            self.assertIn(age, self.text)

    def test_archive_keeps_excluded_old_episode_and_original_eight_injured(self):
        old=[r for r in self.core['records'] if r['source_key']=='dnipropetrovskaODA/32714']
        self.assertTrue(old)
        self.assertEqual(old[0]['state'], 'excluded')
        self.assertIn('восьмеро', old[0]['source_text'])
        self.assertIn('П’ятеро', old[0]['source_text'])
        self.assertNotIn('Кривий Ріг', self.text)

    def test_mixed_police_post_keeps_current_fire_but_not_old_city_casualty(self):
        self.assertIn('виникла пожежа', self.text)
        self.assertIn('загасили пожежу', self.text)
        self.assertNotIn('55-річ', self.text)
        self.assertTrue(any(r['source_key']=='gunpvdp/37246' and r.get('display')
                            for r in self.core['records']))

    def test_published_time_does_not_become_attack_time_and_five_points(self):
        self.assertNotIn('Повідомлення від 11:00', self.text)
        self.assertEqual(re.findall(r'(?m)^([12]\.[1-4])\.', self.text),
                         ['1.1','1.2','2.1','2.2','2.3'])


class SelectionBoundaryTests(unittest.TestCase):
    def test_relative_old_day_across_month_boundary(self):
        start=NOW.replace(month=11,day=1,hour=5)
        value,reason=current_attack_piece('Після вчорашньої атаки двоє поранених.',
                                          start+timedelta(hours=2),start,start+timedelta(days=1))
        self.assertIsNone(value)

    def test_current_yesterday_is_not_automatically_old(self):
        start=NOW-timedelta(days=1)
        body='Після вчорашньої атаки двоє поранених.'
        value,_=current_attack_piece(body,NOW,start,NOW)
        self.assertEqual(value,body)

    def test_forum_reference_does_not_exclude_a_direct_attack(self):
        self.assertIsNone(background_reason('У Дніпрі ворог атакував будинок біля форуму. Двоє поранених.'))

    def test_new_objects_not_lost_due_to_shared_city(self):
        p=dict(F['posts'][0],key='adm_dp/999999',channel='adm_dp',
               published_at='2026-10-20T16:00:00+00:00',
               text='Ворог атакував Нікополь. Пошкоджено церкву.')
        text=render_registry(compile_registry(F['posts']+[p],{},NOW))
        self.assertIn('церкву',text)

    def test_swapped_warehouse_roles_block_even_with_same_number_set(self):
        target={'reporting_period':'2026-10-20T18:30:00+03:00',
                'source_text':'У Дніпрі понівечені склади. Двоє загинули. Четверо поранені.'}
        out=warehouse_supplement('У Дніпрі на складах четверо загинули. Двоє поранені.',
                                [target],NOW-timedelta(days=1))
        self.assertTrue(out['conflict'])


class ReviewerSafetyTests(unittest.TestCase):
    def setUp(self):
        self.core=compile_registry(F['posts'],F['status']['channels'],NOW)
        self.text=render_registry(self.core)

    def test_json_fence_is_accepted_without_ignoring_surrounding_prose(self):
        self.assertEqual(validate_review('```json\n{"issues":[]}\n```',self.core),[])
        for raw in ('Comment\n```json\n{"issues":[]}\n```',
                    '{"issues":[],"issues":[]}', '{"issues":[],"report":"replacement"}'):
            with self.subTest(raw=raw),self.assertRaises(ValueError):
                validate_review(raw,self.core)

    @patch.dict(os.environ,{'REPORT_PROVIDER':'gemini','GEMINI_API_KEY':'test','REPORT_CORE_REVIEW':'true'})
    def test_malformed_success_response_is_not_treated_as_unavailable(self):
        with patch('core_review.request_text',return_value='not JSON') as request:
            result=review_core(self.core,self.text)
        self.assertEqual(result['state'],'invalid_response')
        self.assertEqual(request.call_count,1)

    def test_oversize_is_blocked_before_any_model_call(self):
        with patch('core_review.request_text') as request:
            result=review_core(self.core,'word '*501)
        request.assert_not_called()
        self.assertEqual(result['state'],'blocked_length')
        self.assertEqual(result['requests'],0)

    @patch.dict(os.environ,{'REPORT_PROVIDER':'gemini','GEMINI_API_KEY':'test','REPORT_CORE_REVIEW':'true'})
    def test_bad_api_envelope_json_blocks_too(self):
        with patch('core_review.request_text',side_effect=json.JSONDecodeError('bad envelope','',0)):
            result=review_core(self.core,self.text)
        self.assertEqual(result['state'],'invalid_response')

    @patch.dict(os.environ,{'REPORT_PROVIDER':'gemini','GEMINI_API_KEY':'test','REPORT_CORE_REVIEW':'true'})
    def test_actual_saved_response_with_unknown_codes_blocks(self):
        responses=json.loads((Path(__file__).parent/'fixtures/review_response_20261021.json').read_text())
        for raw in responses:
            with patch('core_review.request_text',return_value=raw):
                result=review_core(self.core,self.text)
            self.assertEqual(result['state'],'invalid_response')

    def test_invalid_review_blocks_delivery_and_does_not_touch_delivery_state(self):
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(c,'DATA_DIR',Path(folder)), \
             patch.object(c,'MORNING_REPORT_FILE',Path(folder)/'morning.md'), \
             patch.object(c,'read_alert_state',return_value={}), \
             patch.dict(os.environ,{'SEND_MORNING_REPORT':'true','FORCE_MORNING_REPORT':'false'}), \
             patch('core_review.review_core',return_value={'state':'invalid_response','requests':1,'issues':[]}), \
             patch.object(c,'deliver_morning_report') as send:
            with self.assertRaisesRegex(RuntimeError,'manual review'):
                c.process_morning_report(F['posts'],F['status']['channels'],NOW)
            send.assert_not_called()
            status=json.loads(Path(folder,'report_generation_status.json').read_text())
            self.assertEqual(status['delivery_state'],'blocked_review')
            self.assertFalse(Path(folder,'report_delivery_status.json').exists())


if __name__=='__main__':
    unittest.main()
