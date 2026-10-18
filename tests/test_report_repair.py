import os
import unittest
from unittest.mock import patch

from ai_report import build_repair_note, generate_gemini_report
from report_rules import source_problems
from test_ai_report import VALID_REPORT
from test_source_accuracy import source, report


class ReportRepairTests(unittest.TestCase):
    def test_repair_contains_failed_draft_and_concrete_instructions(self):
        note = build_repair_note("1.1. Понад 40 атак.", ValueError(
            "unsupported attack total; attack counts belong in section 2.1 with their source periods"))
        self.assertIn("1.1. Понад 40 атак.", note)
        self.assertIn("не складай", note)
        self.assertIn("У 1.1 повністю вилучи", note)
        self.assertIn("початковими джерелами", note)

    def test_missing_community_has_named_correction(self):
        note = build_repair_note("draft", ValueError("missing attack community: Покровській"))
        self.assertIn("поверни громаду", note)
        self.assertIn("Покровській", note)

    @patch.dict(os.environ, {"GEMINI_API_KEY": "test-key", "GITHUB_ACTIONS": "false"})
    @patch("ai_report._request_report")
    def test_second_author_request_edits_actual_failed_draft(self, request):
        wrong = VALID_REPORT.replace("1.1. Підтверджені повідомлення викладено нижче.",
                                     "1.1. Понад 40 атак.")
        request.side_effect = [wrong, VALID_REPORT, RuntimeError("API unavailable")]
        result = generate_gemini_report(
            [source("Понад 30 атак.")], "08:00 16.10.2026", "08:00 17.10.2026",
            "08:05 17.10.2026", "17.10.2026", [])
        self.assertEqual(result, VALID_REPORT.strip())
        second_prompt = request.call_args_list[1].args[2]
        self.assertIn("ВІДХИЛЕНА ЧЕРНЕТКА:", second_prompt)
        self.assertIn("1.1. Понад 40 атак.", second_prompt)
        self.assertEqual(request.call_count, 3)

    def posts(self):
        return [
            source("Троє людей дістали поранень. ▪️ На Нікопольщині "
                   "Марганецька громада. Троє людей дістали поранень."),
            source("В Українській громаді пошкоджений будинок."),
        ]

    def test_day_summary_not_assigned_to_preceding_community(self):
        text = report("На Нікопольщині, у Марганецькій громаді є пошкодження. "
                      "В Українській громаді пошкоджений будинок. "
                      "Загалом протягом дня троє людей дістали поранень.")
        self.assertFalse(source_problems(text, self.posts()))

    def test_direct_wrong_assignment_stays_rejected(self):
        text = report("У Марганецькій громаді є пошкодження. "
                      "В Українській громаді троє людей дістали поранень.")
        self.assertTrue(any("unsupported community: українськ" in e
                            for e in source_problems(text, self.posts())))

    def test_summary_does_not_hide_earlier_wrong_assignment(self):
        text = report("У Марганецькій громаді є пошкодження. "
                      "В Українській громаді троє людей дістали поранень. "
                      "Загалом протягом дня троє людей дістали поранень.")
        self.assertTrue(any("unsupported community: українськ" in e
                            for e in source_problems(text, self.posts())))

    def test_unsupported_global_count_still_rejected(self):
        text = report("У Марганецькій громаді є пошкодження. "
                      "В Українській громаді пошкоджений будинок. "
                      "Загалом протягом дня шестеро людей дістали поранень.")
        self.assertTrue(any("unsupported casualty count" in e
                            for e in source_problems(text, self.posts())))


if __name__ == "__main__":
    unittest.main()
