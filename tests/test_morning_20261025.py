import copy
import json
from datetime import datetime
from pathlib import Path
import re
import os
import tempfile
from unittest.mock import patch
import unittest

from fact_registry import compile_registry, render_registry
from report_contract import publication_issues
from event_brief import locality, split_places
from source_claims import selected_text
from operational_prose import concise

ROOT=Path(__file__).resolve().parents[1]
F=json.loads((ROOT/'tests/fixtures/source_core_20261025.json').read_text())
NOW=datetime.fromisoformat(F['status']['checked_at'])


def prepare(posts=None):
    r=compile_registry(copy.deepcopy(F['posts'] if posts is None else posts),F['status']['channels'],NOW)
    return r,render_registry(r)


def paragraph(text,place):
    return re.search(r'(?m)^'+re.escape(place)+r':\n([^\n]+)',text)[1]


class Morning25Tests(unittest.TestCase):
    def test_production_retries_blocked_day_then_skips_confirmed_date(self):
        import collector as c
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/'report_generation_status.json').write_text(json.dumps(F['blocked_generation']))
            with patch.object(c,'DATA_DIR',root),patch.object(c,'MORNING_REPORT_FILE',root/'morning_report.md'), \
                 patch.object(c,'read_alert_state',return_value={'last_daily_report':'2026-10-24','daily_report_block_notice':'2026-10-25'}) as state, \
                 patch.dict(os.environ,{'SEND_MORNING_REPORT':'true','FORCE_MORNING_REPORT':'false','PRODUCTION_MONITOR':'true'}), \
                 patch('core_review.review_core',return_value={'state':'completed','requests':1,'provider':'gemini','issues':[]}) as reviewer, \
                 patch.object(c,'deliver_morning_report') as send,patch.object(c,'send_bot_message') as notice:
                c.process_morning_report(F['posts'],F['status']['channels'],NOW)
                self.assertEqual(send.call_count,1);self.assertEqual(reviewer.call_count,1)
                self.assertEqual(send.call_args.args[0],(root/'morning_report.md').read_text().strip())
                status=json.loads((root/'report_generation_status.json').read_text())
                self.assertEqual(status['delivery_state'],'confirmed');self.assertEqual(status['publication_issues'],[])
                state.return_value={'last_daily_report':'2026-10-25'}
                c.process_morning_report(F['posts'],F['status']['channels'],NOW)
                self.assertEqual(send.call_count,1);self.assertEqual(reviewer.call_count,1)
                notice.assert_not_called()

    def test_real_day_fits_without_losing_obligations(self):
        r,t=prepare()
        self.assertEqual(len(F['blocked_report'].split()),671)
        self.assertLessEqual(len(t.split()),500)
        self.assertEqual(publication_issues(r,t,F['status']['channels']),[])
        self.assertFalse(r['review_required'])
        self.assertFalse([c for c in r['claim_plan'] if c['disposition']=='unresolved'])
        # Clock change gives this particular reporting window 25 hours.
        start=datetime.fromisoformat(r['window']['start']);end=datetime.fromisoformat(r['window']['end'])
        self.assertEqual((end-start).total_seconds(),25*3600)

    def test_hospital_city_does_not_take_the_casualties(self):
        self.assertIsNone(locality('14-річного хлопчика доправили до обласної лікарні у Дніпрі.'))
        self.assertEqual(locality('До 12 зросла кількість поранених через атаку росіян на Синельникове.'),'Синельникове')
        r,t=prepare();city=paragraph(t,'Дніпро');syn=paragraph(t,'Синельникове')
        self.assertNotIn('12',city);self.assertNotIn('14-річ',city);self.assertNotIn('46-річ',city)
        for term in ['12','п’ятеро','Дві жінки','оперують','обласної лікарні Дніпра','близько 19-ї','п’ятиповерховий','магазин','автомобілі','ліквідовані','мобільний штаб']:
            self.assertIn(term,syn)
        other='У Павлограді пошкоджено будинок. Постраждалого доправили до лікарні у Дніпрі.'
        self.assertEqual([p for p,_ in split_places(other)],['Павлоград'])

    def test_child_clinical_states_and_differing_agency_assessments_remain(self):
        r,t=prepare();n=paragraph(t,'Нікопольщина');s=paragraph(t,'Синельниківський район')
        for fact in ['14-річного хлопчика','Його стан тяжкий','46-річний чоловік у тяжкому стані',
                     'троє чоловіків 45–58 років','За ОВА:','За поліцією:','середньої тяжкості',
                     'Усі госпіталізовані','металева огорожа','50-річний чоловік']:
            self.assertIn(fact,n)
        self.assertLess(n.index('четверо поранених'),n.index('Усі госпіталізовані'))
        for fact in ['11-річна дівчинка','амбулаторному лікуванні','П’ятеро поранених','важкому стані']:
            self.assertIn(fact,s)

    def test_actual_projection_not_source_pointer_is_the_coverage_proof(self):
        r,t=prepare()
        for fact in ['Його стан тяжкий.','14-річного хлопчика госпіталізували до обласної лікарні Дніпра.',
                     'Постраждали троє чоловіків 45–58 років.','Пошкоджені магазин і металева огорожа.']:
            self.assertIn(fact,t)
            self.assertIn('lost_source_claim',publication_issues(r,t.replace(fact,''),{}),fact)
        changed=t.replace('Синельникове:\n','Дніпро:\n')
        self.assertIn('lost_source_claim',publication_issues(r,changed,{}))

    def test_duplicate_overlap_disabled_for_second_episode_or_changed_child(self):
        from operational_prose import clinical_overlap
        r,_=prepare()
        records=copy.deepcopy(r['records'])
        self.assertTrue(clinical_overlap(records))
        ova=next(x for x in records if x['source_key']=='dnipropetrovskaODA/32824')
        ova['source_text']=ova['source_text'].replace('14-річного','15-річного')
        self.assertEqual(clinical_overlap(records),[])
        ova['source_text']=ova['source_text'].replace('15-річного','14-річного')+' Повторна атака.'
        self.assertEqual(clinical_overlap(records),[])

    def test_procedural_formula_cannot_hide_a_new_consequence(self):
        p='Правоохоронці документують наслідки обстрілу в межах кримінального провадження, відкритого за ч. 1 ст. 438 Кримінального кодексу України.'
        self.assertEqual(selected_text(p),'')
        self.assertIn('Врятовано 7 дітей.',selected_text(p+' Врятовано 7 дітей.'))
        self.assertIn('евакуйовано 8 людей',selected_text('Наслідки уточнюємо, евакуйовано 8 людей.'))

    def test_concise_unknown_facts_qualifiers_and_negations_survive(self):
        for s in ['Евакуйовано 31 мешканця.','Не пошкоджено кисневу станцію.',
                  'Близько 19-ї виявлено витік аміаку.','Понад 20 БпЛА збито.',
                  'Стан дитини погіршився, її евакуювали до Києва.']:
            self.assertEqual(concise(s),s)
        self.assertEqual(concise('Внаслідок влучання виникла пожежа у п’ятиповерховому будинку та в магазині.'),
                         'Горіли п’ятиповерховий будинок і магазин.')

    def test_bulletins_keep_their_separate_counts_and_scopes(self):
        r,t=prepare()
        self.assertIn('24 жовтня (станом на 18:30)',t)
        self.assertIn('25 жовтня (станом на 07:30)',t)
        self.assertIn('Понад 60 атак шести районів БпЛА й артилерією',t)
        self.assertIn('Понад 20 атак трьох районів',t)
        self.assertIn('Поранені 14 дорослих і дитина',t)
        self.assertIn('14 дістали поранень',paragraph(t,'Синельниківський район'))


if __name__=='__main__':unittest.main()
