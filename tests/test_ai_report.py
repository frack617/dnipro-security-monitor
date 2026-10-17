import unittest

from ai_report import (
    enforce_report_frame,
    normalize_completed_morning_forecast,
    sanitize_fallback,
    validate_report,
)


VALID_REPORT = """Доброго дня.

Звіт по Дніпропетровській області станом на 08:00 17.10.2026.
Звітний період: з 08:00 16.10.2026 до 08:00 17.10.2026, за Києвом.
Фактичний час автоматичної перевірки: 08:05 17.10.2026.

1. Загальна ситуація в області:
1.1. Підтверджені повідомлення викладено нижче. Рекомендується стежити за сигналами тривоги та мати заряджені засоби зв’язку.
1.2. У перевірених джерелах повідомлень за звітний період не виявлено.
1.3. У перевірених джерелах повідомлень за звітний період не виявлено.
1.4. У перевірених джерелах повідомлень за звітний період не виявлено.

2. Події:
2.1. У перевірених джерелах повідомлень за звітний період не виявлено.
2.2. У перевірених джерелах повідомлень за звітний період не виявлено.
2.3. У перевірених джерелах повідомлень за звітний період не виявлено.
2.4. У перевірених джерелах повідомлень за звітний період не виявлено.

Це огляд станом на 08:00 17.10.2026. Для негайних дій слід стежити за офіційними сповіщеннями про повітряну тривогу.
"""


class ReportValidationTests(unittest.TestCase):
    def test_valid_report(self):
        self.assertEqual(validate_report(VALID_REPORT, "17.10.2026"), VALID_REPORT.strip())

    def test_rejects_source_link(self):
        with self.assertRaises(ValueError):
            validate_report(VALID_REPORT + "\nhttps://t.me/example/1", "17.10.2026")

    def test_rejects_missing_section(self):
        with self.assertRaises(ValueError):
            validate_report(VALID_REPORT.replace("2.4. ", ""), "17.10.2026")

    def test_rejects_city_and_suburb_conflation(self):
        report = VALID_REPORT.replace(
            "1.1. Підтверджені повідомлення викладено нижче.",
            "1.1. У Дніпрі та передмісті зафіксовано наслідки атаки.",
        )
        with self.assertRaises(ValueError):
            validate_report(report, "17.10.2026")

    def test_rejects_city_claimed_to_be_suburb(self):
        report = VALID_REPORT.replace(
            "1.1. Підтверджені повідомлення викладено нижче.",
            "1.1. У Дніпрі під ударом було передмістя.",
        )
        with self.assertRaises(ValueError):
            validate_report(report, "17.10.2026")

    def test_rejects_vague_attack_placeholder(self):
        report = VALID_REPORT.replace(
            "2.1. У перевірених джерелах повідомлень за звітний період не виявлено.",
            "2.1. У Дніпрі також були атаковані об'єкти.",
        )
        with self.assertRaises(ValueError):
            validate_report(report, "17.10.2026")

    def test_rejects_past_morning_forecast_in_future_tense(self):
        report = VALID_REPORT.replace(
            "1.4. У перевірених джерелах повідомлень за звітний період не виявлено.",
            "1.4. Вночі та зранку 17 жовтня прогнозується туман.",
        )
        with self.assertRaises(ValueError):
            validate_report(report, "17.10.2026")

    def test_rejects_weather_duplicated_in_overview_and_practical_section(self):
        report = VALID_REPORT.replace(
            "1.1. Підтверджені повідомлення викладено нижче.",
            "1.1. Підтверджені повідомлення викладено нижче. В області спостерігався туман.",
        ).replace(
            "1.4. У перевірених джерелах повідомлень за звітний період не виявлено.",
            "1.4. Вночі та зранку спостерігався туман з обмеженою видимістю.",
        )
        with self.assertRaisesRegex(ValueError, "weather duplicated"):
            validate_report(report, "17.10.2026")

    def test_prompt_requires_linked_casualties_to_be_one_episode(self):
        from ai_report import build_prompt, build_review_prompt

        prompt = build_prompt([], "08:00 16.10.2026", "08:00 17.10.2026", "08:05 17.10.2026", [])
        review = build_review_prompt("Чернетка", [], "08:00 16.10.2026", "08:00 17.10.2026")
        self.assertIn("підтверджену загибель і поранених", prompt)
        self.assertIn("підтверджену загибель, попередню кількість поранених", review)

    def test_prompt_keeps_secondary_weather_out_of_overview(self):
        from ai_report import build_prompt

        prompt = build_prompt([], "08:00 16.10.2026", "08:00 17.10.2026", "08:05 17.10.2026", [])
        self.assertIn("другорядні погодні фактори подавай лише у 1.4", prompt)

    def test_prompt_requires_fact_based_practical_guidance(self):
        from ai_report import build_prompt

        prompt = build_prompt([], "08:00 16.10.2026", "08:00 17.10.2026", "08:05 17.10.2026", [])
        self.assertIn("пряме практичне значення для гуманітарних місій", prompt)
        self.assertIn("Не вигадуй", prompt)

    def test_normalizes_completed_morning_forecast_tense(self):
        report = VALID_REPORT.replace(
            "1.4. У перевірених джерелах повідомлень за звітний період не виявлено.",
            "1.4. Вночі та зранку 17 жовтня прогнозується туман.",
        )
        normalized = normalize_completed_morning_forecast(report, "17.10.2026")
        self.assertIn("17 жовтня прогнозувався туман", normalized)
        self.assertEqual(validate_report(normalized, "17.10.2026"), normalized.strip())

    def test_enforces_fixed_report_frame(self):
        altered = VALID_REPORT.replace(
            "Звітний період: з 08:00 16.10.2026 до 08:00 17.10.2026, за Києвом.\n"
            "Фактичний час автоматичної перевірки: 08:05 17.10.2026.\n\n",
            "Звітний період без часового поясу.\n\n",
        )
        normalized = enforce_report_frame(
            altered,
            "08:00 16.10.2026",
            "08:00 17.10.2026",
            "08:05 17.10.2026",
        )
        self.assertIn(", за Києвом.", normalized)
        self.assertIn("Фактичний час автоматичної перевірки: 08:05", normalized)
        self.assertEqual(validate_report(normalized, "17.10.2026"), normalized.strip())

    def test_fallback_hides_channel_and_link(self):
        source = "• 16.10 12:00 · @example: Факт\nhttps://t.me/example/1"
        result = sanitize_fallback(source)
        self.assertNotIn("@example", result)
        self.assertNotIn("https://", result)


if __name__ == "__main__":
    unittest.main()
