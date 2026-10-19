import json
import os
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import collector as c
from ai_report import validate_report
from quota_budget import UsageLedger
from report_rules import place_casualty_problems, transport_link_problems, source_problems
from test_source_accuracy import report, source


FIXTURE = Path(__file__).parent / 'fixtures' / 'morning_20261019.json'
NOW = c.parse_datetime('2026-10-19T05:12:26Z')


class MorningCutoffTests(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads(FIXTURE.read_text())

    def test_real_0800_bulletin_published_17_seconds_late_is_included(self):
        posts = c.report_window_posts(self.fixture['posts'], NOW)
        keys = {p['key'] for p in posts}
        self.assertIn('dnipropetrovskaODA/32672', keys)
        self.assertNotIn('dsns_telegram/78061', keys)
        self.assertNotIn('gunpvdp/37210', keys)

    def test_ordinary_new_attack_after_cutoff_is_not_included(self):
        p = dict(self.fixture['posts'][-1], channel='adm_dp', published_at='2026-10-19T05:05:00Z',
                 text='Щойно росіяни атакували Дніпро. Пошкоджено будинок.')
        self.assertFalse(c.report_window_posts([p], NOW))

    def test_late_wrong_date_wrong_channel_and_future_publications_are_excluded(self):
        p = next(p for p in self.fixture['posts'] if p['key'] == 'dnipropetrovskaODA/32672')
        for changes in ({'text':p['text'].replace('19 жовтня','18 жовтня')},
                        {'channel':'other'}, {'published_at':'2026-10-19T05:16:00Z'},
                        {'text':p['text']+' Після 08:00 була нова атака.'}):
            with self.subTest(changes=changes):
                self.assertFalse(c.report_window_posts([dict(p, **changes)], NOW))

    def test_kyiv_district_is_not_oblast_even_in_local_repost(self):
        p = next(p for p in self.fixture['posts'] if p['key'] == 'dsns_telegram/78061')
        self.assertFalse(c.is_regional(p))
        self.assertFalse(c.is_regional(dict(p,channel='adm_dp')))
        self.assertTrue(c.is_regional(dict(p,text='У Дніпропетровській області завдали удару по Дніпровському району.')))

    def test_ambiguous_national_geography_does_not_establish_region(self):
        self.assertFalse(c.is_regional({'channel':'dsns_telegram','text':'У Дніпровському районі пожежа.'}))
        self.assertFalse(c.is_regional({'channel':'SBUkr','text':'Покровський район: вилучено зброю.'}))

    def test_original_delivered_report_is_rejected_against_original_sources(self):
        posts = [dict(p, category_hint=c.classify_post(p)) for p in self.fixture['posts']
                 if c.parse_datetime(p['published_at']) < c.parse_datetime('2026-10-19T05:00:00Z')]
        with self.assertRaisesRegex(ValueError, 'unsupported place/date|unsupported causal link'):
            validate_report(self.fixture['rejected_report'], '19.10.2026', posts=posts)

    def test_corrected_report_passes_against_real_cutoff_evidence(self):
        posts=[dict(p,category_hint=c.classify_post(p),
                    published_local=c.parse_datetime(p['published_at']).astimezone(c.KYIV).strftime('%d.%m.%Y %H:%M за Києвом'))
               for p in c.report_window_posts(self.fixture['posts'],NOW) if c.classify_post(p)]
        self.assertEqual(validate_report(self.fixture['corrected_report'],'19.10.2026',posts=posts),
                         self.fixture['corrected_report'].strip())

    def test_casualty_is_not_moved_from_later_night_to_previous_day(self):
        day = source('18 жовтня. ▪ У Дніпрі пошкоджена інфраструктура. ▪ На Нікопольщині постраждала жінка.')
        night = source('19 жовтня. ▪ У Дніпрі госпіталізована 84-річна жінка.')
        bad = '18 жовтня у Дніпрі одна людина дістала поранень. 19 жовтня на Нікопольщині є пошкодження.'
        good = '18 жовтня на Нікопольщині постраждала жінка. 19 жовтня у Дніпрі госпіталізована 84-річна жінка.'
        self.assertTrue(place_casualty_problems(bad, [day,night]))
        self.assertFalse(place_casualty_problems(good, [day,night]))

    def test_city_and_district_casualties_are_distinct(self):
        posts=[source('У Дніпрі пошкоджений будинок.'),source('У Дніпровському районі одна людина поранена.')]
        self.assertTrue(place_casualty_problems('У Дніпрі одна людина поранена.', posts))
        self.assertFalse(place_casualty_problems('У Дніпровському районі одна людина поранена.', posts))

    def test_equal_attack_numbers_from_two_bulletins_are_both_required(self):
        posts=[source('Понад 20 разів атакували чотири райони.'),
               source('Понад 20 разів атакували три райони.')]
        error='distinct attack bulletins with equal counts were collapsed'
        self.assertIn(error,source_problems(report('Понад 20 разів атакували чотири райони.'),posts))
        self.assertNotIn(error,source_problems(report('Вдень понад 20 разів атакували чотири райони. У ранковому зведенні понад 20 атак на три райони.'),posts))

    def test_independent_transport_notices_cannot_supply_invented_cause(self):
        posts=[source('На вулиці Королеви Єлизавети II перекрито рух.', '1.2'),
               source('Тролейбус №6 курсує через Центральний міст.', '1.2')]
        bad=report('Атак немає.').replace('1.2. У перевірених джерелах повідомлень за звітний період не виявлено.',
            '1.2. Через ремонт вулиці Королеви Єлизавети II тролейбус №6 курсує через Центральний міст.')
        self.assertTrue(transport_link_problems(bad, posts))


class OperationalRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = Path(self.tmp.name)/'state.json'
        self.state.write_text(json.dumps({'initialized':True,'alerted_keys':[]}))
        self.patches=[patch.object(c,'ALERT_STATE_FILE',self.state),
                      patch.dict(os.environ,{'TELEGRAM_BOT_TOKEN':'test','TELEGRAM_CHAT_ID':'test'})]
        for p in self.patches:p.start();self.addCleanup(p.stop)
        self.posts=json.loads(FIXTURE.read_text())['posts']
        self.attack=next(p for p in self.posts if p['key']=='dnipropetrovskaODA/32662')

    def test_actual_attack_wordings_are_resonant(self):
        self.assertTrue(c.is_resonant(self.attack))
        self.assertTrue(c.is_resonant(next(p for p in self.posts if p['key']=='dnipropetrovskaODA/32658')))
        self.assertFalse(c.is_resonant(next(p for p in self.posts if p['key']=='dsns_telegram/78061')))
        self.assertFalse(c.is_resonant(dict(self.attack,text='У застосунку тепер карта орієнтовного руху ворожих ракет.')))

    @patch('collector.send_bot_message',return_value=True)
    def test_attack_older_than_two_hours_is_delivered_after_five_hour_gap_once(self, send):
        previous=c.parse_datetime('2026-10-19T00:06:00Z')
        self.assertFalse(c.process_alerts([self.attack],NOW,previous))
        self.assertEqual(send.call_count,1)
        self.assertIn('після перерви',send.call_args.args[0])
        c.process_alerts([self.attack],NOW+timedelta(minutes=30),NOW)
        self.assertEqual(send.call_count,1)

    @patch('collector.send_bot_message',side_effect=[RuntimeError('network'),True])
    def test_saved_post_is_retried_after_send_failure(self, send):
        previous=NOW-timedelta(hours=6)
        self.assertEqual(c.process_alerts([self.attack],NOW,previous),[self.attack['key']])
        self.assertNotIn(self.attack['key'],json.loads(self.state.read_text())['alerted_keys'])
        self.assertFalse(c.process_alerts([self.attack],NOW+timedelta(minutes=30),NOW))
        self.assertIn(self.attack['key'],json.loads(self.state.read_text())['alerted_keys'])
        self.assertEqual(send.call_count,2)

    @patch('collector.send_bot_message',return_value=True)
    def test_cross_channel_exact_duplicates_sent_once_and_history_retained(self, send):
        duplicate=dict(self.attack,key='adm_dp/44971',channel='adm_dp')
        c.process_alerts([self.attack,duplicate],NOW,NOW-timedelta(hours=6))
        self.assertEqual(send.call_count,1)
        c.process_alerts([self.attack,duplicate],NOW+timedelta(minutes=30),NOW)
        self.assertEqual(set(json.loads(self.state.read_text())['alerted_keys']),{self.attack['key'],duplicate['key']})

    @patch('collector.send_bot_message',return_value=False)
    def test_missing_telegram_delivery_is_not_success(self,send):
        with self.assertRaisesRegex(RuntimeError,'not marked as delivered'):
            c.send_long_bot_message('test')

    @patch('collector.send_bot_message')
    @patch.dict(os.environ,{'SEND_OPERATIONAL_ALERTS':'false'})
    def test_dry_run_does_not_send_alerts_or_advance_delivery_state(self,send):
        before=self.state.read_text()
        c.process_alerts([self.attack],NOW,NOW-timedelta(hours=6))
        send.assert_not_called();self.assertEqual(self.state.read_text(),before)

    @patch('collector.send_bot_message',side_effect=[True,RuntimeError('network'),True])
    def test_partial_report_retries_remaining_part_without_new_ai_or_duplicate(self,send):
        text='А'*3000+'\n\n'+'Б'*3000
        state=json.loads(self.state.read_text())
        with self.assertRaises(RuntimeError):
            c.deliver_morning_report(text,state,'2026-10-19')
        saved=json.loads(self.state.read_text())
        self.assertEqual(saved['pending_daily_report']['sent_parts'],1)
        self.assertNotIn('last_daily_report',saved)
        with patch('ai_report.generate_report') as generate:
            c.process_morning_report(self.posts,{},NOW+timedelta(minutes=30))
        generate.assert_not_called()
        self.assertEqual(send.call_count,3)
        self.assertTrue(send.call_args.args[0].startswith('Частина 2/2'))
        saved=json.loads(self.state.read_text())
        self.assertEqual(saved['last_daily_report'],'2026-10-19')
        self.assertNotIn('pending_daily_report',saved)

    @patch.dict(os.environ,{'GITHUB_ACTIONS':'true','GITHUB_EVENT_NAME':'workflow_dispatch','PRODUCTION_MONITOR':'true'})
    def test_production_watchdog_keeps_morning_reserve_access(self):
        self.assertEqual(UsageLedger.from_environment('model').event,'production_dispatch')

    @patch('collector.send_long_bot_message')
    def test_already_delivered_date_is_not_generated_or_sent_again(self,send):
        self.state.write_text(json.dumps({'initialized':True,'alerted_keys':[],'last_daily_report':'2026-10-19'}))
        with patch.dict(os.environ,{'FORCE_MORNING_REPORT':'false'}),patch('ai_report.generate_report') as generate:
            c.process_morning_report(self.posts,{},NOW)
        generate.assert_not_called();send.assert_not_called()


if __name__=='__main__':unittest.main()
