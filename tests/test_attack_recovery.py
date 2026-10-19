import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from ai_report import generate_gemini_report, validate_report
from groq_report import generate_groq_report
from report_rules import report_section
from report_sections import recover_attack_section, recover_transport_section
from test_groq_report import json_sections

F=json.loads((Path(__file__).parent/'fixtures/attack_recovery_20261019.json').read_text())
ARGS=(F['posts'],'08:00 18.10.2026','08:00 19.10.2026','13:57 19.10.2026','19.10.2026',[])


class AttackRecoveryTests(unittest.TestCase):
    def test_both_real_drafts_recover_and_other_sections_stay_identical(self):
        for a in F['debug']['attempts']:
            raw=recover_transport_section(a['validated_text'],F['posts'])
            with self.subTest(attempt=a['attempt']):
                with self.assertRaisesRegex(ValueError,'unsupported community'):
                    validate_report(raw,'19.10.2026',posts=F['posts'])
                out=recover_attack_section(raw,F['posts'],'19.10.2026')
                validate_report(out,'19.10.2026',posts=F['posts'])
                for s in ('1.1','1.2','1.3','1.4','2.2','2.3','2.4'):
                    self.assertEqual(report_section(raw,s),report_section(out,s))
                body=report_section(out,'2.1')
                for fact in ('За зведенням 18 жовтня','08:00 19 жовтня','84-річна',
                             '21 ворожий БпЛА','Ще три оселі зруйновані','критичної інфраструктури'):
                    self.assertIn(fact,body)
                self.assertEqual(body.lower().count('понад 20 разів'),2)
                self.assertNotIn('сталася пожежа. Постраждала одна людина',body)

    def test_valid_report_is_not_rewritten(self):
        out=recover_attack_section(recover_transport_section(F['debug']['attempts'][1]['validated_text'],F['posts']),F['posts'],'19.10.2026')
        self.assertEqual(recover_attack_section(out,F['posts'],'19.10.2026'),out)

    def test_error_in_overview_cannot_be_hidden_by_rebuilding_events(self):
        raw=F['debug']['attempts'][1]['validated_text'].replace(
            'Протягом звітного періоду Дніпропетровщина зазнала численних атак',
            'Понад 99 разів ворог атакував Дніпропетровщину')
        self.assertEqual(recover_attack_section(raw,F['posts'],'19.10.2026'),raw)

    def test_invalid_structure_stays_rejected(self):
        raw=F['debug']['attempts'][1]['validated_text'].replace('2.2.','2.1.',1)
        self.assertEqual(recover_attack_section(raw,F['posts'],'19.10.2026'),raw)

    def test_no_sources_never_deletes_the_draft(self):
        raw=F['debug']['attempts'][1]['validated_text']
        self.assertEqual(recover_attack_section(raw,[],'19.10.2026'),raw)

    @patch.dict(os.environ,{'GITHUB_ACTIONS':'false','GROQ_API_KEY':'test-key'})
    @patch('groq_report.time.sleep')
    @patch('groq_report._request_groq',return_value='invalid JSON')
    def test_invalid_json_cannot_be_recovered_as_an_author_report(self,request,sleep):
        with self.assertRaisesRegex(RuntimeError,'Groq report failed source validation'):
            generate_groq_report(*ARGS)
        self.assertEqual(request.call_count,2)

    def test_other_section_validation_failure_stays_rejected(self):
        raw=F['debug']['attempts'][1]['validated_text'].replace('1.3.','1.5.',1)
        self.assertEqual(recover_attack_section(raw,F['posts'],'19.10.2026'),raw)

    @patch.dict(os.environ,{'GITHUB_ACTIONS':'false','GEMINI_API_KEY':'test-key'})
    @patch('ai_report._request_report')
    def test_exhausted_author_repairs_use_sources_without_third_request(self,request):
        request.side_effect=[a['text'] for a in F['debug']['attempts']]
        out=generate_gemini_report(*ARGS)
        validate_report(out,'19.10.2026',posts=F['posts'])
        self.assertEqual(request.call_count,2)

    @patch.dict(os.environ,{'GITHUB_ACTIONS':'false','GROQ_API_KEY':'test-key'})
    @patch('groq_report.time.sleep')
    @patch('groq_report._request_groq')
    def test_same_last_recovery_is_available_for_groq(self,request,sleep):
        request.side_effect=[json_sections(a['validated_text']) for a in F['debug']['attempts']]
        out=generate_groq_report(*ARGS)
        validate_report(out,'19.10.2026',posts=F['posts'])
        self.assertEqual(request.call_count,2)

    @patch.dict(os.environ,{'GITHUB_ACTIONS':'false','GEMINI_API_KEY':'test-key'})
    @patch('ai_report._request_report')
    def test_editor_repairs_recover_locally_after_bounded_calls(self,request):
        valid=recover_attack_section(recover_transport_section(F['debug']['attempts'][1]['validated_text'],F['posts']),F['posts'],'19.10.2026')
        request.side_effect=[valid,F['debug']['attempts'][0]['text'],F['debug']['attempts'][1]['text']]
        out=generate_gemini_report(*ARGS)
        validate_report(out,'19.10.2026',posts=F['posts'])
        self.assertEqual(request.call_count,3)
