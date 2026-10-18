import re
import unittest

from ai_report import build_prompt, validate_report
from report_rules import source_problems
from test_ai_report import VALID_REPORT
from test_source_accuracy import report, source


class PromptStructureTests(unittest.TestCase):
    def test_literal_opening_contains_only_four_intro_lines(self):
        prompt = build_prompt([], "08:00 16.10.2026", "08:00 17.10.2026",
                              "10:32 17.10.2026", [])
        intro = prompt.split("Дослівно відтвори лише ці чотири вступні рядки:\n", 1)[1]
        intro = intro.split("Після вступу", 1)[0]
        self.assertEqual(len([line for line in intro.splitlines() if line.strip()]), 4)
        self.assertNotRegex(intro, r"(?m)^\d+\.")
        self.assertNotRegex(prompt, r"(?m)^[12]\.[1-4]\.\s")
        self.assertIn("Не друкуй зміст", prompt)

    def test_checklist_comes_only_from_attack_posts(self):
        prompt = build_prompt([
            source("На Нікопольщині Марганецька та Покровська громади."),
            source("Новини про Зеленодольську громаду.", "1.4"),
        ], "start", "end", "checked", [])
        checklist = prompt.split("(відмінок можна змінювати): ", 1)[1].split("\n", 1)[0]
        self.assertIn("Марганецька", checklist)
        self.assertIn("Покровська", checklist)
        self.assertNotIn("Зеленодольську", checklist)

    def test_duplicate_outline_rejected_before_misleading_fact_errors(self):
        outline = "\n".join(f"{s}. Категорія." for s in (
            "1.1", "1.2", "1.3", "1.4", "2.1", "2.2", "2.3", "2.4"))
        duplicate = VALID_REPORT.replace("1.1.", outline + "\n1.1.", 1)
        posts = [source("Любимівська громада. Пошкоджено будинок культури.")]
        with self.assertRaises(ValueError) as caught:
            validate_report(duplicate, "17.10.2026", posts=posts)
        self.assertIn("duplicate section 2.1.", str(caught.exception))
        self.assertNotIn("missing attack community", str(caught.exception))
        self.assertEqual(len(source_problems(duplicate, posts)), 1)

    def test_missing_number_remains_rejected(self):
        with self.assertRaisesRegex(ValueError, "missing section 2.4."):
            validate_report(VALID_REPORT.replace("2.4.", "2.5."), "17.10.2026")

    def test_correct_structure_still_checks_missing_communities(self):
        posts = [source("Марганецька та Покровська громади.")]
        errors = source_problems(report("На Нікопольщині пошкоджено будинки."), posts)
        self.assertEqual(sum("missing attack community" in e for e in errors), 2)

    def test_invented_total_still_rejected(self):
        posts = [source("Вдень понад 30 атак."), source("Уночі понад 10 атак.")]
        self.assertIn("unsupported attack total",
                      source_problems(report("За добу понад 40 атак."), posts))


if __name__ == "__main__":
    unittest.main()
