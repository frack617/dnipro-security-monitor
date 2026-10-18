import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import collector
from ai_report import generate_report, validate_report
from report_rules import casualty_counts, source_problems
from test_ai_report import VALID_REPORT


def source(text, category="2.1"):
    return {"text": text, "category_hint": category, "channel": "adm_dp",
            "published_at": "2026-11-05T16:00:00+00:00",
            "published_local": "05.11.2026 18:00 за Києвом", "url": "https://t.me/adm_dp/1"}


def report(body, services=None):
    text = VALID_REPORT.replace(
        "2.1. У перевірених джерелах повідомлень за звітний період не виявлено.", "2.1. " + body)
    if services:
        text = text.replace(
            "1.4. У перевірених джерелах повідомлень за звітний період не виявлено.", "1.4. " + services)
    return text


class HistoricalFilterTests(unittest.TestCase):
    start = datetime(2026, 11, 5, 8, tzinfo=collector.KYIV)

    def old(self, text):
        return collector.is_historical_context(source(text), self.start)

    def test_numeric_week_range(self):
        self.assertTrue(self.old("Огляд 28.10 – 04.11.2026. На Дніпропетровщині шестеро постраждалих."))

    def test_numeric_single_date(self):
        self.assertTrue(self.old("04.11.2026 внаслідок атаки пошкоджено будинок."))

    def test_current_numeric_date(self):
        self.assertFalse(self.old("05.11.2026 троє людей дістали поранень."))

    def test_power_queue_is_not_a_date(self):
        self.assertFalse(self.old("Зміни ГПВ: черга 1.2, черга 6.1 з 17:00 до 20:30."))

    def test_old_relative_evacuation(self):
        self.assertTrue(self.old("Декілька тижнів тому поліцейські евакуювали родини."))

    def test_previous_month(self):
        self.assertTrue(self.old("Минулого місяця ворог атакував громаду."))

    def test_yesterday_outside_window(self):
        self.assertTrue(self.old("Напередодні ворог атакував енергетичні об’єкти."))

    def test_yesterday_inside_window(self):
        p = source("Учора ворог атакував громаду.")
        p["published_at"] = "2026-11-06T04:30:00+00:00"
        self.assertFalse(collector.is_historical_context(p, self.start))

    def test_weekly_overview_without_dates(self):
        self.assertTrue(self.old("Головні події тижня. Шестеро постраждалих."))

    def test_new_attack_remains(self):
        self.assertFalse(self.old("Сьогодні вночі ворог атакував громаду."))

    def test_new_classifications(self):
        for text, expected in (
            ("Ворог завдав ударів по Любимівській громаді.", "2.1"),
            ("Зміни ГПВ на 5 листопада.", "1.4"),
            ("Графіки відключення світла повертаються.", "1.4"),
            ("В області дощ, гроза, жовтий рівень небезпечності.", "1.4"),
        ):
            with self.subTest(text=text):
                self.assertEqual(collector.classify_post({"text": text}), expected)


class SourceAccuracyTests(unittest.TestCase):
    def test_casualties_do_not_include_ages_or_house_counts(self):
        self.assertEqual(casualty_counts(
            "Троє людей дістали поранень. Пошкоджено 8 будинків. Госпіталізовано 3 людей віком 44, 75 та 90 років."), {3})

    def test_rejects_wrong_hospital_count(self):
        p = source("Троє людей дістали поранень. До лікарні доправили чоловіка та двох жінок.")
        with self.assertRaisesRegex(ValueError, "unsupported casualty count"):
            validate_report(report("Четверо людей доправлені до лікарні."), "17.10.2026", posts=[p])

    def test_accepts_correct_hospital_count(self):
        p = source("Троє людей дістали поранень.")
        self.assertFalse(source_problems(report("Трьох людей госпіталізували."), [p]))

    def test_rejects_invented_day_total(self):
        posts = [source("Вдень троє людей дістали поранень."), source("Уночі троє людей постраждали.")]
        errors = source_problems(report("Загалом за добу шестеро постраждалих."), posts)
        self.assertTrue(any("casualty total" in e for e in errors))

    def test_rejects_invented_attack_sum(self):
        posts = [source("Понад 30 разів ворог атакував область."), source("Понад 10 разів ворог атакував область.")]
        self.assertIn("unsupported attack total", source_problems(report("За добу понад 40 атак."), posts))

    def test_accepts_separate_attack_periods(self):
        posts = [source("Вдень понад 30 разів ворог атакував область."), source("Уночі понад 10 разів ворог атакував область.")]
        self.assertFalse(source_problems(report("Вдень понад 30 атак. Уночі понад 10 атак."), posts))

    def test_rejects_lost_community_and_consequence(self):
        p = source("Ворог атакував Любимівську громаду. Пошкоджено будинок культури.")
        errors = source_problems(report("У Дніпровському районі пошкоджена інфраструктура."), [p])
        self.assertTrue(any("missing attack community" in e for e in errors))
        self.assertTrue(any("missing specific attack consequence" in e for e in errors))

    def test_accepts_inflected_community(self):
        p = source("Ворог атакував Любимівську громаду. Пошкоджено будинок культури.")
        self.assertFalse(source_problems(report("У Любимівській громаді пошкоджений будинок культури."), [p]))

    def test_checks_community_list(self):
        p = source("Потерпали Зеленодольська та Грушівська громади.")
        errors = source_problems(report("У Зеленодольській громаді є пошкодження."), [p])
        self.assertTrue(any("Грушівська" in e for e in errors))

    def test_rejects_missing_power_and_weather(self):
        posts = [source("Зміни ГПВ.", "1.4"), source("Дощ та гроза, жовтий рівень небезпечності.", "1.4")]
        errors = source_problems(report("Відомостей про нові атаки немає."), posts)
        self.assertEqual(len([e for e in errors if "missing service fact" in e]), 2)

    def test_accepts_power_and_weather_summary(self):
        posts = [source("Зміни ГПВ.", "1.4"), source("Дощ та гроза, жовтий рівень небезпечності.", "1.4")]
        self.assertFalse(source_problems(report("Відомостей про нові атаки немає.",
            "Напередодні діяли відключення світла. На сьогодні оголошено жовтий рівень небезпечності через грозу."), posts))

    @patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"})
    @patch("ai_report._request_report")
    def test_invalid_count_retries_then_uses_only_verified_draft(self, request):
        posts = [source("Троє людей дістали поранень.")]
        wrong = report("Четверо людей доправлені до лікарні.")
        correct = report("Троє людей доправлені до лікарні.")
        request.side_effect = [wrong, correct, RuntimeError("Gemini HTTP 429")]
        result = generate_report(posts, "08:00 16.10.2026", "08:00 17.10.2026", "08:05 17.10.2026", "17.10.2026", [])
        self.assertIn("Троє людей", result)
        self.assertEqual(request.call_count, 3)

    def test_late_recovery_keeps_completed_window(self):
        checked = datetime(2026, 11, 6, 11, tzinfo=timezone.utc)
        start, end, _, _ = collector.completed_report_window(checked)
        self.assertEqual((start.day, start.hour, end.day, end.hour), (5, 8, 6, 8))

    def test_already_sent_date_does_not_generate_again(self):
        with patch.object(collector, "read_alert_state", return_value={"last_daily_report": "2026-11-06"}), \
             patch.object(collector, "build_morning_report") as build, \
             patch.dict(os.environ, {"FORCE_MORNING_REPORT": "false"}):
            collector.process_morning_report([], {}, datetime(2026, 11, 6, 12, tzinfo=timezone.utc))
            build.assert_not_called()


if __name__ == "__main__":
    unittest.main()
