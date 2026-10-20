import json
import os
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import collector as c
from fallback_report import build_sections
from report_rules import transport_link_problems
from report_sections import recover_transport_section
from transport_state import restored_routes


ROOT=Path(__file__).parent/'fixtures'
F=json.loads((ROOT/'reply_body_20261019.json').read_text())


class ReplyBodyTests(unittest.TestCase):
    def test_confirmed_two_text_blocks_choose_own_body(self):
        posts=c.parse_page('DniproCityOfficial',(ROOT/'reply_body_20261019.html').read_text())
        self.assertEqual(posts[0]['text'],F['old']['text'])
        self.assertEqual(posts[1]['text'],F['new']['text'])
        self.assertEqual(posts[1]['reply_to'],F['old']['key'])
        self.assertEqual(posts[1]['published_at'],F['new']['published_at'])
        self.assertNotIn('Сонячна',posts[1]['text'])

    def test_quote_only_media_is_not_an_attack(self):
        html='''<div class="tgme_widget_message" data-post="adm_dp/999">
        <a class="tgme_widget_message_reply" href="https://t.me/adm_dp/888">
        <div class="tgme_widget_message_text">Росіяни атакували Дніпро. Є поранені.</div>
        <time datetime="2026-10-17T12:00:00Z"></time></a>
        <time datetime="2026-10-19T12:00:00Z"></time></div>'''
        p=c.parse_page('adm_dp',html)[0]
        self.assertEqual(p['text'],'[Медіа без тексту]')
        self.assertEqual(p['published_at'],'2026-10-19T12:00:00+00:00')
        self.assertFalse(c.is_resonant(p))

    def test_link_preview_is_not_own_text(self):
        html='''<div class="tgme_widget_message" data-post="adm_dp/999">
        <div class="tgme_widget_message_link_preview"><div class="tgme_widget_message_text">Старий обстріл.</div></div>
        <div class="tgme_widget_message_text"><b>У Дніпрі</b> нове повідомлення.</div>
        <time datetime="2026-10-19T12:00:00Z"></time></div>'''
        p=c.parse_page('adm_dp',html)[0]
        self.assertNotIn('Старий',p['text'])
        self.assertIn('нове повідомлення',p['text'])

    def test_nested_message_is_not_collected_as_current_post(self):
        html='''<div class="tgme_widget_message" data-post="adm_dp/999">
        <div class="tgme_widget_message" data-post="adm_dp/888"><div class="tgme_widget_message_text">Цитата</div><time datetime="2026-10-17T12:00:00Z"></time></div>
        <div class="tgme_widget_message_text">Власний текст</div><time datetime="2026-10-19T12:00:00Z"></time></div>'''
        posts=c.parse_page('adm_dp',html)
        self.assertEqual(len(posts),1)
        self.assertEqual(posts[0]['text'],'Власний текст')


class RestorationTests(unittest.TestCase):
    def setUp(self):
        self.posts=[dict(F[k],category_hint='1.2') for k in ('old','new')]

    def test_restoration_classified_and_alerted(self):
        self.assertEqual(c.classify_post(F['new']),'1.2')
        self.assertTrue(c.is_resonant(F['new']))
        self.assertEqual(restored_routes(F['new']['text']),
                         {('тролейбус','6'),('автобус','18'),('автобус','134')})

    def test_recovery_cannot_leave_only_old_restriction(self):
        report='1.2. '+F['old']['text']+'\n1.3. Немає повідомлень.'
        self.assertIn('missing source transport restoration',transport_link_problems(report,self.posts))
        out=recover_transport_section(report,self.posts)
        self.assertEqual(transport_link_problems(out,self.posts),[])
        self.assertNotIn('За попереднім повідомленням:',out)
        self.assertNotIn('Інститут фізкультури',out)
        self.assertIn('Відновлюється рух',out)
        self.assertNotIn('вул.…',out)

    def test_all_restored_routes_required_not_just_one(self):
        report='1.2. Відновлено рух тролейбуса №6.\n1.3. Немає повідомлень.'
        self.assertIn('missing source transport restoration',transport_link_problems(report,self.posts))

    def test_fallback_preserves_explicit_source_sequence(self):
        out=build_sections({'1.2':self.posts},date(2026,10,20))['1.2']
        self.assertIn('За попереднім повідомленням:',out)
        self.assertIn('Пізніше повідомлено про відновлення:',out)
        self.assertEqual(transport_link_problems('1.2. '+out+'\n1.3. Немає.',self.posts),[])

    def test_restoration_of_power_or_business_is_not_a_route(self):
        for text in ('Відновлено електропостачання будинку №6.',
                     'Відновлено роботу підприємства №134.',
                     'Не відновлено рух автобуса №134.',
                     'Поки не було відновлено рух автобуса №134.'):
            self.assertFalse(restored_routes(text))

    def test_later_restriction_is_not_overridden_by_earlier_restoration(self):
        later=dict(F['old'],published_at='2026-10-19T13:00:00Z',category_hint='1.2')
        self.assertNotIn('missing source transport restoration',
            transport_link_problems('1.2. '+later['text']+'\n1.3. Немає.',[self.posts[1],later]))


class ParserMigrationTests(unittest.TestCase):
    def test_corrected_restoration_sent_once_outside_normal_overlap(self):
        now=c.parse_datetime('2026-10-19T15:30:00Z')
        state={'initialized':True,'alerted_keys':[F['old']['key']],
               'last_alert_scan_at':'2026-10-19T15:00:00Z','last_daily_report':'2026-10-19'}
        keys=c.recovered_restoration_keys([F['old'],F['new']],{F['new']['key']},state,now)
        self.assertEqual(keys,[F['new']['key']])
        with tempfile.TemporaryDirectory() as d, patch.object(c,'ALERT_STATE_FILE',Path(d)/'state.json'), \
             patch.dict(os.environ,{'SEND_OPERATIONAL_ALERTS':'true','TELEGRAM_BOT_TOKEN':'offline','TELEGRAM_CHAT_ID':'offline'}), \
             patch.object(c,'send_bot_message',return_value=True) as send:
            c.save_alert_state(state)
            c.process_alerts([F['old'],F['new']],now,recovered_keys=keys)
            self.assertEqual(send.call_count,1)
            self.assertIn('Уточнення після виправлення читання допису.',send.call_args.args[0])
            self.assertIn('Відновлюється рух',send.call_args.args[0])
            c.process_alerts([F['old'],F['new']],now,recovered_keys=keys)
            self.assertEqual(send.call_count,1)
            self.assertEqual(c.read_alert_state()['last_daily_report'],'2026-10-19')

    def test_no_forced_backlog_without_prior_alert_or_on_another_day(self):
        now=c.parse_datetime('2026-10-19T15:30:00Z')
        self.assertEqual(c.recovered_restoration_keys([F['old'],F['new']],{F['new']['key']},
            {'alerted_keys':[]},now),[])
        self.assertEqual(c.recovered_restoration_keys([F['old'],F['new']],{F['new']['key']},
            {'alerted_keys':[F['old']['key']]},now+timedelta(days=1)),[])

    def test_later_restriction_prevents_forced_old_restoration(self):
        later=dict(F['old'],key='DniproCityOfficial/15099',published_at='2026-10-19T14:00:00Z')
        self.assertEqual(c.recovered_restoration_keys([F['old'],F['new'],later],{F['new']['key']},
            {'alerted_keys':[F['old']['key']]},c.parse_datetime('2026-10-19T15:30:00Z')),[])

    def test_dry_alert_scan_does_not_mark_corrected_restoration_delivered(self):
        with tempfile.TemporaryDirectory() as d, patch.object(c,'ALERT_STATE_FILE',Path(d)/'state.json'), \
             patch.dict(os.environ,{'SEND_OPERATIONAL_ALERTS':'false'}):
            state={'initialized':True,'alerted_keys':[F['old']['key']]}
            c.save_alert_state(state)
            c.process_alerts([F['new']],c.parse_datetime('2026-10-19T15:30:00Z'),recovered_keys=[F['new']['key']])
            self.assertEqual(c.read_alert_state(),state)

    def test_old_cached_preview_replaced_and_refresh_bounded(self):
        now=c.parse_datetime('2026-10-19T15:00:00Z')
        for version in (None,c.PARSER_VERSION):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as d:
                status=Path(d)/'status.json'
                status.write_text(json.dumps({'checked_at':now.isoformat(),
                    'channels':{'DniproCityOfficial':{'parser_version':version}}}))
                with patch.object(c,'STATUS_FILE',status), patch.object(c,'utc_now',return_value=now), \
                     patch.object(c,'load_channels',return_value=['DniproCityOfficial']), \
                     patch.object(c,'read_existing',return_value=[F['bad_cached']]), \
                     patch.object(c,'collect_channel',return_value=[F['new']]) as collect, \
                     patch.object(c,'write_outputs') as write, \
                     patch.object(c,'process_alerts',return_value=[]), \
                     patch.object(c,'process_morning_report'):
                    c.main()
                expected=now-timedelta(hours=c.LOOKBACK_HOURS) if version is None else \
                    max(now-timedelta(hours=c.LOOKBACK_HOURS),c.parse_datetime(F['new']['published_at'])-timedelta(hours=2))
                self.assertEqual(collect.call_args.args[2],expected)
                self.assertEqual(write.call_args.args[0][0]['text'],F['new']['text'])
                self.assertEqual(write.call_args.args[1]['DniproCityOfficial']['parser_version'],c.PARSER_VERSION)

    def test_recovered_marker_survives_a_following_poll_until_delivery(self):
        now=c.parse_datetime('2026-10-19T15:30:00Z')
        with tempfile.TemporaryDirectory() as d:
            status=Path(d)/'status.json'
            status.write_text(json.dumps({'checked_at':now.isoformat(),
                'channels':{'DniproCityOfficial':{'parser_version':c.PARSER_VERSION}}}))
            with patch.object(c,'STATUS_FILE',status), patch.object(c,'utc_now',return_value=now), \
                 patch.object(c,'load_channels',return_value=['DniproCityOfficial']), \
                 patch.object(c,'read_existing',return_value=[dict(F['new'],parser_recovered=True)]), \
                 patch.object(c,'read_alert_state',return_value={'alerted_keys':[F['old']['key']]}), \
                 patch.object(c,'collect_channel',return_value=[dict(F['new'])]), \
                 patch.object(c,'write_outputs') as write, \
                 patch.object(c,'process_alerts',return_value=[]) as alerts, \
                 patch.object(c,'process_morning_report'):
                c.main()
            self.assertTrue(write.call_args.args[0][0]['parser_recovered'])
            self.assertEqual(alerts.call_args.kwargs['recovered_keys'],[F['new']['key']])


if __name__=='__main__':
    unittest.main()
