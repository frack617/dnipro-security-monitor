import json
import os
import unittest
from pathlib import Path
from unittest.mock import Mock,patch

from ai_report import generate_gemini_report,validate_report
from groq_report import generate_groq_report
from report_sections import clean_transport_notice,recover_transport_section
from report_rules import report_section
from test_groq_report import json_sections
from test_source_accuracy import report,source

FIXTURE=json.loads((Path(__file__).parent/'fixtures'/'transport_20261019.json').read_text())
ARGS=(FIXTURE['posts'],'08:00 18.10.2026','08:00 19.10.2026',
      '08:49 19.10.2026','19.10.2026',[])


class TransportRecoveryTests(unittest.TestCase):
    def test_both_real_rejected_drafts_are_recovered_without_ai(self):
        for attempt in FIXTURE['debug']['attempts']:
            raw=attempt['validated_text']
            with self.subTest(attempt=attempt['attempt']):
                with self.assertRaisesRegex(ValueError,'unsupported causal link'):
                    validate_report(raw,'19.10.2026',posts=FIXTURE['posts'])
                recovered=recover_transport_section(raw,FIXTURE['posts'])
                validate_report(recovered,'19.10.2026',posts=FIXTURE['posts'])
                for section in ('1.1','1.3','1.4','2.1','2.2','2.3','2.4'):
                    self.assertEqual(report_section(raw,section),report_section(recovered,section))

    def test_current_notices_keep_full_route_and_remove_link_captions(self):
        raw=FIXTURE['debug']['attempts'][1]['validated_text']
        body=report_section(recover_transport_section(raw,FIXTURE['posts']),'1.2')
        for fact in ('№6К','№9К','№23','Королеви Єлизавети II','№6',
                     'ж/м Придніпровський','ж/м Сонячний','Центральний міст',
                     'Січеславська Набережна','пл. Соборна','№18','№134'):
            self.assertIn(fact,body)
        for fragment in ('Деталі','Розклад руху','на сайті','ℹ','Усі інші маршрути'):
            self.assertNotIn(fragment,body)
        self.assertIn('№9К. Кінцева',body)
        self.assertIn('Окремо:',body)
        self.assertNotIn('Через тимчасове перекриття',body)

    def test_valid_model_transport_is_left_unchanged(self):
        text=recover_transport_section(report('Атак немає.'),FIXTURE['posts'])
        self.assertEqual(recover_transport_section(text,FIXTURE['posts']),text)

    def test_explicit_cause_in_a_source_is_preserved(self):
        text='Через ремонт вулиці Нової автобус №51 курсує через Південний міст.'
        posts=[source(text,'1.2')]
        raw=report('Атак немає.').replace(
            '1.2. У перевірених джерелах повідомлень за звітний період не виявлено.', '1.2. '+text)
        self.assertEqual(recover_transport_section(raw,posts),raw)

    def test_recovery_works_with_other_routes_and_never_substitutes_todays_numbers(self):
        posts=[source('Через ремонт колії на Соборному мосту призупинено трамвай № 42.', '1.2'),
               source('Тролейбус №77 курсує через Південний міст, автобус №218 через площу Миру.', '1.2')]
        bad=report('Атак немає.').replace(
            '1.2. У перевірених джерелах повідомлень за звітний період не виявлено.',
            '1.2. Через ремонт колії на Соборному мосту тролейбус №77 та автобус №218 курсують через Південний міст.')
        body=report_section(recover_transport_section(bad,posts),'1.2')
        self.assertIn('№ 42',body);self.assertIn('площу Миру',body)
        self.assertNotIn('№9К',body)

    def test_other_factual_error_remains_rejected(self):
        raw=FIXTURE['debug']['attempts'][1]['validated_text'].replace('21 ворожий БпЛА','99 ворожий БпЛА')
        # Use a known checked error, not a count type the validator doesn't cover.
        raw=raw.replace('понад 20 разів','понад 99 разів',1)
        recovered=recover_transport_section(raw,FIXTURE['posts'])
        with self.assertRaisesRegex(ValueError,'unsupported attack total'):
            validate_report(recovered,'19.10.2026',posts=FIXTURE['posts'])

    @patch.dict(os.environ,{'GEMINI_BACKUP_API_KEY':'test-key','GITHUB_ACTIONS':'false'})
    @patch('ai_report._request_report')
    def test_author_and_editor_transport_recovered_without_extra_repair_request(self,request):
        drafts=[a['text'] for a in FIXTURE['debug']['attempts']]
        request.side_effect=drafts
        result=generate_gemini_report(*ARGS,backup=True)
        validate_report(result,'19.10.2026',posts=FIXTURE['posts'])
        self.assertEqual(request.call_count,2)
        self.assertIn('Окремо:',report_section(result,'1.2'))

    @patch.dict(os.environ,{'GROQ_API_KEY':'test-key','GITHUB_ACTIONS':'false'})
    @patch('groq_report._request_groq')
    def test_same_recovery_applies_to_groq(self,request):
        request.return_value=json_sections(FIXTURE['debug']['attempts'][1]['validated_text'])
        result=generate_groq_report(*ARGS)
        validate_report(result,'19.10.2026',posts=FIXTURE['posts'])
        self.assertEqual(request.call_count,1)


if __name__=='__main__':unittest.main()
