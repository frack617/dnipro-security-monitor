import copy
import json
import os
import tempfile
import unittest
from contextlib import ExitStack, contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import collector as c
from fact_registry import compile_registry, render_registry
from report_contract import publication_issues, review_input_digest, reusable_review

F = json.loads((Path(__file__).parent/'fixtures/source_core_20261022.json').read_text())
NOW = datetime.fromisoformat(F['status']['checked_at'])


@contextmanager
def pipeline(review_result, sending=True):
    with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
        root = Path(directory)
        state_path = root/'alert_state.json'
        state_path.write_text(json.dumps({'last_daily_report':'2026-10-21','alerted_keys':['keep']}))
        for name,value in [('DATA_DIR',root),('MORNING_REPORT_FILE',root/'morning_report.md'),
                           ('ALERT_STATE_FILE',state_path)]:
            stack.enter_context(patch.object(c,name,value))
        stack.enter_context(patch.dict(os.environ,{'PRODUCTION_MONITOR':'true',
            'SEND_MORNING_REPORT':str(sending).lower(),'FORCE_MORNING_REPORT':'false'}))
        review = stack.enter_context(patch('core_review.review_core',side_effect=review_result))
        send = stack.enter_context(patch.object(c,'deliver_morning_report'))
        notice = stack.enter_context(patch.object(c,'send_bot_message',return_value=True))
        yield root,review,send,notice


class PublicationContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = compile_registry(F['posts'],F['status']['channels'],NOW)
        cls.text = render_registry(cls.registry)

    def test_saved_22_october_passes_complete_local_contract(self):
        self.assertEqual(publication_issues(self.registry,self.text,F['status']['channels'],c.load_channels()),[])

    def test_missing_channel_is_not_confused_with_all_sources_successful(self):
        statuses = copy.deepcopy(F['status']['channels'])
        statuses.pop('SBUkr')
        errors = publication_issues(self.registry,self.text,statuses,c.load_channels())
        self.assertIn('source_coverage:SBUkr',errors)

    def test_each_coverage_boundary_and_failure_is_checked(self):
        start = datetime.fromisoformat(self.registry['window']['start'])
        end = datetime.fromisoformat(self.registry['window']['end'])
        for field,value in [('ok',False),('coverage_complete',False),
                            ('coverage_from',(start+timedelta(seconds=1)).isoformat()),
                            ('coverage_until',(end-timedelta(seconds=1)).isoformat()),
                            ('coverage_until','broken')]:
            statuses = copy.deepcopy(F['status']['channels'])
            statuses['adm_dp'][field] = value
            self.assertIn('source_coverage:adm_dp',publication_issues(self.registry,self.text,statuses,c.load_channels()))

    def test_raw_appeal_and_unnamed_service_cannot_pass_as_publishable(self):
        for added,code in [('Шановні споживачі м. Дніпро','raw_address_to_readers'),
                           ('Анонсовано відключення 22 ЖОВТНЯ','unnamed_service')]:
            self.assertIn(code,publication_issues(self.registry,self.text+'\n'+added,{},()))

    def test_length_is_advisory_but_extra_public_category_is_blocked(self):
        self.assertNotIn('length',publication_issues(self.registry,self.text+' факт'*501,{},()))
        self.assertIn('public_format',publication_issues(self.registry,self.text+'\n2.4. Додаткове',{},()))

    def test_invalid_response_remains_in_audit_without_blocking_delivery(self):
        results = [{'state':'invalid_response','requests':1,'provider':'gemini','issues':[]},
                   {'state':'unavailable','requests':0,'provider':'gemini','issues':[]}]
        with pipeline(results) as (root,review,send,notice):
            for minutes in (0,30):
                c.process_morning_report(F['posts'],F['status']['channels'],NOW+timedelta(minutes=minutes))
            self.assertEqual(review.call_count,1)
            self.assertEqual(send.call_count,2)
            notice.assert_not_called()
            status = json.loads((root/'report_generation_status.json').read_text())
            self.assertEqual(status['review']['state'],'invalid_response')
            self.assertTrue(status['review']['reused'])
            self.assertEqual(status['review']['requests'],0)
            self.assertEqual(status['delivery_state'],'confirmed')
            state = json.loads((root/'alert_state.json').read_text())
            self.assertEqual(state['last_daily_report'],'2026-10-21')
            self.assertEqual(state['alerted_keys'],['keep'])
            self.assertNotIn('daily_report_block_notice',state)

    def test_valid_review_reused_for_identical_dry_run_without_second_request(self):
        with pipeline([{'state':'completed','requests':1,'provider':'gemini','issues':[]}],False) as (root,review,send,notice):
            for minutes in (0,30):
                c.process_morning_report(F['posts'],F['status']['channels'],NOW+timedelta(minutes=minutes))
            self.assertEqual(review.call_count,1)
            send.assert_not_called()
            notice.assert_not_called()

    def test_concern_is_preserved_across_unchanged_runs(self):
        issue = {'source_key':'dnipropetrovskaODA/32729','code':'number_scope'}
        with pipeline([{'state':'concerns','requests':1,'provider':'gemini','issues':[issue]}]) as (root,review,send,notice):
            for minutes in (0,30):
                c.process_morning_report(F['posts'],F['status']['channels'],NOW+timedelta(minutes=minutes))
            self.assertEqual(review.call_count,1)
            self.assertEqual(json.loads((root/'report_generation_status.json').read_text())['review']['issues'],[issue])
            self.assertEqual(send.call_count,2)

    def test_changed_source_gets_new_bounded_review(self):
        posts = copy.deepcopy(F['posts'])
        next(p for p in posts if p['key']=='dnipropetrovskaODA/32729')['text'] += '\nПошкоджено дах.'
        with pipeline([{'state':'invalid_response','requests':1,'provider':'gemini','issues':[]},
                       {'state':'completed','requests':1,'provider':'gemini','issues':[]}]) as (root,review,send,notice):
            c.process_morning_report(F['posts'],F['status']['channels'],NOW)
            c.process_morning_report(posts,F['status']['channels'],NOW+timedelta(minutes=30))
            self.assertEqual(review.call_count,2)
            self.assertEqual(send.call_count,2)
            self.assertIn('Пошкоджено дах.',send.call_args.args[0])

    def test_incomplete_source_delivers_flagged_draft_without_review_request(self):
        statuses = copy.deepcopy(F['status']['channels'])
        statuses.pop('SBUkr')
        with pipeline([]) as (root,review,send,notice):
            c.process_morning_report(F['posts'],statuses,NOW)
            review.assert_not_called()
            send.assert_called_once()
            notice.assert_not_called()
            status = json.loads((root/'report_generation_status.json').read_text())
            self.assertIn('source_coverage:SBUkr',status['publication_issues'])
            self.assertEqual(status['review']['requests'],0)
            self.assertFalse(status['coverage_complete'])

    def test_incomplete_source_needs_no_separate_delay_notification(self):
        statuses = copy.deepcopy(F['status']['channels'])
        statuses['adm_dp']['ok'] = False
        with pipeline([]) as (root,review,send,notice):
            notice.side_effect = RuntimeError('offline')
            c.process_morning_report(F['posts'],statuses,NOW)
            state = json.loads((root/'alert_state.json').read_text())
            self.assertNotIn('daily_report_block_notice',state)
            self.assertEqual(state['last_daily_report'],'2026-10-21')
            send.assert_called_once()
            notice.assert_not_called()

    def test_real_fixture_delivers_exact_saved_text_with_complete_sources(self):
        with pipeline([{'state':'completed','requests':1,'provider':'gemini','issues':[]}]) as (root,review,send,notice):
            c.process_morning_report(F['posts'],F['status']['channels'],NOW)
            self.assertEqual(send.call_count,1)
            self.assertEqual(send.call_args.args[0],(root/'morning_report.md').read_text().strip())
            self.assertEqual(json.loads((root/'report_generation_status.json').read_text())['delivery_state'],'confirmed')
            notice.assert_not_called()

    def test_audit_and_reviewer_setting_changes_invalidate_cached_decision(self):
        fingerprint = review_input_digest(self.registry,self.text)
        changed = copy.deepcopy(self.registry)
        changed['records'][0]['source_text'] += ' змінений контекст'
        self.assertNotEqual(fingerprint,review_input_digest(changed,self.text))
        with patch.dict(os.environ,{'REPORT_PROVIDER':'groq'}):
            self.assertNotEqual(fingerprint,review_input_digest(self.registry,self.text))
        previous = {'report_date':'2026-10-21','review_input_sha256':fingerprint,
                    'review':{'state':'completed','issues':[]}}
        self.assertIsNone(reusable_review(previous,fingerprint,'2026-10-22'))

    def test_incomplete_or_unavailable_decisions_are_not_positive_cached_reviews(self):
        for state in ('unavailable','local_contract','disabled'):
            prior={'report_date':'2026-10-22','review_input_sha256':'x','review':{'state':state,'issues':[]}}
            self.assertIsNone(reusable_review(prior,'x','2026-10-22'))


if __name__ == '__main__':
    unittest.main()
