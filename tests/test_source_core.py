import copy
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import collector as c
from core_review import review_core, validate_review
from fact_registry import (compile_registry, render_registry, validate_core_text,
                           make_record, merge_mirrors, transport_display)

FIXTURE = Path(__file__).parent/'fixtures'/'source_core_20261020.json'


class FrozenDayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.f = json.loads(FIXTURE.read_text())
        cls.now = datetime.fromisoformat(cls.f['status']['checked_at'])
        cls.core = compile_registry(cls.f['posts'], cls.f['status']['channels'], cls.now)
        cls.text = render_registry(cls.core)

    def test_all_collected_posts_not_only_prepared_subset(self):
        self.assertGreater(len(self.f['posts']), 79)
        self.assertGreater(len(self.core['records']), 20)

    def test_correct_whole_core_is_accepted(self):
        self.assertEqual(validate_core_text(self.text, self.core), self.text)
        self.assertFalse(self.core['review_required'])
        self.assertLessEqual(len(self.text.split()), 500)
        self.assertGreater(len(self.text.split()), 250)

    def test_original_community_survives_shortened_mirror_once_per_period(self):
        part = self.text.split('Обласне зведення на 07:30 20.10.2026:')[1]
        self.assertIn('Червоногригорівська', part)
        self.assertEqual(part.count('На Нікопольщині'), 1)
        shared = [r for r in self.core['records'] if r['state'] == 'included' and
                  'dnipropetrovskaODA/32696' in r['source_refs'] and
                  'adm_dp/45017' in r['source_refs']]
        self.assertEqual(len(shared), 5)

    def test_no_national_meeting_old_casualty_or_route_numbers(self):
        for unwanted in ('Lockheed', 'Patriot', '84-річ', '47-річ', '№', '21:46', 'збільшено кількість'):
            self.assertNotIn(unwanted, self.text)

    def test_uncertain_morning_time_stays_in_audit(self):
        for key in ('borys_filatovv/3717','DniproCityOfficial/14967','gunpvdp/37221'):
            record = next(r for r in self.core['records'] if r['source_key'] == key)
            self.assertEqual(record['state'], 'review')
            self.assertIsNone(record['incident_time'])
            self.assertTrue(record['possible_prior_sources'])

    def test_new_morning_under_its_bulletin_and_region_count_not_city(self):
        day, night = self.text.split('Обласне зведення на 07:30 20.10.2026:')
        self.assertIn('Десятеро дістали поранень', day)
        kr = day.split('У Кривому Розі')[1].split('На Нікопольщині')[0]
        self.assertNotIn('Десятеро', kr)
        self.assertIn('Є поранені, зокрема дитина.', kr)
        self.assertIn('пошкоджені приватні будинки', night)
        self.assertIn('Повідомлення від 06:06 20.10: На світанку', day)

    def test_planned_power_not_reported_as_completed(self):
        self.assertIn('Анонсовано відключення 20 ЖОВТНЯ з 08:00 до 18:00', self.text)
        self.assertIn('ВІЛЬНОГІРСЬК', self.text)
        self.assertIn('павербанки', self.text)
        self.assertNotIn('планували відновити', self.text)

    def test_old_false_accepted_counterexample_now_rejected(self):
        with self.assertRaisesRegex(ValueError,'protected factual core'):
            validate_core_text(self.f['legacy_false_accept'], self.core)

    def test_any_model_prose_change_rejected_including_omissions(self):
        mutations = [self.text.replace('Червоногригорівська і ', ''),
            self.text.replace('Є поранені, зокрема дитина.', 'Десятеро поранених.'),
            self.text.replace('Анонсовано відключення', 'Проведено відключення'),
            self.text.replace('07:30 20.10.2026', '07:30 19.10.2026'),
            self.text+'\nГарантовано безпечно.']
        for text in mutations:
            with self.subTest(text=text[-100:]), self.assertRaises(ValueError):
                validate_core_text(text, self.core)

    def test_no_source_is_claimed_independent_confirmation(self):
        self.assertNotIn('незалежно підтвердж', self.text)
        self.assertTrue(self.core['coverage_unproven'])

    def test_public_has_only_approved_five_points(self):
        import re
        self.assertEqual(re.findall(r'(?m)^([12]\.[1-4])\.', self.text), ['1.1','1.2','2.1','2.2','2.3'])


class ScopeTests(unittest.TestCase):
    def post(self, text, key='adm_dp/1', at='2026-10-19T15:30:00+00:00'):
        return dict(key=key, channel=key.split('/')[0], post_id=int(key.split('/')[1]),
                    text=text, published_at=at, url='https://t.me/'+key)

    def test_conflicting_same_bulletin_does_not_choose_last(self):
        a=self.post('Дніпропетровщина\n19 жовтня\n18:30\nТроє людей поранені. Ворог атакував область.\n▪️У Дніпрі пошкоджені будинки.\n▪️На Нікопольщині пошкоджені будинки.')
        b=self.post(a['text'].replace('Троє','Четверо'), 'dnipropetrovskaODA/2')
        core=compile_registry([a,b],{},datetime.fromisoformat('2026-10-20T06:00:00+00:00'))
        self.assertTrue(core['review_required'])
        self.assertIn('Троє',render_registry(core))
        self.assertIn('Четверо',render_registry(core))

    def test_same_date_different_bulletins_survive(self):
        a=self.post('Дніпропетровщина\n19 жовтня\n10:30\nТроє людей поранені. Ворог атакував область.\n▪️У Дніпрі пошкоджені будинки.\n▪️На Нікопольщині пошкоджені будинки.')
        b=self.post(a['text'].replace('10:30','18:30'), 'adm_dp/2')
        core=compile_registry([a,b],{},datetime.fromisoformat('2026-10-20T06:00:00+00:00'))
        self.assertIn('10:30',render_registry(core));self.assertIn('18:30',render_registry(core))

    def test_mixed_national_regions_not_copied(self):
        post=self.post('ДСНС: ліквідація наслідків.\n▪️У Дніпрі після атаки пошкоджені будинки.\n▪️У Харкові після атаки пошкоджені будинки.', 'dsns_telegram/1')
        core=compile_registry([post],{},datetime.fromisoformat('2026-10-20T06:00:00+00:00'))
        self.assertIn('Дніпрі',render_registry(core));self.assertNotIn('Харкові',render_registry(core))
        self.assertTrue(any(r['reason']=='outside_or_uncertain_region_block' for r in core['records']))

    def test_district_not_renamed_city(self):
        post=self.post('У Дніпровському районі виявили бойову частину безпілотника.')
        core=compile_registry([post],{},datetime.fromisoformat('2026-10-20T06:00:00+00:00'))
        self.assertIn('Дніпровському районі',render_registry(core))
        self.assertNotIn('У Дніпрі',render_registry(core))

    def test_post_cutoff_event_not_included(self):
        post=self.post('Ворог завдав удару по Дніпру. Загинула людина.', at='2026-10-20T05:10:00+00:00')
        core=compile_registry([post],{},datetime.fromisoformat('2026-10-20T06:00:00+00:00'))
        self.assertNotIn('Загинула людина',render_registry(core))

    def test_unrelated_new_consequence_not_lost_behind_bulletin(self):
        f=json.loads(FIXTURE.read_text())
        extra=self.post('Ворог атакував Нікополь. Пошкоджено церкву.', 'adm_dp/9999', '2026-10-19T17:00:00+00:00')
        core=compile_registry(f['posts']+[extra],{},datetime.fromisoformat(f['status']['checked_at']))
        self.assertIn('церкву',render_registry(core))


class ReviewerTests(unittest.TestCase):
    def setUp(self):
        f=json.loads(FIXTURE.read_text())
        self.core=compile_registry(f['posts'],f['status']['channels'],datetime.fromisoformat(f['status']['checked_at']))
        self.text=render_registry(self.core)

    def test_model_cannot_return_replacement_report(self):
        for payload in (self.text, '{"issues":[],"report":"fake"}', '{"issues":[{"source_key":"fake/1","code":"time"}]}'):
            with self.subTest(payload=payload[:40]),self.assertRaises(ValueError):
                validate_review(payload,self.core)

    @patch.dict(os.environ,{'REPORT_CORE_REVIEW':'true','REPORT_PROVIDER':'gemini_backup','GEMINI_API_KEY':'primary','GEMINI_BACKUP_API_KEY':'backup'})
    def test_one_review_request_only_no_repair_or_author(self):
        with patch('core_review.request_text',return_value='{"issues":[]}') as call:
            result=review_core(self.core,self.text)
        self.assertEqual(call.call_count,1)
        self.assertEqual(result['state'],'completed')
        self.assertFalse(call.call_args.kwargs['allow_rate_retry'])
        self.assertEqual(call.call_args.args[3].limit,1)

    @patch.dict(os.environ,{'REPORT_CORE_REVIEW':'true','REPORT_PROVIDER':'gemini','GEMINI_API_KEY':'primary'})
    def test_failure_keeps_exact_same_core_no_cascade(self):
        with patch('core_review.request_text',side_effect=RuntimeError('429')) as call:
            result=review_core(self.core,self.text)
        self.assertEqual(call.call_count,1)
        self.assertEqual(result['state'],'unavailable')
        self.assertEqual(render_registry(self.core),self.text)

    @patch.dict(os.environ,{'REPORT_CORE_REVIEW':'true','REPORT_PROVIDER':'auto','GEMINI_API_KEY':'','GEMINI_BACKUP_API_KEY':'','GROQ_API_KEY':''})
    def test_no_credentials_no_call(self):
        with patch('core_review.request_text') as call:
            result=review_core(self.core,self.text)
        call.assert_not_called();self.assertEqual(result['requests'],0)


class CollectionEvidenceTests(unittest.TestCase):
    def test_empty_html_is_not_successful_boundary(self):
        with patch.object(c,'fetch',return_value='<html></html>'):
            result=c.collect_channel('adm_dp',None,datetime(2026,10,19,tzinfo=timezone.utc))
        self.assertFalse(result.coverage['boundary_reached'])
        self.assertEqual(result.coverage['stop_reason'],'empty_or_unparseable_page')

    def test_repeated_page_and_page_limit_not_complete(self):
        post={'key':'adm_dp/1','post_id':1,'published_at':'2026-10-20T04:00:00+00:00'}
        for limit,reason in ((1,'page_limit'),(3,'repeated_page')):
            with patch.object(c,'MAX_PAGES',limit),patch.object(c,'fetch',return_value='x'),patch.object(c,'parse_page',return_value=[post]),patch.object(c.time,'sleep'):
                result=c.collect_channel('adm_dp',None,datetime(2026,10,19,tzinfo=timezone.utc))
            self.assertFalse(result.coverage['boundary_reached'])
            self.assertEqual(result.coverage['stop_reason'],reason)

    def test_reached_boundary_has_evidence(self):
        post={'key':'adm_dp/1','post_id':1,'published_at':'2026-10-18T04:00:00+00:00'}
        with patch.object(c,'fetch',return_value='x'),patch.object(c,'parse_page',return_value=[post]):
            result=c.collect_channel('adm_dp',None,datetime(2026,10,19,tzinfo=timezone.utc))
        self.assertTrue(result.coverage['boundary_reached'])
        self.assertEqual(result.coverage['pages_read'],1)

    def test_unproven_legacy_status_forces_full_backfill(self):
        now=datetime(2026,10,20,6,tzinfo=timezone.utc)
        recent={'key':'adm_dp/1','channel':'adm_dp','post_id':1,'text':'x','published_at':now.isoformat()}
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'status.json';path.write_text(json.dumps({'checked_at':now.isoformat(),'channels':{'adm_dp':{'parser_version':c.PARSER_VERSION}}}))
            with patch.object(c,'STATUS_FILE',path),patch.object(c,'utc_now',return_value=now),patch.object(c,'load_channels',return_value=['adm_dp']),patch.object(c,'read_existing',return_value=[recent]),patch.object(c,'collect_channel',return_value=[recent]) as collect,patch.object(c,'write_outputs'),patch.object(c,'process_alerts',return_value=[]),patch.object(c,'process_morning_report'):
                c.main()
        self.assertEqual(collect.call_args.args[2],now-timedelta(hours=c.LOOKBACK_HOURS))

    def test_status_range_after_retention(self):
        now=datetime(2026,10,20,6,tzinfo=timezone.utc)
        old={'key':'adm_dp/1','channel':'adm_dp','post_id':1,'text':'x','published_at':(now-timedelta(hours=100)).isoformat()}
        recent=dict(old,key='adm_dp/2',post_id=2,published_at=now.isoformat())
        with tempfile.TemporaryDirectory() as d,patch.object(c,'STATUS_FILE',Path(d)/'missing'),patch.object(c,'utc_now',return_value=now),patch.object(c,'load_channels',return_value=['adm_dp']),patch.object(c,'read_existing',return_value=[old,recent]),patch.object(c,'collect_channel',return_value=[recent]),patch.object(c,'write_outputs') as output,patch.object(c,'process_alerts',return_value=[]),patch.object(c,'process_morning_report'):
            c.main()
        saved,status=output.call_args.args[:2]
        self.assertEqual(len(saved),1)
        self.assertEqual(status['adm_dp']['oldest_collected_at'],recent['published_at'])


class IntegrationTests(unittest.TestCase):
    def test_same_saved_and_delivered_core_with_run_hash(self):
        f=json.loads(FIXTURE.read_text());now=datetime.fromisoformat(f['status']['checked_at'])
        with tempfile.TemporaryDirectory() as d,patch.object(c,'DATA_DIR',Path(d)),patch.object(c,'MORNING_REPORT_FILE',Path(d)/'morning_report.md'),patch.object(c,'read_alert_state',return_value={}),patch.dict(os.environ,{'SEND_MORNING_REPORT':'true','GITHUB_RUN_ID':'core-test'}),patch('core_review.review_core',return_value={'state':'unavailable','requests':1,'provider':'gemini','issues':[]}),patch.object(c,'deliver_morning_report') as send:
            c.process_morning_report(f['posts'],f['status']['channels'],now)
            text=Path(d,'morning_report.md').read_text().strip()
            self.assertEqual(send.call_args.args[0],text)
            status=json.loads(Path(d,'report_generation_status.json').read_text())
            registry=json.loads(Path(d,'report_fact_registry.json').read_text())
            self.assertEqual(status['report_sha256'],registry['report_sha256'])
            self.assertEqual(status['delivery_state'],'confirmed')
            self.assertEqual(status['run_id'],'core-test')

    def test_dry_run_never_sends_or_updates_delivery_state(self):
        f=json.loads(FIXTURE.read_text());now=datetime.fromisoformat(f['status']['checked_at'])
        with tempfile.TemporaryDirectory() as d,patch.object(c,'DATA_DIR',Path(d)),patch.object(c,'MORNING_REPORT_FILE',Path(d)/'morning_report.md'),patch.object(c,'read_alert_state',return_value={}),patch.dict(os.environ,{'SEND_MORNING_REPORT':'false','REPORT_CORE_REVIEW':'false'}),patch.object(c,'deliver_morning_report') as send:
            c.process_morning_report(f['posts'],f['status']['channels'],now)
            send.assert_not_called()

    def test_review_concern_blocks_automatic_send_but_saves_preview(self):
        f=json.loads(FIXTURE.read_text());now=datetime.fromisoformat(f['status']['checked_at'])
        with tempfile.TemporaryDirectory() as d,patch.object(c,'DATA_DIR',Path(d)),patch.object(c,'MORNING_REPORT_FILE',Path(d)/'morning_report.md'),patch.object(c,'read_alert_state',return_value={}),patch.dict(os.environ,{'SEND_MORNING_REPORT':'true'}),patch('core_review.review_core',return_value={'state':'concerns','requests':1,'provider':'gemini','issues':[{'source_key':'dnipropetrovskaODA/32693','code':'number_scope'}]}),patch.object(c,'deliver_morning_report') as send:
            with self.assertRaisesRegex(RuntimeError,'requires manual review'):
                c.process_morning_report(f['posts'],f['status']['channels'],now)
            send.assert_not_called()
            self.assertTrue(Path(d,'morning_report.md').exists())
            self.assertEqual(json.loads(Path(d,'report_generation_status.json').read_text())['delivery_state'],'blocked_review')



class PriorDatasetReplayTests(unittest.TestCase):
    def test_all_frozen_fixture_datasets_preserve_source_keys_and_cutoff(self):
        folder=Path(__file__).parent/'fixtures'
        tested=0
        for path in sorted(folder.glob('*.json')):
            if path.name=='source_core_20261020.json':
                continue
            data=json.loads(path.read_text())
            posts=data.get('posts',[]) if isinstance(data,dict) else data
            if not posts or not all(isinstance(p,dict) and p.get('published_at') and p.get('key') for p in posts):
                continue
            day=datetime.strptime(path.stem[-8:],'%Y%m%d').replace(hour=9,tzinfo=c.KYIV)
            core=compile_registry(posts,{},day)
            with self.subTest(dataset=path.name):
                text=render_registry(core)
                self.assertEqual(validate_core_text(text,core),text)
                self.assertTrue(all(r['source_key'] in {p['key'] for p in posts} for r in core['records']))
                self.assertEqual(core['window']['end'],day.replace(hour=8).isoformat())
            tested+=1
        self.assertGreaterEqual(tested,10)

    def test_negation_is_conflict_not_fuller_mirror(self):
        p={'key':'adm_dp/1','published_at':'2026-10-19T15:00:00+00:00'}
        a=make_record(p,'2.1','У Дніпрі пошкоджені будинки.',scope='Дніпро',period='p')
        b=make_record(dict(p,key='adm_dp/2'),'2.1','У Дніпрі не пошкоджені будинки.',scope='Дніпро',period='p')
        diagnostics=[]
        merge_mirrors([a,b],diagnostics)
        self.assertEqual(diagnostics[0]['reason'],'source_conflict')

    def test_unknown_scopes_are_not_collapsed(self):
        p={'key':'adm_dp/1','published_at':'2026-10-19T15:00:00+00:00'}
        a=make_record(p,'2.1','Пошкоджені будинки.',period='p')
        b=make_record(p,'2.1','Пошкоджені будинки та магазин.',period='p')
        self.assertEqual(len(merge_mirrors([a,b],[])),2)


class MirrorRoleTests(unittest.TestCase):
    def test_swapped_casualty_roles_are_not_deduplicated(self):
        p={'key':'adm_dp/1','published_at':'2026-10-19T15:00:00+00:00'}
        a=make_record(p,'2.1','У Дніпрі двоє загинули. Троє поранені.',scope='Дніпро',period='p')
        b=make_record(dict(p,key='adm_dp/2'),'2.1','У Дніпрі троє загинули. Двоє поранені.',scope='Дніпро',period='p')
        diagnostics=[]
        self.assertEqual(len(merge_mirrors([a,b],diagnostics)),2)
        self.assertTrue(diagnostics)


class PracticalScopeTests(unittest.TestCase):
    def test_thunderstorm_does_not_invent_visibility_problem(self):
        p={'key':'DniproCityOfficial/1','channel':'DniproCityOfficial','post_id':1,
           'published_at':'2026-10-20T04:00:00+00:00','text':'У Дніпрі 20 жовтня прогнозується гроза.', 'url':'https://t.me/DniproCityOfficial/1'}
        core=compile_registry([p],{},datetime.fromisoformat('2026-10-20T06:00:00+00:00'))
        self.assertNotIn('погіршення видимості',render_registry(core))

    def test_allegations_keep_official_attribution_and_suspicion(self):
        p={'key':'SBUkr/1','channel':'SBUkr','post_id':1,
           'published_at':'2026-10-19T14:00:00+00:00','text':'У Дніпрі СБУ затримала підозрюваного у незаконному збуті зброї.', 'url':'https://t.me/SBUkr/1'}
        core=compile_registry([p],{},datetime.fromisoformat('2026-10-20T06:00:00+00:00'))
        self.assertIn('За даними СБУ',render_registry(core))
        self.assertIn('підозрюваного',render_registry(core))
        self.assertNotIn('засуджено',render_registry(core))


if __name__=='__main__':
    unittest.main()
