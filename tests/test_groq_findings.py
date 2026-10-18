import unittest

from ai_report import validate_report, build_repair_note
from report_rules import source_problems, explicit_casualty_totals
from test_source_accuracy import source, report


class GroqFindingTests(unittest.TestCase):
    def test_overall_total_wording_from_actual_groq_draft_is_rejected(self):
        posts = [source("Вдень троє людей поранені."), source("Уночі троє людей поранені.")]
        text = report("Вдень поранено 3 особи. Уночі поранено 3 особи. "
                      "Усього у зазначених епізодах поранено 3 особи.")
        self.assertIn("casualty total not explicitly supported by source", source_problems(text, posts))

    def test_explicit_source_total_remains_allowed(self):
        text = "Усього за добу поранено 3 особи."
        self.assertFalse(source_problems(report(text), [source(text)]))

    def test_totals_parser_handles_count_before_and_after_casualty_verb(self):
        self.assertEqual(explicit_casualty_totals("Загалом за добу троє людей дістали поранень."), {3})
        self.assertEqual(explicit_casualty_totals("Усього у зазначених епізодах поранено 3 особи."), {3})

    def test_two_dates_in_same_sentence_do_not_hide_expired_schedule(self):
        text = report("Нових атак немає.",
                      "16 жовтня діє графік відключень; 17 жовтня прогнозуються дощі.")
        with self.assertRaisesRegex(ValueError, "expired power schedule"):
            validate_report(text, "17.10.2026")

    def test_current_date_present_tense_does_not_change_previous_past_tense(self):
        text = report("Нових атак немає.",
                      "16 жовтня діяв графік відключень, а 17 жовтня діють нові обмеження.")
        validate_report(text, "17.10.2026")

    def test_current_date_before_old_date_does_not_hide_expired_schedule(self):
        text = report("Нових атак немає.",
                      "17 жовтня прогнозуються дощі, а 16 жовтня діє графік відключень.")
        with self.assertRaisesRegex(ValueError, "expired power schedule"):
            validate_report(text, "17.10.2026")

    def test_critical_object_night_label_needs_source_support(self):
        posts = [source("У Дніпрі атаковано об’єкт критичної інфраструктури.")]
        text = report("16 жовтня, ніч: у Дніпрі атаковано об’єкт критичної інфраструктури.")
        self.assertIn("unsupported incident period: critical infrastructure", source_problems(text, posts))

    def test_critical_object_without_invented_period_passes(self):
        posts = [source("У Дніпрі атаковано об’єкт критичної інфраструктури.")]
        text = report("У Дніпрі атаковано об’єкт критичної інфраструктури.")
        self.assertFalse(source_problems(text, posts))

    def test_city_abbreviation_does_not_hide_invented_night_label(self):
        posts = [source("У Дніпрі атаковано об’єкт критичної інфраструктури.")]
        text = report("16 жовтня, ніч: в м. Дніпро атаковано об’єкт критичної інфраструктури.")
        self.assertIn("unsupported incident period: critical infrastructure", source_problems(text, posts))

    def test_queue_number_clause_cannot_hide_expired_schedule(self):
        text = report("Нових атак немає.",
                      "16 жовтня з 17:00 діє черга 1.1‑2.2; 17 жовтня прогнозуються дощі.")
        with self.assertRaisesRegex(ValueError, "expired power schedule"):
            validate_report(text, "17.10.2026")

    def test_future_incident_date_rejected(self):
        with self.assertRaisesRegex(ValueError, "incident date outside report window"):
            validate_report(report("19 жовтня атаковано Дніпро."), "17.10.2026")

    def test_previous_and_report_day_dates_allowed(self):
        validate_report(report("16 жовтня атаковано Дніпро. У ніч на 17 жовтня були удари."),
                        "17.10.2026")

    def test_bulletin_header_clock_is_not_attack_time(self):
        posts = [source("Дніпропетровщина\n16 жовтня\n18:30\nВорог атакував область.")]
        errors = source_problems(report("16 жовтня о 18:30 ворог атакував область."), posts)
        self.assertIn("publication clock used as incident time: 18:30", errors)

    def test_explicit_source_incident_clock_allowed(self):
        posts = [source("О 16:30 ворог атакував область.")]
        self.assertFalse(source_problems(report("16 жовтня о 16:30 ворог атакував область."), posts))

    def test_explicitly_reported_night_attack_is_allowed(self):
        posts = [source("Вночі у Дніпрі атаковано об’єкт критичної інфраструктури.")]
        text = report("16 жовтня, ніч: у Дніпрі атаковано об’єкт критичної інфраструктури.")
        self.assertFalse(source_problems(text, posts))

    def test_new_errors_have_actionable_feedback(self):
        note = build_repair_note("draft", ValueError(
            "casualty total not explicitly supported by source; "
            "expired power schedule presented as current; "
            "unsupported incident period: critical infrastructure"))
        self.assertIn("Збережи окремо кожну підтверджену групу", note)
        self.assertIn("Учорашні обмеження", note)
        self.assertIn("за часом публікації", note)


if __name__ == "__main__":
    unittest.main()
