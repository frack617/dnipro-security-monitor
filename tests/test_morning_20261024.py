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
from fact_registry import compile_registry,render_registry
from operational_facts import background_reason,current_attack_piece,dated_power_interruption,has_operational_attack_assertion
from report_contract import publication_issues

F=json.loads((Path(__file__).parent/'fixtures/source_core_20261024.json').read_text())
NOW=datetime.fromisoformat(F['status']['checked_at'])


def render(posts=None):
    r=compile_registry(F['posts'] if posts is None else posts,F['status']['channels'],NOW)
    return r,render_registry(r)


class Morning24Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry,cls.text=render()

    def test_real_failure_fits_without_increasing_limit(self):
        self.assertEqual(len(F['blocked_report'].split()),565)
        self.assertLessEqual(len(self.text.split()),500)
        self.assertEqual(publication_issues(self.registry,self.text,F['status']['channels']),[])
        self.assertFalse(self.registry['review_required'])

    def test_previous_night_recap_is_audit_only_not_a_new_day_event(self):
        records=[r for r in self.registry['records'] if r['source_key']=='dsns_telegram/78570']
        self.assertTrue(records)
        self.assertTrue(all(r['state']=='excluded' for r in records))
        self.assertEqual(records[0]['reason'],'completed_prior_night_recap')
        self.assertIn('Протягом ночі',records[0]['source_text'])
        self.assertNotIn('У Павлограді - адмінбудівля',self.text)
        self.assertNotIn('2 людей постраждали',self.text)

    def test_explicit_new_attack_after_eight_is_not_excluded_as_prior_night(self):
        post=next(p for p in F['posts'] if p['key']=='dsns_telegram/78570')
        text=post['text']+' Після 08:30 ворог знову атакував Дніпро. Пошкоджено лікарню.'
        start,end,*_=c.completed_report_window(NOW)
        filtered,reason=current_attack_piece(text,datetime.fromisoformat(post['published_at']).astimezone(ZoneInfo('Europe/Kyiv')),start,end)
        self.assertIsNotNone(filtered)
        self.assertNotEqual(reason,'completed_prior_night_recap')

    def test_ceremony_not_reported_as_attack(self):
        r=next(r for r in self.registry['records'] if r['source_key']=='DniproCityOfficial/15236')
        self.assertEqual(r['state'],'excluded')
        self.assertIn('угоду',r['source_text'])
        for word in ('ЛаГранд','церемонії','побратим','І міста, яке'):
            self.assertNotIn(word,self.text)
        self.assertIsNone(background_reason('Під час церемонії ворог атакував Дніпро. Пошкоджено будинок, постраждали двоє людей.'))

    def test_unknown_background_wording_still_needs_an_asserted_event(self):
        text='Делегація обговорила співпрацю. Дніпро щодня зазнає атак та втрат. Говорили про підтримку міста.'
        self.assertFalse(has_operational_attack_assertion(text))
        text='Ворог атакував критичну інфраструктуру Дніпра.'
        self.assertTrue(has_operational_attack_assertion(text))
        self.assertTrue(has_operational_attack_assertion('У Дніпрі пошкоджені приватні будинки.'))
        self.assertTrue(has_operational_attack_assertion('Через ворожу атаку без світла залишилися понад 30 тисяч мешканців у Павлоградському, Синельниківському районах і місті Самар.'))

    def test_full_power_interval_and_service_type_are_kept(self):
        self.assertIn('з 08:00 24.10.2026 до 20:00 26.10.2026',self.text)
        self.assertIn('припинення електропостачання',self.text)
        self.assertIn('термінові аварійно-відновлювальні роботи',self.text)
        for name in ('Богдана Ступки','Братська','Героїв України','Дмитра Бочарникова','Заводська',
                     'Зарічна','Ігоря Плосконоса','Квітуча','Кільцева','Лебединська','Лінійна','Ягідна','пров. Зарічний'):
            self.assertIn(name,self.text)
        self.assertIn('для окремих будинків',self.text)

    def test_power_formatter_refuses_mixed_city_unknown_fact_or_invalid_dates(self):
        post=next(p for p in F['posts'] if p['key']=='cek_info/4274')
        self.assertIsNotNone(dated_power_interruption(post))
        for text in (post['text']+' У м. САМАР також відключено будинки.',
                     post['text']+' Водопостачання припинено.',
                     post['text'].replace('26.10.2026','22.10.2026')):
            self.assertIsNone(dated_power_interruption(dict(post,text=text)))

    def test_transport_keeps_restriction_interval_and_landmarks_not_detour(self):
        for phrase in ('З 9:00 до 16:00','Богдана Хмельницького','КСК «Шинник»','заводу Металовиробів','Інженерної','Словацькій'):
            self.assertIn(phrase,self.text)
        for phrase in ('прямуватимуть','кінцевої зупинки трамвая','№12','21:16','21:46'):
            self.assertNotIn(phrase,self.text)
        self.assertEqual(self.text.count('КСК «Шинник»'),1)

    def test_all_communities_and_both_reporting_scopes_survive(self):
        for phrase in ('Майже 70','Майже 10','4 райони','три райони','11 людей поранено',
                       'Підгородненській','Марганецькій','Червоногригорівській','Покровській',
                       'Мозолевській','Карпівській','Грушівській','Васильківській'):
            self.assertIn(phrase,self.text)
        self.assertEqual(self.text.count('Майже 70'),1)
        self.assertEqual(self.text.count('Майже 10'),1)
        self.assertNotIn('80 разів',self.text)
        self.assertIn('За цим зведенням, постраждалих немає',self.text)
        self.assertNotIn('за добу постраждалих немає',self.text)

    def test_clinical_and_house_details_not_lost_by_cutting_prose(self):
        for phrase in ('26-річний чоловік у вкрай тяжкому стані','щонайменше 5 приватних осель',
                       'Зруйновано приватний будинок','критичної інфраструктури',
                       '66 і 46 років','55-річна жінка'):
            self.assertIn(phrase,self.text)

    def test_suburb_patients_are_not_assigned_to_city_or_added(self):
        suburb=self.text.split('\nПередмістя Дніпра:\n')[1].split('\n\n')[0]
        city=self.text.split('\nДніпро:\n')[1].split('\n\n')[0]
        self.assertIn('26-річний',suburb)
        self.assertIn('Серед госпіталізованих',suburb)
        self.assertNotIn('5 поранених',suburb)
        self.assertTrue(any(p.get('archived_intermediate_count')==5 for p in self.registry['public_projection']['provenance']))
        self.assertNotIn('26-річний',city)
        self.assertIn('восьмеро поранених',city)
        self.assertNotIn('13 поранених',self.text)
        self.assertNotIn('16 поранених',self.text)

    def test_preliminary_two_is_not_presented_as_additional_people(self):
        self.assertNotIn('Двоє людей дістали поранень через атаку',self.text)
        self.assertTrue(any('Двоє людей дістали поранень' in r['source_text'] for r in self.registry['records']))
        self.assertIn('пожежа на підприємстві',self.text)

    def test_regional_context_keeps_community_block_without_city_keyword(self):
        r=next(r for r in self.registry['records'] if r['source_key']=='dsns_telegram/78672' and 'травмовано трьох' in r['source_text'])
        self.assertEqual(r['state'],'included')
        self.assertTrue(r['display'])
        self.assertEqual(r['section'],'2.1')
        self.assertTrue(any(p.get('covered_record_id')==r['id'] for p in self.registry['public_projection']['provenance']))

    def test_new_consequence_from_rescue_recap_is_not_erased(self):
        posts=copy.deepcopy(F['posts'])
        for p in posts:
            if p['key']=='dsns_telegram/78672':
                p['text']=p['text'].replace('Пошкоджено приватні будинки, підприємства та об’єкти інфраструктури.',
                    'Пошкоджено приватні будинки, підприємства, об’єкти інфраструктури та церкву.')
        _,text=render(posts)
        self.assertIn('церкву',text)

    def test_shared_rescue_effect_keeps_joint_scope_without_repeating_communities(self):
        self.assertEqual(self.text.count('Карпівськ'),1)
        self.assertIn('Криворізького та Синельниківського районів',self.text)
        self.assertIn('пошкоджено об’єкти інфраструктури',self.text)
        self.assertIn('пожежі ліквідовано',self.text)
        posts=copy.deepcopy(F['posts'])
        for p in posts:
            if p['key']=='dsns_telegram/78672':
                p['text']=p['text'].replace('Карпівська та Грушівська','Карпівська, Грушівська та Зеленодольська')
        _,text=render(posts)
        self.assertIn('Зеленодольська',text)

    def test_conflicting_recap_count_blocks_instead_of_silent_merge(self):
        posts=copy.deepcopy(F['posts'])
        for p in posts:
            if p['key']=='dsns_telegram/78672':
                p['text']=p['text'].replace('травмовано трьох людей','травмовано чотирьох людей')
        registry,text=render(posts)
        self.assertTrue(registry['review_required'])
        self.assertIn('чотирьох',text)

    def test_swapped_death_and_injury_roles_not_accepted_as_same_set(self):
        posts=copy.deepcopy(F['posts'])
        for p in posts:
            if p['key']=='dsns_telegram/78672':
                p['text']=p['text'].replace('одна людина загинула, ще 11 постраждали','11 людей загинули, ще одна постраждала')
        registry,text=render(posts)
        self.assertTrue(registry['review_required'])
        self.assertNotEqual(registry['public_projection']['provenance'],self.registry['public_projection']['provenance'])
        self.assertIn('11 людей загинули',text)

    def test_source_audit_and_public_facts_have_complete_provenance(self):
        provenance=self.registry['public_projection']['provenance']
        accounted={i for p in provenance for i in p.get('record_ids',[])}
        accounted.update(p['covered_record_id'] for p in provenance if 'covered_record_id' in p)
        for r in self.registry['records']:
            if r['state']=='included' and r['section']=='2.1' and r['display']:
                self.assertIn(r['id'],accounted)
        self.assertFalse(re.search(r'УДніпрі|УПідгород|області області|загинула\.\.',self.text))

    def test_five_archived_days_fit_and_keep_five_public_points(self):
        for day in ('20','21','22','23','24'):
            f=json.loads((Path(__file__).parent/f'fixtures/source_core_202610{day}.json').read_text())
            r=compile_registry(f['posts'],f['status']['channels'],datetime.fromisoformat(f['status']['checked_at']))
            text=render_registry(r)
            self.assertLessEqual(len(text.split()),500,day)
            self.assertFalse(r['review_required'],day)
            self.assertEqual(re.findall(r'(?m)^([12]\.[1-4])\.',text),['1.1','1.2','2.1','2.2','2.3'])
            self.assertEqual(publication_issues(r,text,{}),[])

    def test_production_entry_can_deliver_exact_saved_text_once(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            with patch.object(c,'DATA_DIR',root),patch.object(c,'MORNING_REPORT_FILE',root/'morning_report.md'), \
                 patch.object(c,'read_alert_state',return_value={'last_daily_report':'2026-10-23'}), \
                 patch.dict(os.environ,{'SEND_MORNING_REPORT':'true','FORCE_MORNING_REPORT':'false','PRODUCTION_MONITOR':'true'}), \
                 patch('core_review.review_core',return_value={'state':'completed','requests':1,'provider':'gemini','issues':[]}) as reviewer, \
                 patch.object(c,'deliver_morning_report') as send,patch.object(c,'send_bot_message') as notice:
                c.process_morning_report(F['posts'],F['status']['channels'],NOW)
                self.assertEqual(send.call_count,1)
                self.assertEqual(reviewer.call_count,1)
                self.assertEqual(send.call_args.args[0],(root/'morning_report.md').read_text().strip())
                status=json.loads((root/'report_generation_status.json').read_text())
                self.assertEqual(status['delivery_state'],'confirmed')
                self.assertEqual(status['publication_issues'],[])
                notice.assert_not_called()


if __name__=='__main__':
    unittest.main()
