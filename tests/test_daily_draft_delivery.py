import json
import os
import re
import tempfile
import unittest
from contextlib import ExitStack, contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import collector as c
from daily_draft import reserve_report

F = json.loads((Path(__file__).parent/'fixtures/source_core_20261026.json').read_text())
NOW = datetime.fromisoformat(F['status']['checked_at'])


@contextmanager
def live_pipeline():
    with tempfile.TemporaryDirectory() as folder, ExitStack() as stack:
        root = Path(folder)
        for key, value in [('DATA_DIR',root), ('MORNING_REPORT_FILE',root/'morning_report.md'),
                           ('ALERT_STATE_FILE',root/'alert_state.json')]:
            stack.enter_context(patch.object(c,key,value))
        stack.enter_context(patch.dict(os.environ,{'FORCE_MORNING_REPORT':'false',
            'SEND_MORNING_REPORT':'true','PRODUCTION_MONITOR':'true','REPORT_CORE_REVIEW':'false'}))
        send = stack.enter_context(patch.object(c,'send_bot_message',return_value=True))
        yield root, send


class DailyDraftDeliveryTests(unittest.TestCase):
    def test_real_blocked_day_delivers_once_and_preserves_unrelated_state(self):
        with live_pipeline() as (root,send):
            (root/'alert_state.json').write_text(json.dumps({'alerted_keys':['keep'], 'last_daily_report':'2026-10-25'}))
            c.process_morning_report(F['posts'],F['status']['channels'],NOW)
            calls = send.call_count
            self.assertGreater(calls,0)
            c.process_morning_report(F['posts'],F['status']['channels'],NOW+timedelta(minutes=30))
            self.assertEqual(send.call_count,calls)
            state=json.loads((root/'alert_state.json').read_text())
            receipt=json.loads((root/'report_delivery_status.json').read_text())
            self.assertEqual(state['alerted_keys'],['keep'])
            self.assertEqual(state['last_daily_report'],'2026-10-26')
            self.assertEqual(receipt['delivery_state'],'confirmed')

    def test_generation_exception_delivers_current_source_reserve(self):
        with live_pipeline() as (root,send), patch('fact_registry.compile_registry',side_effect=ValueError('private detail')):
            c.process_morning_report(F['posts'],F['status']['channels'],NOW)
            text=(root/'morning_report.md').read_text()
            self.assertIn('Резервна джерельна довідка',text)
            self.assertNotIn('private detail',text)
            self.assertIn('26.10.2026 08.00',text)
            self.assertEqual(re.findall(r'(?m)^([12]\.\d)\.',text),['1.1','1.2','2.1','2.2','2.3'])
            self.assertGreater(send.call_count,0)
            status=json.loads((root/'report_generation_status.json').read_text())
            self.assertFalse(status['coverage_complete'])
            self.assertEqual(status['report_kind_detail'],'source_reserve')

    def test_incomplete_sources_are_visible_and_do_not_suppress_report(self):
        with live_pipeline() as (root,send):
            c.process_morning_report(F['posts'],{},NOW)
            self.assertGreater(send.call_count,0)
            self.assertIn('не підтверджено повне читання',(root/'morning_report.md').read_text())
            self.assertFalse(json.loads((root/'report_generation_status.json').read_text())['coverage_complete'])

    def test_failed_telegram_retries_exact_saved_text_without_regeneration(self):
        with live_pipeline() as (root,send):
            send.return_value=False
            with self.assertRaises(RuntimeError):
                c.process_morning_report(F['posts'],F['status']['channels'],NOW)
            state=json.loads((root/'alert_state.json').read_text())
            text=state['pending_daily_report']['text']
            self.assertNotIn('last_daily_report',state)
            send.return_value=True
            with patch('fact_registry.compile_registry',side_effect=AssertionError('must not generate')):
                c.process_morning_report([],{},NOW+timedelta(minutes=30))
            self.assertEqual((root/'morning_report.md').read_text().strip(),text)
            self.assertEqual(json.loads((root/'report_generation_status.json').read_text())['delivery_state'],'confirmed')

    def test_reviewer_exception_is_an_advisory(self):
        with live_pipeline() as (root,send), patch('core_review.review_core',side_effect=RuntimeError('offline')):
            c.process_morning_report(F['posts'],F['status']['channels'],NOW)
            self.assertGreater(send.call_count,0)
            status=json.loads((root/'report_generation_status.json').read_text())
            self.assertEqual(status['review']['state'],'unavailable')
            self.assertTrue(status['review_required'])

    def test_no_posts_produces_honest_reserve_without_claiming_no_events(self):
        text=reserve_report([],NOW)
        self.assertIn('не означає відсутності подій',text)
        self.assertNotIn('подій не зареєстровано',text)

    def test_schedule_does_not_force_repeat_delivery(self):
        workflow=(Path(__file__).parents[1]/'.github/workflows/collect.yml').read_text()
        force=next(line for line in workflow.splitlines() if 'FORCE_MORNING_REPORT:' in line)
        self.assertNotIn("github.event_name == 'schedule'",force)
        self.assertIn('REPORT_CORE_REVIEW: "false"',workflow)

    def test_reserve_preserves_raw_text_and_excludes_old_and_future_publications(self):
        def post(key, date, text):
            return dict(key=key,channel='adm_dp',published_at=date,text=text,url='https://t.me/'+key)
        texts=[post('adm_dp/1','2026-10-25T10:00:00+02:00','У Дніпрі ворог атакував лікарню. Поранено 3 людей.'),
               post('adm_dp/2','2026-10-24T10:00:00+03:00','У Дніпрі ворог атакував старий об’єкт.'),
               post('adm_dp/3','2026-10-26T09:00:00+02:00','У Дніпрі ворог атакував майбутній об’єкт.')]
        text=reserve_report(texts,NOW)
        self.assertIn(texts[0]['text'],text)
        self.assertNotIn(texts[1]['text'],text)
        self.assertNotIn(texts[2]['text'],text)
        self.assertIn('це не встановлений час події',text)
