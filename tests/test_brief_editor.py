import copy
import json
import re
import tempfile
import os
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import collector as c
from fact_registry import compile_registry,render_registry
from brief_editor import CATALOG,normalize_names,geography_issues,unsupported_incident_clocks,city_prose
from operational_facts import current_attack_piece
from report_contract import publication_issues,review_input_digest

F=json.loads((Path(__file__).parent/'fixtures/source_core_20261024.json').read_text())
NOW=datetime.fromisoformat(F['status']['checked_at'])


def make(posts=None):
    r=compile_registry(F['posts'] if posts is None else posts,F['status']['channels'],NOW)
    return r,render_registry(r)


class BriefEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry,cls.text=make()

    def test_overview_states_actual_geography_and_consequences(self):
        block=self.text.split('1.1.\n')[1].split('\n\n')[0]
        for name in ('Дніпрі','передмісті','Дніпровського','Криворізького','Нікопольського','Синельниківського'):
            self.assertIn(name,block)
        self.assertIn('загиблі та поранені',block)
        self.assertIn('Пошкоджено житло',block)
        self.assertNotIn('Деталі наведено',block)
        self.assertNotIn('За звітний період зафіксовано атаки та їхні наслідки',block)

    def test_no_casualties_are_invented_when_sources_only_report_damage(self):
        post=dict(key='adm_dp/1',channel='adm_dp',text='Ворог атакував Дніпро. Пошкоджені приватні будинки.',
                  published_at='2026-10-23T10:00:00+00:00',url='https://t.me/adm_dp/1')
        r,_=make([post])
        summary=r['public_projection']['overview']
        self.assertNotIn('загибл',summary)
        self.assertNotIn('поранен',summary)
        self.assertIn('житло',summary)

    def test_overview_recognizes_finite_injury_word_forms(self):
        from event_brief import casualty_roles
        self.assertEqual(casualty_roles('Двоє людей загинули. Десятеро дістали поранень.'),{'dead':2,'injured':10})
        f=json.loads((Path(__file__).parent/'fixtures/source_core_20261020.json').read_text())
        r=compile_registry(f['posts'],f['status']['channels'],datetime.fromisoformat(f['status']['checked_at']))
        self.assertIn('загиблі та поранені',r['public_projection']['overview'])

    def test_overview_covers_joint_district_effects_without_allocating_count(self):
        f=json.loads((Path(__file__).parent/'fixtures/source_core_20261022.json').read_text())
        r=compile_registry(f['posts'],f['status']['channels'],datetime.fromisoformat(f['status']['checked_at']))
        overview=r['public_projection']['overview']
        self.assertIn('Синельниківського',overview)
        self.assertIn('Самарі',overview)
        self.assertNotIn('30 тисяч',overview)

    def test_official_reference_covers_all_eighty_six_communities(self):
        self.assertEqual(len(CATALOG['communities']),86)
        self.assertEqual(len({r['source_url'] for r in CATALOG['communities']}),86)
        self.assertEqual(len({r['district'] for r in CATALOG['communities']}),7)
        pid=next(r for r in CATALOG['communities'] if r['name']=='Підгородненська')
        self.assertEqual(pid['district'],'Дніпровський район')
        self.assertEqual(next(r for r in CATALOG['communities'] if r['name']=='Мозолевська')['district'],'Нікопольський район')

    def test_known_spelling_is_corrected_only_in_public_text(self):
        self.assertIn('Підгородненській громаді',self.text)
        self.assertNotIn('Підгороднянській',self.text)
        self.assertTrue(any('Підгороднянській' in r['source_text'] for r in self.registry['records']))
        self.assertTrue(self.registry['public_projection']['name_normalizations'])
        self.assertEqual(normalize_names('Підгороднянська назва'),'Підгороднянська назва')

    def test_unknown_community_name_requires_review(self):
        posts=copy.deepcopy(F['posts'])
        for p in posts:p['text']=p['text'].replace('Мозолевській','Неправдивській')
        r,_=make(posts)
        self.assertTrue(r['review_required'])
        self.assertTrue(any(d.get('detail')=='unknown_community_name' for d in r['diagnostics']))

    def test_known_name_in_wrong_district_requires_review(self):
        posts=copy.deepcopy(F['posts'])
        for p in posts:p['text']=p['text'].replace('Мозолевській','Раївській')
        r,_=make(posts)
        self.assertTrue(r['review_required'])
        self.assertTrue(any(d.get('detail')=='community_district_mismatch' for d in r['diagnostics']))

    def test_ambiguous_pokrovska_district_context_is_preserved(self):
        projection={'provenance':[
            {'text':'У Покровській громаді пошкоджено будинок.','place':'Нікопольщина','record_ids':['a']},
            {'text':'У Покровській громаді пошкоджено будинок.','place':'Синельниківський район','record_ids':['b']}]}
        self.assertEqual(geography_issues(projection),[])
        projection['provenance'][0]['place']='Дніпровський район'
        self.assertTrue(geography_issues(projection))

    def test_other_community_is_not_published_as_dnipro_city(self):
        projection={'provenance':[{'text':'У Підгородненській громаді сталася пожежа.','place':'Дніпро','record_ids':['a']}]}
        self.assertTrue(any(x['detail']=='community_in_city_scope' for x in geography_issues(projection)))

    def test_city_paragraph_separates_daily_people_total_from_house_damage(self):
        city=self.text.split('\nДніпро:\n')[1].split('\n\n')[0]
        self.assertIn('Загалом по місту одна людина загинула',city)
        self.assertIn('восьмеро поранених перебувають у лікарні',city)
        self.assertIn('пошкоджено щонайменше 5 приватних осель',city)
        self.assertIn('критичної інфраструктури',city)
        self.assertNotIn('Зайнялася пожежа. Ворог атакував',city)
        self.assertNotIn('ракетного озброєння',self.text)
        self.assertNotIn('13 поранених',self.text)

    def test_unknown_new_city_consequence_is_retained(self):
        paragraph=('Дніпро:\n23 жовтня у Дніпрі понівечені підприємства. '
                   'Пошкоджено церкву та дві амбулаторії.')
        self.assertEqual(city_prose(paragraph),paragraph)

    def test_joint_rescue_scope_is_not_silently_allocated_to_one_city(self):
        self.assertIn('За спільними даними ДСНС щодо Криворізького та Синельниківського районів',self.text)
        self.assertIn('пожежі ліквідовано',self.text)
        self.assertNotIn('Криворіжжя та Синельниківський район:\n',self.text)

    def test_actual_service_dates_times_and_streets_remain(self):
        for phrase in ('з 08:00 24.10.2026 до 20:00 26.10.2026','для окремих будинків',
                       'Богдана Ступки','пров. Зарічний','З 9:00 до 16:00','Старому мосту',
                       'Королеви Єлизавети II','від вул. Харківської до вул. Європейської'):
            self.assertIn(phrase,self.text)

    def test_saved_publication_time_cannot_become_a_rescue_time(self):
        changed=self.text.replace('Тіло загиблої людини','О 17:17 тіло загиблої людини')
        self.assertIn('unsupported_incident_clock',publication_issues(self.registry,changed,{}))
        self.assertEqual(unsupported_incident_clocks(self.registry,self.text),[])

    def clocks(self,source,heading='Дніпро',claim='О 15:20 ворог атакував місто.'):
        registry={'records':[{'section':'2.1','reporting_period':None,'state':'included','source_text':source}]}
        text='2.1. Обстріли\n'+heading+':\n'+claim+'\n2.2. Незаконне'
        return unsupported_incident_clocks(registry,text)

    def test_alarm_interval_does_not_certify_attack_time(self):
        source='У Дніпрі тривога тривала з 15:20 до 16:01 через загрозу атаки БпЛА.'
        self.assertTrue(self.clocks(source))

    def test_clock_in_another_city_cannot_certify_dnipro_attack(self):
        self.assertTrue(self.clocks('23 жовтня о 15:20 ворог атакував Нікополь.'))
        self.assertEqual(self.clocks('23 жовтня о 15:20 ворог атакував Дніпро.'),[])

    def test_approximation_and_bounds_cannot_become_exact_times(self):
        source='23 жовтня близько 15:20 ворог атакував Дніпро.'
        self.assertTrue(self.clocks(source))
        self.assertEqual(self.clocks(source,claim='Близько 15:20 ворог атакував місто.'),[])
        self.assertEqual(self.clocks(source,claim='~15:20: ворог атакував місто.'),[])
        for word in ('Після','До','Від'):
            source=f'23 жовтня {word.lower()} 15:20 ворог атакував Дніпро.'
            self.assertTrue(self.clocks(source))
            self.assertEqual(self.clocks(source,claim=f'{word} 15:20 ворог атакував місто.'),[])

    def test_numeric_source_date_is_not_a_clock(self):
        source='У Дніпрі після атаки від 23.10 пошкоджено будинок.'
        self.assertTrue(self.clocks(source,claim='Від 23:10 ворог атакував місто.'))
        self.assertEqual(self.clocks(source,claim='Наслідки атаки 23.10 у місті.'),[])

    def test_reporting_clock_is_not_reused_as_an_incident_clock(self):
        changed=self.text.replace('Тіло загиблої людини','О 18:30 тіло загиблої людини')
        self.assertTrue(unsupported_incident_clocks(self.registry,changed))

    def test_previous_night_with_explicit_start_date_is_excluded(self):
        post=next(p for p in F['posts'] if p['key']=='dsns_telegram/78570')
        start,end,*_=c.completed_report_window(NOW)
        text='23 жовтня. '+post['text']
        filtered,reason=current_attack_piece(text,datetime.fromisoformat(post['published_at']).astimezone(ZoneInfo('Europe/Kyiv')),start,end)
        self.assertIsNone(filtered)
        self.assertEqual(reason,'completed_prior_night_recap')

    def test_new_after_eight_attack_survives_without_previous_night_victims(self):
        post=next(p for p in F['posts'] if p['key']=='dsns_telegram/78570')
        start,end,*_=c.completed_report_window(NOW)
        text=post['text']+' Після 08:30 ворог атакував Дніпро. Пошкоджено лікарню.'
        filtered,reason=current_attack_piece(text,datetime.fromisoformat(post['published_at']).astimezone(ZoneInfo('Europe/Kyiv')),start,end)
        self.assertIn('Пошкоджено лікарню',filtered)
        self.assertNotIn('2 людей постраждали',filtered)
        self.assertEqual(reason,'explicit_new_episode_after_prior_night')

    def test_old_sbu_operation_is_not_brought_into_new_window(self):
        post=dict(key='SBUkr/1',channel='SBUkr',published_at='2026-10-20T10:31:00+00:00',
                  url='https://t.me/SBUkr/1',text='СБУ викрила на Дніпропетровщині схему розкрадання газу на 65 мільйонів гривень.')
        _,text=make(F['posts']+[post])
        self.assertNotIn('65 мільйонів',text)

    def test_missing_overview_or_wrong_spelling_blocks_publication(self):
        for old,new,issue in [
            (self.registry['public_projection']['overview'],'За звітний період зафіксовано атаки та їхні наслідки.','empty_security_overview'),
            ('Підгородненській','Підгороднянській','unverified_community_spelling')]:
            changed=self.text.replace(old,new)
            self.assertIn(issue,publication_issues(self.registry,changed,{}))

    def test_five_frozen_days_are_publishable_and_have_real_overviews(self):
        for day in ('20','21','22','23','24'):
            f=json.loads((Path(__file__).parent/f'fixtures/source_core_202610{day}.json').read_text())
            r=compile_registry(f['posts'],f['status']['channels'],datetime.fromisoformat(f['status']['checked_at']))
            text=render_registry(r)
            self.assertFalse(r['review_required'],day)
            self.assertLessEqual(len(text.split()),500,day)
            self.assertEqual(publication_issues(r,text,{}),[],day)
            self.assertTrue(r['public_projection']['overview'])

    def test_geography_conflict_blocks_before_model_or_delivery(self):
        posts=copy.deepcopy(F['posts'])
        for p in posts:p['text']=p['text'].replace('Мозолевській','Неправдивській')
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            with patch.object(c,'DATA_DIR',root),patch.object(c,'MORNING_REPORT_FILE',root/'morning_report.md'), \
                 patch.object(c,'read_alert_state',return_value={'last_daily_report':'2026-10-23'}), \
                 patch.dict(os.environ,{'SEND_MORNING_REPORT':'true','PRODUCTION_MONITOR':'true','FORCE_MORNING_REPORT':'false'}), \
                 patch('core_review.review_core') as reviewer,patch.object(c,'deliver_morning_report') as send, \
                 patch.object(c,'send_bot_message'):
                with self.assertRaises(RuntimeError):c.process_morning_report(posts,F['status']['channels'],NOW)
                reviewer.assert_not_called()
                send.assert_not_called()


if __name__=='__main__':unittest.main()
