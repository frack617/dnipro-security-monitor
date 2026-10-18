import unittest

from ai_report import enforce_report_frame, validate_report, build_prompt, build_review_prompt
from report_rules import source_problems
from test_ai_report import VALID_REPORT
from test_source_accuracy import source, report


class ReportQualityTests(unittest.TestCase):
    def notice(self, text, category):
        post = source(text, category)
        post["published_at"] = "2026-10-17T04:17:00+00:00"
        post["published_local"] = "17.10.2026 07:17"
        return post

    def test_restores_bare_main_headings_without_changing_facts(self):
        raw = VALID_REPORT.replace("1. Загальна ситуація в області:", "1.").replace("2. Події:", "2.")
        fixed = enforce_report_frame(raw, "08:00 16.10.2026", "08:00 17.10.2026",
                                    "08:05 17.10.2026")
        self.assertEqual(fixed, VALID_REPORT)
        validate_report(fixed, "17.10.2026")

    def test_validator_rejects_bare_headings_without_normalization(self):
        raw = VALID_REPORT.replace("2. Події:", "2.")
        with self.assertRaisesRegex(ValueError, "main heading"):
            validate_report(raw, "17.10.2026")

    def test_validator_rejects_duplicate_main_heading(self):
        raw = VALID_REPORT.replace("2. Події:", "2. Події:\n2. Події:")
        with self.assertRaisesRegex(ValueError, "main heading"):
            validate_report(raw, "17.10.2026")

    def test_responding_firefighters_are_not_injured_firefighters(self):
        post = source("У Дніпрі сталася пожежа. Пожежі ліквідовані.")
        text = report("У Дніпрі сталася пожежа, яку рятувальники ліквідували.")
        self.assertFalse(source_problems(text, [post]))

    def test_other_injured_people_do_not_make_responders_casualties(self):
        post = source("Троє людей поранені. Пожежу ліквідовано.")
        text = report("Поранені 3 людей, рятувальники ліквідували пожежу.")
        self.assertFalse(source_problems(text, [post]))

    def test_unsupported_injured_rescuer_still_rejected(self):
        for body in ("Рятувальник отримав поранення.", "Поранений рятувальник.",
                     "Серед постраждалих є рятувальник."):
            with self.subTest(body=body):
                self.assertIn("unsupported casualty/event detail: rescuer",
                              source_problems(report(body), [source("Пожежі ліквідовані.")]))

    def test_supported_injured_rescuer_accepted(self):
        body = "Рятувальник отримав поранення."
        self.assertFalse(source_problems(report(body), [source(body)]))

    def test_current_day_weather_not_shifted_before_cutoff(self):
        posts = [self.notice("Сьогодні впродовж дня прогнозуються дощ і гроза.", "1.4")]
        text = report("Нових атак не зафіксовано.",
                      "До кінця звітного періоду очікувалися дощ і гроза.")
        with self.assertRaisesRegex(ValueError, "weather moved before"):
            validate_report(text, "17.10.2026", posts=posts)

    def test_current_day_weather_can_remain_daytime_forecast(self):
        posts = [self.notice("Сьогодні впродовж дня прогнозуються дощ і гроза.", "1.4")]
        text = report("Нових атак не зафіксовано.", "На 17 жовтня прогнозуються дощ і гроза.")
        validate_report(text, "17.10.2026", posts=posts)

    def test_completed_night_weather_is_not_daytime_notice(self):
        posts = [self.notice("Сьогодні вночі прогнозувався туман.", "1.4")]
        text = report("Нових атак не зафіксовано.", "До кінця звітного періоду спостерігався туман.")
        validate_report(text, "17.10.2026", posts=posts)

    def test_current_transport_not_presented_as_completed(self):
        posts = [self.notice("Сьогодні діють зміни руху. Призупиняється рух трамваїв.", "1.2")]
        text = VALID_REPORT.replace(
            "1.2. У перевірених джерелах повідомлень за звітний період не виявлено.",
            "1.2. Рух трамваїв призупинявся, замінні автобуси працювали.")
        with self.assertRaisesRegex(ValueError, "transport restrictions shifted"):
            validate_report(text, "17.10.2026", posts=posts)

    def test_current_transport_has_current_status(self):
        posts = [self.notice("Сьогодні діють зміни руху. Призупиняється рух трамваїв.", "1.2")]
        text = VALID_REPORT.replace(
            "1.2. У перевірених джерелах повідомлень за звітний період не виявлено.",
            "1.2. Рух трамваїв призупинено, замінні автобуси працюють.")
        validate_report(text, "17.10.2026", posts=posts)

    def test_explicitly_ended_restrictions_allow_past_tense(self):
        posts = [self.notice("Сьогодні діють зміни руху. Пізніше рух відновлено.", "1.2")]
        text = VALID_REPORT.replace(
            "1.2. У перевірених джерелах повідомлень за звітний період не виявлено.",
            "1.2. Рух призупинявся, згодом рух відновлено.")
        validate_report(text, "17.10.2026", posts=posts)

    def test_separate_notice_of_restored_service_allows_past_tense(self):
        posts = [self.notice("Сьогодні діють зміни руху.", "1.2"),
                 self.notice("Сьогодні рух відновлено.", "1.2")]
        text = VALID_REPORT.replace(
            "1.2. У перевірених джерелах повідомлень за звітний період не виявлено.",
            "1.2. Рух призупинявся, згодом рух відновлено.")
        validate_report(text, "17.10.2026", posts=posts)

    def test_author_and_editor_receive_temporal_and_readability_rules(self):
        prompts = [build_prompt([], "start", "end", "checked", []),
                   build_review_prompt("draft", [], "start", "end")]
        for prompt in prompts:
            self.assertIn("анонс на поточний день", prompt)
            self.assertIn("чинні зміни руху", prompt)
            self.assertIn("не повторюй ту саму думку", prompt)


if __name__ == "__main__":
    unittest.main()
