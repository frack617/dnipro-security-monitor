import unittest

from ai_report import build_prompt, build_repair_note
from report_rules import required_attack_counts, source_problems
from test_source_accuracy import source, report


class CompletenessTests(unittest.TestCase):
    def bulletin(self, text, at):
        post = source(text)
        post["published_at"] = at
        post["published_local"] = ""
        return post

    def posts(self):
        return [
            self.bulletin("Упродовж дня понад 30 разів ворог атакував чотири райони.",
                          "2026-10-17T15:30:00+00:00"),
            self.bulletin("Понад 10 разів ворог атакував три райони.",
                          "2026-10-18T04:30:00+00:00"),
        ]

    def test_rejects_removal_of_both_independent_counts(self):
        errors = source_problems(report("Ворог атакував область."), self.posts())
        self.assertIn("missing source attack counts in section 2.1: 10, 30", errors)

    def test_rejects_removal_of_one_count(self):
        errors = source_problems(report("Уночі понад 10 атак."), self.posts())
        self.assertIn("missing source attack counts in section 2.1: 30", errors)

    def test_accepts_separate_counts_without_inventing_sum(self):
        self.assertFalse(source_problems(
            report("Вдень понад 30 атак на чотири райони. Уночі понад 10 атак на три райони."),
            self.posts()))

    def test_does_not_force_old_number_from_updated_same_period(self):
        posts = [
            self.bulletin("Протягом дня понад 20 разів атакував три райони.",
                          "2026-10-17T12:00:00+00:00"),
            self.bulletin("Протягом дня понад 30 разів атакував три райони.",
                          "2026-10-17T16:00:00+00:00"),
        ]
        self.assertEqual(required_attack_counts(posts), {30})

    def test_keeps_explicit_day_and_night_on_same_publication_date(self):
        posts = [
            self.bulletin("Вночі понад 10 разів атакував три райони.",
                          "2026-10-17T04:00:00+00:00"),
            self.bulletin("Вдень понад 30 разів атакував три райони.",
                          "2026-10-17T16:00:00+00:00"),
        ]
        self.assertEqual(required_attack_counts(posts), {10, 30})

    def test_single_event_count_not_treated_as_oblast_bulletin(self):
        self.assertEqual(required_attack_counts([source("По будинку вдарили 2 рази.")]), set())

    def test_rejects_lost_critical_object_despite_generic_infrastructure(self):
        post = source("Атакували об’єкт критичної інфраструктури у Дніпрі.")
        errors = source_problems(report("У Дніпрі пошкоджена інфраструктура."), [post])
        self.assertIn("missing specific attack consequence: critical infrastructure", errors)

    def test_accepts_critical_object_with_location(self):
        post = source("Атакували об’єкт критичної інфраструктури у Дніпрі.")
        self.assertFalse(source_problems(
            report("У Дніпрі атаковано об’єкт критичної інфраструктури."), [post]))

    def test_missing_fact_feedback_requests_restoration(self):
        note = build_repair_note("draft", ValueError(
            "missing source attack counts in section 2.1: 10, 30; "
            "missing specific attack consequence: critical infrastructure"))
        self.assertIn("не складай і не видаляй", note)
        self.assertIn("10, 30", note)
        self.assertIn("критичної інфраструктури", note)

    def test_prompt_reminds_model_to_keep_counts(self):
        prompt = build_prompt(self.posts(), "start", "end", "checked", [])
        self.assertIn("Контрольні числові показники з актуальних зведень: 10, 30", prompt)


if __name__ == "__main__":
    unittest.main()
