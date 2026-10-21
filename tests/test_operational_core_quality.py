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
from operational_facts import (current_attack_piece, background_reason,
                               warehouse_supplement, consolidate_warehouse_details)

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
        self.assertRegex(self.text.lower(), r'виникла(?: масштабна)? пожежа')
        self.assertIn('ліквідували вогнеборці', self.text)
        self.assertNotIn('55-річ', self.text)
        self.assertTrue(any('gunpvdp/37246' in r.get('detail_source_refs', [])
                            for r in self.core['records']))

    def test_fire_details_appear_only_inside_the_bulletin_warehouse_block(self):
        section=self.text.split('2.1. ')[1].split('2.2. ')[0]
        self.assertTrue(section.splitlines()[1].startswith('Обласне зведення'))
        block=section.split('У Дніпрі понівечені склади')[1].split('На Синельниківщині')[0]
        self.assertEqual(block.count('пожеж'),1)
        self.assertIn('масштабна пожежа, яку ліквідували вогнеборці',block)
        self.assertIn('Рятувальники виявили тіла.',block)
        self.assertEqual(block.count('Четверо людей дістали поранень'),1)
        self.assertNotIn('Повідомлення від',block)

    def test_published_time_does_not_become_attack_time_and_five_points(self):
        self.assertNotIn('Повідомлення від 11:00', self.text)
        self.assertEqual(re.findall(r'(?m)^([12]\.[1-4])\.', self.text),
                         ['1.1','1.2','2.1','2.2','2.3'])


class DetailMergeTests(unittest.TestCase):
    def records(self, detail):
        target={'id':'target','source_text':'У Дніпрі понівечені склади.',
                'display':'У Дніпрі понівечені склади.'}
        rec={'id':'detail','source_key':'source/1','warehouse_target':'target',
             'source_text':detail, 'detail_label':'У передмісті Дніпра, на складах',
             'detail_sentences':[detail], 'display':detail,'state':'included'}
        return [target,rec]

    def test_unfamiliar_material_and_number_are_preserved(self):
        records=self.records('Виникла пожежа, знищено три автомобілі.')
        records.append(dict(records[1],id='detail2',source_key='source/2',
            detail_sentences=['Виникла масштабна пожежа, яку ліквідували вогнеборці.']))
        consolidate_warehouse_details(records)
        self.assertIn('знищено три автомобілі',records[0]['display'])
        self.assertIn('ліквідували',records[0]['display'])
        self.assertEqual(records[1]['source_text'],'Виникла пожежа, знищено три автомобілі.')

    def test_merge_is_idempotent(self):
        records=self.records('Виникла масштабна пожежа, яку ліквідували вогнеборці.')
        consolidate_warehouse_details(records)
        once=records[0]['display']
        consolidate_warehouse_details(records)
        self.assertEqual(records[0]['display'],once)

    def test_unmatched_target_is_not_removed(self):
        records=self.records('Рятувальники загасили пожежу та виявили тіла.')
        records[1]['warehouse_target']='another event'
        consolidate_warehouse_details(records)
        self.assertEqual(records[1]['state'],'included')



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


class FutureWindowAndPlaceTests(unittest.TestCase):
    def setUp(self):
        from zoneinfo import ZoneInfo
        zone=ZoneInfo('Europe/Kyiv')
        self.start=datetime(2026,10,20,8,tzinfo=zone)
        self.end=datetime(2026,10,21,8,tzinfo=zone)
        self.published=datetime(2026,10,20,12,tzinfo=zone)

    def test_explicit_pre_cutoff_clock_is_not_publication_time(self):
        for city in ('Дніпро','Нікополь','Павлоград'):
            body='20 жовтня о 07:10 ворог атакував '+city+'. Поранений чоловік.'
            out,reason=current_attack_piece(body,self.published,self.start,self.end)
            self.assertIsNone(out)
            self.assertEqual(reason,'explicit_incident_outside_window')

    def test_exact_start_is_included_and_end_is_excluded(self):
        for text,inside in (('20 жовтня о 08:00 ворог атакував Дніпро.',True),
                            ('21 жовтня о 08:00 ворог атакував Дніпро.',False)):
            out,_=current_attack_piece(text,self.published,self.start,self.end)
            self.assertEqual(out is not None,inside)

    def test_current_date_without_clock_remains_undated_not_inferred_from_publication(self):
        body='20 жовтня ворог атакував Нікополь. Пошкоджено будинок.'
        out,_=current_attack_piece(body,self.published,self.start,self.end)
        self.assertEqual(out,body)
        self.assertNotIn('12:00',out)

    def test_new_incident_survives_relative_old_intro(self):
        body='Після вчорашньої атаки на Кривий Ріг залишаються поранені. У Дніпрі 20 жовтня ворог атакував підприємство.'
        out,_=current_attack_piece(body,self.published,self.start,self.end)
        self.assertEqual(out,'У Дніпрі 20 жовтня ворог атакував підприємство.')

    def test_two_explicit_dates_keep_new_locality_and_consequence(self):
        body='19 жовтня ворог атакував Кривий Ріг. У Павлограді 20 жовтня ворог атакував підприємство.'
        out,_=current_attack_piece(body,self.published,self.start,self.end)
        self.assertEqual(out,'У Павлограді 20 жовтня ворог атакував підприємство.')

    def test_same_day_earlier_and_later_clocks_split_only_at_sentence_boundary(self):
        body='20 жовтня о 07:10 ворог атакував Дніпро. У Нікополі 20 жовтня о 09:00 ворог атакував будинок.'
        out,_=current_attack_piece(body,self.published,self.start,self.end)
        self.assertEqual(out,'У Нікополі 20 жовтня о 09:00 ворог атакував будинок.')

    def test_inseparable_mixed_times_require_review_instead_of_losing_facts(self):
        body='20 жовтня о 07:10 ворог атакував Дніпро, а 20 жовтня о 09:00 ворог атакував Нікополь.'
        out,reason=current_attack_piece(body,self.published,self.start,self.end)
        self.assertEqual(out,body)
        self.assertEqual(reason,'mixed_incident_times_requires_review')

    def test_approximate_clock_at_boundary_requires_review(self):
        body='20 жовтня близько 08:00 ворог атакував Дніпро.'
        out,reason=current_attack_piece(body,self.published,self.start,self.end)
        self.assertEqual(out,body)
        self.assertTrue(reason.endswith('requires_review'))

    def test_source_publication_label_not_used_as_incident_clock(self):
        body='Повідомлення від 20 жовтня о 07:10: ворог атакував Дніпро.'
        out,_=current_attack_piece(body,self.published,self.start,self.end)
        self.assertEqual(out,body)

    def test_nikopol_consequences_are_never_attached_to_dnipro(self):
        target={'id':'target','reporting_period':'2026-10-20T18:30:00+03:00',
                'source_text':'У Дніпрі пошкоджені склади. Четверо поранені.'}
        body='У Дніпрі працюють служби. У Нікополі пошкоджені склади. Четверо поранені. Виникла пожежа.'
        result=warehouse_supplement(body,[target],self.published)
        self.assertTrue(result['conflict'])
        self.assertIsNone(result['display'])

    def test_explicit_separate_attack_or_clock_is_not_collapsed(self):
        target={'id':'target','reporting_period':'2026-10-20T18:30:00+03:00',
                'source_text':'У Дніпрі пошкоджені склади. Четверо поранені.'}
        for lead in ('Окрема атака: ', 'Після повторної атаки ', 'О 09.15 '):
            body=lead+'у Дніпрі пошкоджені склади. Четверо поранені. Виникла пожежа.'
            with self.subTest(lead=lead):
                result=warehouse_supplement(body,[target],self.published)
                self.assertTrue(result['conflict'])

    def test_uncertain_time_prevents_delivery_in_registry(self):
        body='20 жовтня близько 08:00 ворог атакував Дніпро. Поранений чоловік.'
        post={'key':'adm_dp/9998','channel':'adm_dp','published_at':self.published.isoformat(),'text':body}
        core=compile_registry([post],{},NOW)
        self.assertTrue(core['review_required'])
        self.assertTrue(any(r['state']=='review' and r['source_text']==body for r in core['records']))

    def test_new_community_prevents_silent_geographic_merge(self):
        target={'id':'target','reporting_period':'2026-10-20T18:30:00+03:00',
                'source_text':'У Дніпрі пошкоджені склади. Четверо поранені.'}
        body='У Дніпрі працюють служби. У Покровській громаді пошкоджені склади. Четверо поранені.'
        self.assertTrue(warehouse_supplement(body,[target],self.published)['conflict'])

    def test_local_conflict_does_not_consume_a_review_request(self):
        body='20 жовтня близько 08:00 ворог атакував Дніпро. Поранений чоловік.'
        post={'key':'adm_dp/9998','channel':'adm_dp','published_at':self.published.isoformat(),'text':body}
        core=compile_registry([post],{},NOW)
        with patch('core_review.request_text') as request:
            result=review_core(core,render_registry(core))
        request.assert_not_called()
        self.assertEqual(result['state'],'local_conflict')
        self.assertEqual(result['requests'],0)


if __name__=='__main__':
    unittest.main()
