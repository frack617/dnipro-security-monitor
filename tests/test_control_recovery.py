import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

import collector
from ai_report import build_prompt, build_review_prompt, generate_gemini_report, validate_report
from groq_report import correction_prompt, completion_capacity, compact_evidence, _request_groq
from quota_budget import UsageLedger
from report_rules import required_fact_checklist,source_problems
from test_ai_report import VALID_REPORT
from test_groq_report import ARGS
from test_source_accuracy import source


FIXTURE=json.loads((Path(__file__).parent/'fixtures'/'control_20261019.json').read_text())
ENV={'GITHUB_ACTIONS':'true','GITHUB_EVENT_NAME':'workflow_dispatch',
     'USE_MORNING_RESERVE':'true','FORCE_MORNING_REPORT':'true',
     'SEND_MORNING_REPORT':'false','REPORT_PROVIDER':'gemini_backup'}


class ControlRecoveryTests(unittest.TestCase):
    def test_actual_gemini_rejection_is_still_rejected(self):
        draft=FIXTURE['gemini']['attempts'][0]['validated_text']
        with self.assertRaisesRegex(ValueError,'missing specific attack consequence: critical infrastructure'):
            validate_report(draft,'19.10.2026',posts=FIXTURE['posts'])

    def test_initial_and_editor_prompt_require_the_missing_object_explicitly(self):
        inventory=required_fact_checklist(FIXTURE['posts'])
        self.assertIn('критичної інфраструктури у Дніпрі',inventory)
        self.assertIn('чотири райони',inventory)
        self.assertIn('три райони',inventory)
        self.assertIn('18 жовтня',inventory)
        self.assertIn('19 жовтня',inventory)
        prompt=build_prompt(FIXTURE['posts'],'08:00 18.10.2026','08:00 19.10.2026','08:35 19.10.2026',[])
        self.assertLess(prompt.index(inventory),prompt.index('ВХІДНІ ДАНІ:'))
        self.assertIn(inventory,build_review_prompt('draft',FIXTURE['posts'],'start','end'))

    def test_actual_groq_repair_fits_without_removing_any_evidence(self):
        attempt=FIXTURE['groq']['attempts'][0]
        try:
            validate_report(attempt['rendered_text'],'19.10.2026',posts=FIXTURE['posts'])
        except ValueError as current_error:
            rejection=current_error
        prompt=correction_prompt(FIXTURE['posts'],'08:00 18.10.2026','08:00 19.10.2026',[],
                                  attempt['raw_text'],rejection)
        self.assertGreaterEqual(completion_capacity(prompt),2200)
        self.assertIn('critical-infrastructure strike',prompt)
        self.assertIn('BOTH equal-count bulletins',prompt)
        evidence=json.loads(prompt.split('EVIDENCE:\n',1)[1])
        self.assertEqual(evidence,compact_evidence(FIXTURE['posts']))

    def test_real_groq_additional_person_is_detected_even_after_fixing_other_omissions(self):
        draft=FIXTURE['groq']['attempts'][0]['rendered_text']
        with self.assertRaisesRegex(ValueError,'additional casualties need a distinct dated source episode'):
            validate_report(draft,'19.10.2026',posts=FIXTURE['posts'])

    def test_another_city_casualty_does_not_make_new_city_update_a_duplicate(self):
        from test_source_accuracy import report
        posts=[source('У Дніпрі пошкоджено будинок.'),
               source('На Нікопольщині одна людина поранена.'),
               source('У Дніпрі одна людина поранена.')]
        text=report('У Дніпрі пошкоджено будинок. На Нікопольщині одна людина поранена. У Дніпрі також одна людина поранена.')
        self.assertFalse(any('additional casualties' in e for e in source_problems(text,posts)))

    @patch('groq_report.requests.post')
    def test_oversize_preflight_never_reserves_a_request(self,post):
        ledger=Mock()
        with self.assertRaisesRegex(RuntimeError,'facts were not truncated'):
            _request_groq('x'*30000,'key','model',ledger)
        ledger.reserve.assert_not_called();post.assert_not_called()

    @patch.dict(os.environ,{'GITHUB_ACTIONS':'false','GEMINI_API_KEY':'test-key'})
    @patch('ai_report._request_report')
    def test_quota_failure_preserves_the_real_validation_reason(self,request):
        request.side_effect=[FIXTURE['gemini']['attempts'][0]['text'],RuntimeError('Local budget blocked')]
        with self.assertRaisesRegex(RuntimeError,'critical infrastructure; repair unavailable: Local budget blocked'):
            generate_gemini_report(FIXTURE['posts'],'08:00 18.10.2026','08:00 19.10.2026',
                                    '08:35 19.10.2026','19.10.2026',[])

    @patch.dict(os.environ,ENV)
    def test_reserve_mode_only_applies_to_explicit_backup_dry_check(self):
        self.assertEqual(UsageLedger.from_environment('gemini_backup:model').event,'manual_reserve_check')
        self.assertNotEqual(UsageLedger.from_environment('gemini-2.5-flash-lite').event,'manual_reserve_check')
        for changes in ({'SEND_MORNING_REPORT':'true'}, {'USE_MORNING_RESERVE':'false'},
                        {'REPORT_PROVIDER':'auto'}, {'FORCE_MORNING_REPORT':'false'},
                        {'GITHUB_EVENT_NAME':'schedule'}):
            with self.subTest(changes=changes),patch.dict(os.environ,changes):
                self.assertNotEqual(UsageLedger.from_environment('gemini_backup:model').event,'manual_reserve_check')

    def test_only_two_reserved_attempts_allowed_across_repeated_checks(self):
        now=datetime(2026,10,19,6,tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'usage.json'
            path.write_text(json.dumps({'events':[{'at':(now-timedelta(hours=1)).isoformat(),
                'model':'gemini_backup:model','event':'workflow_dispatch'} for _ in range(8)],'blocked_until':{}}))
            ledger=UsageLedger('gemini_backup:model',path=path,event='manual_reserve_check',now=lambda:now)
            ledger.reserve('author');ledger.reserve('author')
            with self.assertRaisesRegex(RuntimeError,'2 attempts'):
                ledger.reserve('editor')
            self.assertEqual(len(json.loads(path.read_text())['events']),10)

    @patch.dict(os.environ,{'GEMINI_BACKUP_API_KEY':'test-key','GITHUB_ACTIONS':'false'})
    @patch('ai_report._request_report')
    @patch('ai_report.UsageLedger.from_environment')
    def test_control_check_budget_has_two_requests_max_and_keeps_valid_draft(self,from_env,request):
        from_env.return_value=Mock(event='manual_reserve_check')
        request.side_effect=[VALID_REPORT,RuntimeError('budget exhausted')]
        result=generate_gemini_report([], *ARGS[1:],backup=True)
        self.assertEqual(result,VALID_REPORT.strip())
        self.assertEqual(request.call_args_list[0].args[3].limit,2)

    @patch.dict(os.environ,{'GEMINI_BACKUP_API_KEY':'test-key','GITHUB_ACTIONS':'false'})
    @patch('ai_report.UsageLedger.from_environment')
    @patch('gemini_transport.requests.post')
    def test_full_transport_repair_flow_stops_after_two_real_mock_http_calls(self,post,from_env):
        now=datetime(2026,10,19,6,tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as folder:
            ledger=UsageLedger('gemini_backup:model',path=Path(folder)/'usage.json',
                               event='manual_reserve_check',now=lambda:now)
            from_env.return_value=ledger
            corrected=json.loads((Path(__file__).parent/'fixtures'/'morning_20261019.json').read_text())['corrected_report']
            texts=[FIXTURE['gemini']['attempts'][0]['text'],corrected]
            responses=[]
            for text in texts:
                response=Mock(status_code=200)
                response.json.return_value={'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':text}]}}]}
                responses.append(response)
            post.side_effect=responses
            result=generate_gemini_report(FIXTURE['posts'],'08:00 18.10.2026','08:00 19.10.2026',
                                            '08:35 19.10.2026','19.10.2026',[],backup=True)
            self.assertIn('критичної інфраструктури',result)
            self.assertEqual(post.call_count,2)
            self.assertEqual(len(json.loads(ledger.path.read_text())['events']),2)

    def test_fallback_keeps_final_casualties_and_all_posts(self):
        long={'text':'Пошкоджено будинок. '*40+'Госпіталізована 84-річна жінка. #hashtag https://t.me/example/1'}
        text=collector.section_text([long]+[{'text':f'Повідомлення {i}.'} for i in range(8)])
        self.assertIn('84-річна жінка',text)
        self.assertIn('Повідомлення 0.',text)
        self.assertNotIn('#hashtag',text);self.assertNotIn('https://',text);self.assertNotIn('…',text)

    def test_weather_fallback_does_not_invent_accident_advice(self):
        note=collector.practical_note('1.4',[{'text':'Прогнозується гроза, жовтий рівень небезпечності.'}])
        self.assertNotIn('аварії',note);self.assertNotIn('пожежі',note)


if __name__=='__main__':unittest.main()
