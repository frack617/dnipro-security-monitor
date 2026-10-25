import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from datetime import datetime
from unittest.mock import patch

import collector as c
from fact_registry import compile_registry,render_registry
from report_contract import publication_issues

F=json.loads((Path(__file__).parent/'fixtures/source_core_20261025.json').read_text())
NOW=datetime.fromisoformat(F['status']['checked_at'])


def long_posts():
    posts=copy.deepcopy(F['posts'])
    posts.append(dict(key='adm_dp/long-unique-facts',channel='adm_dp',published_at='2026-10-24T14:00:00+00:00',url='https://example.invalid/long',
        text='24 жовтня ворог атакував Дніпро. Пошкоджено лікарню. '+
             ' '.join(f'На території лікарні пошкоджено вимірювальний пристрій під інвентарним номером {n}.' for n in range(1,31))))
    return posts


class AdvisoryLengthTests(unittest.TestCase):
    def test_long_unique_supported_facts_are_preserved_and_can_be_delivered(self):
        posts=long_posts();r,t=compile_and_render(posts)
        self.assertGreater(len(t.split()),500)
        self.assertEqual(publication_issues(r,t,{}),[])
        self.assertIn('номером 30.',t)
        self.check_pipeline(posts,concern=False)

    def test_long_report_still_blocks_factual_concerns(self):
        self.check_pipeline(long_posts(),concern=True)

    def test_lost_fact_in_long_report_still_blocks_locally(self):
        r,t=compile_and_render(long_posts())
        self.assertIn('lost_source_claim',publication_issues(r,t.replace('На території лікарні пошкоджено вимірювальний пристрій під інвентарним номером 30.',''),{}))

    def check_pipeline(self,posts,concern):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            review={'state':'concerns' if concern else 'completed','requests':1,'provider':'gemini',
                    'issues':[{'source_key':'adm_dp/long-unique-facts','code':'number_scope'}] if concern else []}
            with patch.object(c,'DATA_DIR',root),patch.object(c,'MORNING_REPORT_FILE',root/'morning_report.md'), \
                 patch.object(c,'read_alert_state',return_value={'last_daily_report':'2026-10-24'}), \
                 patch.dict(os.environ,{'PRODUCTION_MONITOR':'true','SEND_MORNING_REPORT':'true','FORCE_MORNING_REPORT':'false'}), \
                 patch('core_review.review_core',return_value=review) as reviewer, \
                 patch.object(c,'deliver_morning_report') as send,patch.object(c,'send_bot_message'):
                if concern:
                    with self.assertRaises(RuntimeError):c.process_morning_report(posts,F['status']['channels'],NOW)
                    send.assert_not_called()
                else:
                    c.process_morning_report(posts,F['status']['channels'],NOW)
                    send.assert_called_once()
                    self.assertEqual(send.call_args.args[0],(root/'morning_report.md').read_text().strip())
                reviewer.assert_called_once()
                status=json.loads((root/'report_generation_status.json').read_text())
                self.assertGreater(status['report_words'],500)
                self.assertEqual(status['length_policy'],'advisory')
                self.assertIn('over_target_length',status['editorial_warnings'])
                self.assertEqual(status['publication_issues'],[])


def compile_and_render(posts):
    r=compile_registry(posts,F['status']['channels'],NOW)
    return r,render_registry(r)


if __name__=='__main__':unittest.main()
