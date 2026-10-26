import copy
import json
import os
import re
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import collector as c
from fact_registry import compile_registry,render_registry,service_display
from operational_facts import current_attack_piece,queue_power_schedule,completed_chronological_day_recap
from report_contract import publication_issues
from event_brief import split_places

F=json.loads((Path(__file__).parent/'fixtures/source_core_20261026.json').read_text())
NOW=datetime.fromisoformat(F['status']['checked_at']);KYIV=ZoneInfo('Europe/Kyiv')


def render(posts=None):
    r=compile_registry(copy.deepcopy(F['posts'] if posts is None else posts),F['status']['channels'],NOW)
    return r,render_registry(r)


def post(key):return copy.deepcopy(next(p for p in F['posts'] if p['key']==key))


class Morning26Tests(unittest.TestCase):
    def test_real_blocked_case_passes_complete_contract_with_facts_retained(self):
        self.assertEqual(F['blocked_generation']['publication_issues'],['raw_address_to_readers','lost_source_claim'])
        r,t=render()
        self.assertEqual(publication_issues(r,t,F['status']['channels'],c.load_channels()),[])
        self.assertFalse(r['review_required'])
        self.assertFalse([x for x in r['claim_plan'] if x['disposition']=='unresolved'])
        for fact in ['30-річного чоловіка','середньої тяжкості','Миколаївській','Солонянській','Мозолевській','сільгосптехніка','пасажирський автобус','Понад 40','Понад 10']:
            self.assertIn(fact,t)
        for old in ['Шановні','11-річна','72-річна','58-річна','113 повідомлень','Нкопольщину']:
            self.assertNotIn(old,t)

    def test_operator_scope_every_queue_interval_and_midnight_are_retained(self):
        p=post('cek_info/4278');t=queue_power_schedule(p)
        self.assertIsNotNone(t)
        for q in ['1.1','1.2','2.1','2.2','4.1','4.2','5.1','5.2','6.1','6.2']:
            self.assertIn(q,t)
        for interval in ['21:30–00:30 наступної доби','11:00–14:30','14:30–18:00','07:00–11:00','18:00–21:30','07:00–24:00']:
            self.assertIn(interval,t)
        self.assertIn('для споживачів оператора',t);self.assertIn('26.10.2026',t)
        self.assertIn('може змінюватися',t)
        self.assertNotIn('Шановні',t);self.assertNotIn('всій області',t)
        r,report=render()
        for changed in [report.replace('21:30–00:00','21:30–00:30'),report.replace('1.1, 1.2','1.1')]:
            self.assertIn('lost_service_schedule',publication_issues(r,changed,{}))

    def test_later_complete_update_supersedes_initial_table_in_audit(self):
        r,t=render()
        old=next(x for x in r['records'] if x['source_key']=='cek_info/4278')
        new=next(x for x in r['records'] if x['source_key']=='cek_info/4280')
        self.assertEqual(old['state'],'superseded');self.assertIsNone(old['display'])
        self.assertEqual(old['superseded_by'],new['id'])
        self.assertIn('21:30-00:30',old['source_text'])
        self.assertIn('21:30–00:00',t);self.assertNotIn('21:30–00:30',t)
        self.assertEqual(t.count('заявлений період 07:00–24:00'),1)
        self.assertEqual(publication_issues(r,t,{}),[])

    def test_partial_or_different_date_update_does_not_erase_full_schedule(self):
        initial=post('cek_info/4278');updated=post('cek_info/4280')
        for change in ['partial','date']:
            candidate=copy.deepcopy(updated)
            if change=='partial':candidate['text']=candidate['text'].replace('Черга 6.2\n18:00-21:30','')
            else:candidate['text']=candidate['text'].replace('26 ЖОВТНЯ','27 ЖОВТНЯ')
            r,t=render([initial,candidate])
            old=next(x for x in r['records'] if x['source_key']=='cek_info/4278')
            self.assertNotEqual(old['state'],'superseded')
            self.assertIn('21:30–00:30',t)

    def test_unknown_extra_service_consequence_is_not_discarded(self):
        p=post('cek_info/4278');p['text']+=' Аварія пошкодила резервний кабель на вул. Центральній.'
        self.assertIsNone(queue_power_schedule(p))
        t=service_display(p,NOW.astimezone(KYIV))
        self.assertNotIn('Шановні',t)
        self.assertIn('електроенергії',t)
        self.assertIn('Аварія пошкодила резервний кабель на вул. Центральній.',t)
        self.assertIn('21:30-00:30',t)

    def test_previous_evening_to_morning_recap_is_outside_next_window(self):
        r,t=render()
        records=[x for x in r['records'] if x['source_key']=='dsns_telegram/78776']
        self.assertTrue(records)
        self.assertTrue(all(x['state']=='excluded' for x in records))
        self.assertEqual(records[0]['reason'],'completed_prior_night_recap')
        start,end,*_=c.completed_report_window(NOW)
        p=post('dsns_telegram/78776');published=datetime.fromisoformat(p['published_at']).astimezone(KYIV)
        for marker in ['Після 08:30 ворог знову атакував Дніпро. Пошкоджено лікарню.',
                       'Після 9-ї ворог знову атакував Дніпро. Пошкоджено лікарню.']:
            body,reason=current_attack_piece(p['text']+' '+marker,published.replace(hour=10),start,end)
            self.assertIsNotNone(body);self.assertIn('лікарню',body)
            self.assertNotIn('11-річна',body)

    def test_completed_police_chronology_is_not_redated_to_publication(self):
        r,t=render();records=[x for x in r['records'] if x['source_key']=='gunpvdp/37438']
        self.assertTrue(all(x['state']=='excluded' for x in records))
        self.assertEqual(records[0]['reason'],'completed_chronological_previous_day_recap')
        p=post('gunpvdp/37438');published=datetime.fromisoformat(p['published_at']).astimezone(KYIV)
        start,*_=c.completed_report_window(NOW)
        from fallback_report import clean_lines
        # Use the prepared single copy of the source, not Telegram's repeated HTML body.
        raw=records[0]['source_text']
        self.assertTrue(completed_chronological_day_recap(clean_lines(raw),published,start))
        self.assertFalse(completed_chronological_day_recap(clean_lines(raw)+' Сьогодні після 08:30 ворог атакував Дніпро.',published,start))
        self.assertFalse(completed_chronological_day_recap(clean_lines(raw).replace('Близько 23-ї','Близько 11-ї'),published,start))
        self.assertFalse(completed_chronological_day_recap(clean_lines(raw),published.replace(hour=23,minute=30),start))
        self.assertFalse(completed_chronological_day_recap(clean_lines(raw).replace('За кілька годин російські війська повторно вдарили','Російські війська вдарили'),published,start))

    def test_current_regional_fire_fact_is_not_assigned_to_last_named_city(self):
        p=post('dsns_telegram/78776');p['key']='dsns_telegram/current'
        p['published_at']='2026-10-26T05:45:00+00:00'
        r,t=render([p])
        fire='Рятувальники ДСНС ліквідували всі пожежі, спричинені ворожими ударами.'
        self.assertIn(fire,t)
        self.assertEqual(publication_issues(r,t,{}),[])
        claim=next(c for c in r['claim_plan'] if c['source_text']==fire)
        self.assertIsNone(claim['place']);self.assertEqual(claim['disposition'],'rendered')
        self.assertIn('lost_source_claim',publication_issues(r,t.replace(fire,''),{}))
        chunks=split_places('У Дніпрі сталася пожежа. Рятувальники ліквідували всі пожежі.')
        self.assertEqual(len(chunks),1);self.assertEqual(chunks[0][0],'Дніпро')

    def test_scope_is_inherited_only_from_single_explicit_bulletin_place(self):
        r,t=render()
        target=next(x for x in r['records'] if x['source_key']=='dnipropetrovskaODA/32834' and x['source_text'].startswith('Цілив'))
        self.assertEqual(target['scope_context'],'Нікопольщина')
        n=re.search(r'(?m)^Нікопольщина:\n([^\n]+)',t)[1]
        self.assertIn('Понівечені багатоповерхівка та адмінбудівля',n)
        self.assertIn('Нкопольщину',next(x for x in r['records'] if x['source_key']=='dnipropetrovskaODA/32834' and x['scope']=='Дніпропетровська область')['source_text'])
        self.assertTrue(r['public_projection']['name_normalizations'])
        self.assertNotIn('Нкопольщину',t)
        ambiguous=post('dnipropetrovskaODA/32834')
        ambiguous['text']=ambiguous['text'].replace('Нкопольщину','Нікопольщину та Дніпровський район')
        other,_=render([ambiguous])
        generic=next(x for x in other['records'] if x['source_text'].startswith('Цілив'))
        self.assertNotIn('scope_context',generic)

    def test_blocked_day_can_reach_delivery_without_force_or_real_calls(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            (root/'report_generation_status.json').write_text(json.dumps(F['blocked_generation']))
            with patch.object(c,'DATA_DIR',root),patch.object(c,'MORNING_REPORT_FILE',root/'morning_report.md'), \
                 patch.object(c,'read_alert_state',return_value={'last_daily_report':'2026-10-25','daily_report_block_notice':'2026-10-26'}) as state, \
                 patch.dict(os.environ,{'PRODUCTION_MONITOR':'true','SEND_MORNING_REPORT':'true','FORCE_MORNING_REPORT':'false'}), \
                 patch('core_review.review_core',return_value={'state':'completed','requests':1,'provider':'gemini','issues':[]}) as reviewer, \
                 patch.object(c,'deliver_morning_report') as send,patch.object(c,'send_bot_message') as notice:
                c.process_morning_report(F['posts'],F['status']['channels'],NOW)
                reviewer.assert_called_once();send.assert_called_once();notice.assert_not_called()
                self.assertEqual(send.call_args.args[0],(root/'morning_report.md').read_text().strip())
                status=json.loads((root/'report_generation_status.json').read_text())
                self.assertEqual(status['delivery_state'],'confirmed');self.assertEqual(status['publication_issues'],[])
                state.return_value={'last_daily_report':'2026-10-26'}
                c.process_morning_report(F['posts'],F['status']['channels'],NOW)
                send.assert_called_once();reviewer.assert_called_once()


if __name__=='__main__':unittest.main()
