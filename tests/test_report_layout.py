import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import collector as c
from ai_report import validate_report
from groq_report import render_groq_sections
from report_layout import PUBLIC_TITLES, EMPTY, TITLES, geographic_paragraphs, internal_sections, render_report, words, polish_body
from report_sections import recover_attack_section, recover_transport_section
from test_ai_report import VALID_REPORT


ARGS=('08:00 16.10.2026','08:00 17.10.2026','08:05 17.10.2026')


class ReportLayoutTests(unittest.TestCase):
    def test_requested_exact_five_points_and_titles(self):
        out=render_report(VALID_REPORT,*ARGS)
        self.assertTrue(out.startswith('Станом на 17.10.2026 08.00\n'))
        self.assertIn('1. ЗАГАЛЬНА СИТУАЦІЯ В ОБЛАСТІ (РАЙОНІ)',out)
        self.assertIn('2. ПОДІЇ У СФЕРІ БЕЗПЕКИ',out)
        self.assertNotIn('Доброго дня.',out)
        self.assertEqual(re.findall(r'(?m)^([12]\.[1-4])\.(?: |$)',out),list(PUBLIC_TITLES))
        for key,title in PUBLIC_TITLES.items():
            self.assertIn((key+'. '+title).rstrip()+'\n',out)
        self.assertNotIn('2.4.',out)
        self.assertNotIn('1.3.',out)

    def test_public_header_uses_cutoff_not_late_check_time(self):
        out=render_report(VALID_REPORT,ARGS[0],ARGS[1],'11:42 17.10.2026')
        self.assertTrue(out.startswith('Станом на 17.10.2026 08.00\n\n1.'))
        self.assertNotIn('11:42',out)
        self.assertNotIn('Звітний період:',out)

    def test_city_and_district_separated_without_reassignment(self):
        body='У Дніпрі пошкоджені будинки. У Дніпровському районі троє людей поранені.'
        out=geographic_paragraphs(body)
        self.assertIn('У Дніпрі пошкоджені будинки.',out)
        self.assertIn('У Дніпровському районі троє людей поранені.',out)
        self.assertEqual(words(out),words(body))

    def test_administrative_name_outside_small_known_city_list(self):
        body="У Кам'янському районі пошкоджений ангар."
        out=geographic_paragraphs(body)
        self.assertIn("У Кам'янському районі пошкоджений ангар.",out)
        self.assertEqual(words(out),words(body))

    def test_joint_place_list_is_not_given_a_single_place_heading(self):
        body='У Дніпрі та Павлограді пошкоджені будинки.'
        self.assertEqual(geographic_paragraphs(body),body)

    def test_community_and_explicit_parent_district_stay_in_one_heading(self):
        body='У Зайцівській громаді Синельниківського району сталася пожежа.'
        out=geographic_paragraphs(body)
        self.assertIn('У Зайцівській громаді Синельниківського району сталася пожежа.',out)
        self.assertEqual(words(out),words(body))

    def test_standalone_city_heading_gets_its_own_line(self):
        out=geographic_paragraphs('Дніпро. Попередньо: пошкоджені будинки.')
        self.assertEqual(out,'Дніпро:\nПопередньо: пошкоджені будинки.')

    def test_author_written_hierarchy_preserved_without_guessed_parent(self):
        body='Любимівська громада:\nПошкоджено будинок культури. Попередньо без поранених.'
        self.assertEqual(geographic_paragraphs(body),body)
        self.assertNotIn('район',geographic_paragraphs(body))

    def test_no_clock_or_weapon_added_to_unspecified_event(self):
        body='У Нікополі пошкоджений будинок.'
        out=geographic_paragraphs(body)
        self.assertNotRegex(out,r'\d{1,2}:\d{2}|Шахед|FPV')
        self.assertEqual(words(out),words(body))

    def test_empty_wording_is_not_changed_to_absence_of_events(self):
        out=render_report(VALID_REPORT,*ARGS)
        self.assertEqual(out.count('У перевірених джерелах повідомлень за звітний період не виявлено.'),4)
        self.assertNotIn('подій не зафіксовано',out)

    def test_fallback_warning_is_retained_in_same_layout(self):
        out=render_report('⚠️ Резервна автоматична версія\n\n'+VALID_REPORT,*ARGS)
        self.assertTrue(out.startswith('Станом на'))
        self.assertEqual(out.count('⚠️ Резервна автоматична версія'),1)

    def test_missing_duplicate_and_reordered_points_fail_closed(self):
        for text in (VALID_REPORT.replace('2.4. ','2.5. '),
                     VALID_REPORT+'\n2.1. Повтор.',
                     VALID_REPORT.replace('2.2. ','2.9. ').replace('2.3. ','2.2. ').replace('2.9. ','2.3. ')):
            with self.subTest(text=text[-50:]),self.assertRaises(ValueError):
                render_report(text,*ARGS)

    def test_final_format_cannot_invent_facts(self):
        with patch('report_layout.geographic_paragraphs',return_value='Вигадано 99 постраждалих.'):
            with self.assertRaisesRegex(ValueError,'changed facts'):
                render_report(VALID_REPORT,*ARGS)

    def test_real_recovered_report_keeps_every_section_token_in_order(self):
        f=json.loads((Path(__file__).parent/'fixtures/coverage_20261019.json').read_text())
        report=recover_attack_section(recover_transport_section(f['delivered_dry_report'],f['posts']),
                                      f['posts'],'19.10.2026')
        validate_report(report,'19.10.2026',posts=f['posts'])
        before=internal_sections(report)
        out=render_report(report,'08:00 18.10.2026','08:00 19.10.2026','14:25 19.10.2026')
        mapping={'1.1':'1.1','1.2':'1.1','1.3':'1.2','1.4':'1.1',
                 '2.1':'2.1','2.2':'2.2','2.3':'2.2','2.4':'2.3'}
        points=list(re.finditer(r'(?m)^([12]\.[1-3])\.(?: |$)',out))
        public={m[1]:out[m.end():points[i+1].start() if i+1<len(points) else len(out)]
                for i,m in enumerate(points)}
        for key,body in before.items():
            if body==EMPTY and key in ('1.2','1.4','2.3'):continue
            self.assertIn(' '.join(words(polish_body(body,key))), ' '.join(words(public[mapping[key]])),key)

    def test_supplemental_facts_are_preserved_under_correct_public_points(self):
        sections=internal_sections(VALID_REPORT)
        sections.update({'1.2':'Автобус №18 зупинено.', '1.3':'Оголошено контрольований вибух.',
                         '1.4':'Без води вулиця Сонячна.', '2.3':'Повідомили про мінування школи.',
                         '2.4':'Виявлено небезпечний боєприпас.'})
        canonical='\n'.join(k+'. '+v for k,v in sections.items())
        out=render_report(canonical,*ARGS)
        general=out.split('1.1.\n')[1].split('1.2. ')[0]
        self.assertIn('Автобус №18 зупинено.',general)
        self.assertIn('Без води вулиця Сонячна.',general)
        self.assertIn('Оголошено контрольований вибух.',out.split('1.2. ')[1].split('2. ПОДІЇ')[0])
        law=out.split('2.2. ')[1].split('2.3. ')[0]
        self.assertIn('Повідомлення про мінування:\nПовідомили про мінування школи.',law)
        self.assertIn('Зброя та правоохоронні операції:\n'+EMPTY,law)
        self.assertIn('Виявлено небезпечний боєприпас.',out.split('2.3. ')[1])

    def test_overview_district_count_does_not_become_daily_total(self):
        for count in ('чотири','трьох','5','семи'):
            with self.subTest(count=count):
                body='Протягом звітного періоду ворог атакував '+count+' райони області.'
                out=polish_body(body,'1.1')
                self.assertEqual(out,'Протягом звітного періоду ворог атакував райони області.')
                self.assertEqual(polish_body(body,'2.1'),body)

    def test_other_numbers_and_named_districts_survive_overview_cleanup(self):
        body='У Дніпровському районі пошкоджено 4 будинки. Постраждала 84-річна жінка.'
        self.assertEqual(polish_body(body,'1.1'),body)

    def test_typo_corrected_without_replacing_correct_words(self):
        self.assertEqual(polish_body('21 БпЛА збили упрожовж ночі.','2.1'),
                         '21 БпЛА збили упродовж ночі.')
        self.assertEqual(polish_body('Упродовж дня працювали служби.','2.1'),
                         'Упродовж дня працювали служби.')

    def test_update_context_and_uncertain_housing_counts_survive_polish(self):
        body='Попередньо: Можуть бути заблоковані люди. Пізніше: Один будинок зруйнований. Зведення: Ще три оселі зруйновані.'
        out=polish_body(body,'2.1')
        self.assertIn('Попередньо повідомлялося: Можуть бути заблоковані люди.',out)
        self.assertIn('Згодом повідомлено: Один будинок зруйнований.',out)
        self.assertIn('У зведенні зазначено: Ще три оселі зруйновані.',out)
        self.assertNotIn('чотири',out)
        self.assertNotIn('Попередньо:',out)
        self.assertEqual(polish_body(out,'2.1'),out)

    def test_full_publication_applies_cleanup_after_fact_validation(self):
        sections=internal_sections(VALID_REPORT)
        sections['1.1']='Протягом звітного періоду атаковано чотири райони області.'
        sections['2.1']='У Дніпрі пошкоджені будинки. У Дніпровському районі постраждала людина.'
        out=render_report('\n'.join(k+'. '+v for k,v in sections.items()),*ARGS)
        self.assertIn('атаковано райони області.',out)
        self.assertIn('У Дніпрі пошкоджені будинки.\n\nУ Дніпровському районі постраждала людина.',out)
        self.assertNotIn('У Дніпрі:\n',out)

    def test_groq_preserves_source_supported_geographic_line_breaks(self):
        sections=internal_sections(VALID_REPORT)
        sections['2.1']='Дніпро:\nПошкоджені будинки.\n\nНікопольщина:\nПостраждала людина.'
        out=render_groq_sections(json.dumps(sections,ensure_ascii=False),*ARGS)
        self.assertIn('Дніпро:\nПошкоджені будинки.',out)
        self.assertIn('\n\nНікопольщина:',out)


class PublicationLayoutTests(unittest.TestCase):
    def test_actual_publication_path_uses_layout_for_author_and_fallback(self):
        now=c.parse_datetime('2026-10-17T08:05:00+03:00')
        for fallback in (False,True):
            with self.subTest(fallback=fallback),tempfile.TemporaryDirectory() as d, \
                 patch.object(c,'MORNING_REPORT_FILE',Path(d)/'report.md'), \
                 patch.object(c,'read_alert_state',return_value={'last_daily_report':'2026-10-16'}), \
                 patch.dict(os.environ,{'FORCE_MORNING_REPORT':'false','SEND_MORNING_REPORT':'true'}), \
                 patch('ai_report.generate_report',side_effect=RuntimeError('offline test') if fallback else None,
                       return_value=VALID_REPORT),patch.object(c,'deliver_morning_report') as deliver:
                c.process_morning_report([],{},now)
                sent=deliver.call_args.args[0]
                self.assertTrue(sent.startswith('Станом на 17.10.2026 08.00'))
                self.assertEqual(Path(d,'report.md').read_text().strip(),sent)
                self.assertEqual('⚠️ Резервна автоматична версія' in sent,fallback)

    def test_pending_old_layout_resumes_without_reformatting_or_ai(self):
        now=c.parse_datetime('2026-10-17T08:05:00+03:00')
        state={'pending_daily_report':{'date':'2026-10-17','text':VALID_REPORT,'sent_parts':1}}
        with patch.object(c,'read_alert_state',return_value=state), \
             patch.dict(os.environ,{'FORCE_MORNING_REPORT':'false','SEND_MORNING_REPORT':'true'}), \
             patch('ai_report.generate_report') as generate,patch.object(c,'deliver_morning_report') as deliver:
            c.process_morning_report([],{},now)
            self.assertEqual(deliver.call_args.args[0],VALID_REPORT)
            generate.assert_not_called()


if __name__=='__main__':
    unittest.main()
