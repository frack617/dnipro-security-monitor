import json
import unittest
from datetime import date
from pathlib import Path

import collector
from ai_report import normalize_completed_morning_forecast, validate_report
from fallback_report import build_sections, clean_event, weather_expired, weather_text
from report_rules import downed_drone_counts, house_counts, required_downed_counts, source_problems
from test_source_accuracy import report, source

FIXTURE=json.loads((Path(__file__).parent/'fixtures'/'transport_20261019.json').read_text())


def post(text, at='2026-10-18T18:53:00+00:00', category='1.4'):
    return dict(source(text,category),published_at=at,
                published_local=collector.parse_datetime(at).astimezone(collector.KYIV).strftime('%d.%m.%Y %H:%M'))


class FallbackQualityTests(unittest.TestCase):
    def test_real_fallback_preserves_all_critical_facts_without_visit_or_navigation(self):
        text=collector.build_morning_report(FIXTURE['posts'],{},collector.parse_datetime('2026-10-19T05:49:00Z'))
        for fact in ('критичної інфраструктури','Грушівській','Миколаївській','Раївській',
                     'Червоногригорівська','Зайцівській','84-річна','21 ворожий БпЛА',
                     'один будинок зруйнований','Ще три оселі зруйновані','заблоковані люди',
                     'За зведенням 18 жовтня','08:00 19 жовтня','понад 20','прогнозувалися'):
            self.assertIn(fact.lower(),text.lower())
        for bad in ('Виїхав','Поспілкувався','Дякую','єВідновлення','Деталі —','https://','#russia','•'):
            self.assertNotIn(bad,text)
        self.assertFalse(source_problems(text,FIXTURE['posts']))
        validate_report(text,'19.10.2026',posts=FIXTURE['posts'])

    def test_visit_removal_keeps_the_only_location_and_concrete_damage(self):
        text=clean_event(post('Виїхав на місце атаки на Павлоград. Поспілкувався з людьми. '
                             'Один приватний будинок зруйнований. Дякую рятувальникам.',category='2.1'))
        self.assertIn('Павлоград',text);self.assertIn('Один приватний будинок зруйнований',text)
        self.assertNotIn('Виїхав',text);self.assertNotIn('Дякую',text)

    def test_implicit_opening_one_is_not_repeated_with_the_same_woman(self):
        text=clean_event(post('Дніпропетровщина\n19 жовтня\n8:00\nПостраждала людина. '
            'Понад 20 разів атаковано три райони. ▪ У Дніпрі госпіталізована 84-річна жінка.',category='2.1'))
        self.assertNotIn('Постраждала людина.',text)
        self.assertIn('19 жовтня',text);self.assertIn('84-річна',text)

    def test_unrepeated_header_count_is_never_removed(self):
        text=clean_event(post('Дніпропетровщина\n18 жовтня\n18:30\nТроє людей поранені. '
            'Понад 20 разів атаковано три райони. ▪ У громаді пошкоджені будинки.',category='2.1'))
        self.assertIn('Троє людей поранені',text)

    def test_generic_service_status_and_real_casualties_are_not_cut(self):
        text=clean_event(post('У Дніпрі пошкоджений будинок. '*30+
            'До лікарні доправили 3 особи. На місці працюють служби.',category='2.1'))
        self.assertIn('3 особи',text);self.assertIn('працюють служби',text)
        self.assertNotIn('…',text)

    def test_narrative_cleanup_cannot_remove_a_unique_casualty_count(self):
        text=clean_event(post('Виїхав до Дніпра, де троє людей поранені.',category='2.1'))
        self.assertIn('троє людей поранені',text)

    def test_exact_same_day_duplicates_removed_but_next_day_is_retained(self):
        first=post('У Дніпрі пошкоджені приватні будинки.','2026-10-18T09:00:00Z','2.1')
        duplicate=dict(first,channel='other')
        next_day=dict(first,published_at='2026-10-19T04:00:00Z')
        self.assertEqual(len(collector.dedupe_posts([first,duplicate,next_day])),2)
        text=build_sections({'2.1':[first,duplicate,next_day]},date(2026,10,19))['2.1']
        self.assertEqual(text.count('У Дніпрі'),2)

    def test_transport_notices_are_separate_and_keep_full_routes(self):
        items=[p for p in FIXTURE['posts'] if p['category_hint']=='1.2']
        text=build_sections({'1.2':items},date(2026,10,19))['1.2']
        self.assertIn('Окремо:',text);self.assertIn('Січеславська Набережна',text)
        self.assertNotIn('Усі інші маршрути',text)

    def test_empty_section_is_unchanged(self):
        self.assertEqual(build_sections({'2.2':[]},date(2026,10,19))['2.2'],
                         'У перевірених джерелах повідомлень за звітний період не виявлено.')


class NumericGroundingTests(unittest.TestCase):
    def test_downed_drone_word_orders_and_declensions(self):
        for text in ('21 ворожий БпЛА збили наші сили ППО.',
                     'Сили ППО збили у небі над областю 21 ворожий БпЛА.',
                     'Було знищено 21 ударний безпілотник.',
                     '21 БпЛА було збито.', 'Знищено три дрони.'):
            with self.subTest(text=text):
                self.assertEqual(downed_drone_counts(text),{3} if 'три' in text else {21})

    def test_launched_drones_and_downing_drones_are_not_the_same_metric(self):
        self.assertEqual(downed_drone_counts('Ворог запустив 40 БпЛА, ППО збила 21 ворожий БпЛА.'),{21})
        errors=source_problems(report('ППО збила 40 БпЛА.'),[source('Ворог запустив 40 БпЛА, ППО збила 21 БпЛА.')])
        self.assertIn('unsupported downed drone count',errors)
        self.assertEqual(downed_drone_counts('ППО знищила три склади, ворог запустив 21 БпЛА.'),set())

    def test_changed_real_downing_count_is_rejected(self):
        errors=source_problems(report('ППО збила 99 БпЛА.'),[source('21 ворожий БпЛА збили сили ППО.')])
        self.assertIn('unsupported downed drone count',errors)
        self.assertIn('missing confirmed downed drone count',errors)

    def test_latest_comparable_downing_update_not_both_counts_required(self):
        posts=[post('За ніч ППО збила 19 БпЛА.','2026-10-19T03:00:00Z','2.1'),
               post('За ніч ППО збила 21 БпЛА.','2026-10-19T04:00:00Z','2.1')]
        self.assertEqual(required_downed_counts(posts),{21})
        self.assertFalse(source_problems(report('За ніч ППО збила 21 БпЛА.'),posts))

    def test_unsupported_sum_of_downed_drones_is_rejected(self):
        posts=[source('Вдень ППО збила 10 БпЛА.'),source('Уночі ППО збила 21 БпЛА.')]
        self.assertIn('unsupported downed drone count',source_problems(report('ППО збила 31 БпЛА.'),posts))

    def test_housing_types_and_ellipsis(self):
        self.assertEqual(house_counts('Один будинок зруйнований, ще щонайменше три пошкоджені. Ще три оселі зруйновані.'),
                         {'destroyed':{1,3},'damaged':{3}})
        self.assertEqual(house_counts('Пошкоджено 8 приватних будинків.'),{'destroyed':set(),'damaged':{8}})

    def test_damage_count_cannot_become_destruction_count(self):
        errors=source_problems(report('Зруйновано 8 приватних будинків.'),[source('Пошкоджено 8 приватних будинків.')])
        self.assertIn('unsupported housing count: destroyed',errors)

    def test_no_own_housing_sum_from_additive_update(self):
        posts=[source('Один будинок зруйнований.'),source('Ще три оселі зруйновані.')]
        self.assertIn('unsupported housing count: destroyed',source_problems(report('Зруйновано 4 приватні будинки.'),posts))

    def test_ages_drone_counts_and_attack_counts_do_not_become_house_counts(self):
        self.assertEqual(house_counts('Госпіталізована 84-річна жінка. ППО збила 21 БпЛА. Понад 20 атак.'),
                         {'destroyed':set(),'damaged':set()})

    def test_implicit_single_person_supports_explicit_one(self):
        self.assertFalse(source_problems(report('Одна людина поранена.'),[source('Постраждала людина.')]))


class WeatherValidityTests(unittest.TestCase):
    end=date(2026,10,19)

    def test_real_finished_warning_keeps_dates_and_has_past_tense(self):
        item=next(p for p in FIXTURE['posts'] if p['category_hint']=='1.4')
        self.assertTrue(weather_expired(item,self.end))
        text=weather_text(item,self.end)
        self.assertIn('18 жовтня',text);self.assertIn('19 жовтня',text)
        self.assertIn('прогнозувалися',text);self.assertNotIn('прогнозуються',text)
        self.assertNotIn('найближчу годину 18',text)

    def test_current_day_warning_keeps_future_validity(self):
        item=post('Сьогодні впродовж дня прогнозуються дощ і гроза.','2026-10-19T04:00:00Z')
        self.assertFalse(weather_expired(item,self.end))
        self.assertIn('прогнозуються',weather_text(item,self.end))
        self.assertIn('19 жовтня',weather_text(item,self.end))

    def test_current_night_warning_is_expired_at_cutoff(self):
        item=post('Сьогодні вночі прогнозується туман.','2026-10-19T01:00:00Z')
        self.assertTrue(weather_expired(item,self.end))
        self.assertIn('прогнозувався',weather_text(item,self.end))

    def test_tomorrow_becomes_an_explicit_date_not_tomorrow_relative_to_report(self):
        item=post('Завтра впродовж дня прогнозуються дощ і гроза.')
        self.assertIn('19 жовтня',weather_text(item,self.end))
        self.assertNotIn('Завтра',weather_text(item,self.end))
        self.assertFalse(weather_expired(item,self.end))

    def test_year_boundary_for_night_warning(self):
        item=post('31 грудня та вночі 1 січня прогнозуються складні погодні умови.', '2026-12-31T18:00:00Z')
        self.assertTrue(weather_expired(item,date(2027,1,1)))

    def test_missing_validity_is_not_guessed(self):
        item=post('Прогнозується гроза.')
        self.assertIsNone(weather_expired(item,self.end))

    def test_ai_weather_uses_the_single_dated_source_and_preserves_other_sections(self):
        raw=FIXTURE['debug']['attempts'][-1]['validated_text']
        normalized=normalize_completed_morning_forecast(raw,'19.10.2026',FIXTURE['posts'])
        self.assertIn('Попередження від 18 жовтня',normalized)
        self.assertEqual(raw.split('2. Події:')[1],normalized.split('2. Події:')[1])

    def test_other_service_facts_are_never_removed_by_weather_normalization(self):
        raw=report('Атак немає.','Гроза. Діють відключення світла.')
        items=[post('19 жовтня вдень прогнозується гроза.'),source('Діють відключення світла.','1.4')]
        self.assertEqual(normalize_completed_morning_forecast(raw,'19.10.2026',items),raw)


if __name__=='__main__':unittest.main()
