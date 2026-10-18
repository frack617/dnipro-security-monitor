import unittest

from ai_report import validate_report
from groq_report import compact_evidence, build_compact_prompt
from report_rules import source_problems
from test_ai_report import VALID_REPORT
from test_source_accuracy import source, report


class LocationGroundingTests(unittest.TestCase):
    def posts(self):
        return [source("У Любимівській громаді пошкоджений будинок культури. Попередньо загиблих та поранених немає."),
                source("Троє людей дістали поранень. ▪️ У Любимівській громаді пошкоджено будинок культури. ▪️ На Нікопольщині атакували Марганецьку та Покровську громади. Троє людей дістали поранень.")]

    def test_rejects_supported_number_assigned_to_wrong_community(self):
        text = report("У Любимівській громаді пошкоджено будинок культури; 3 особи отримали поранення. У Марганецькій та Покровській громадах троє людей дістали поранень.")
        self.assertTrue(any("unsupported community: любимівськ" in e for e in source_problems(text, self.posts())))

    def test_does_not_assign_opening_total_to_first_community(self):
        posts = [source("Троє людей поранені. ▪️ У Зеленодольській громаді пошкоджений будинок. ▪️ У Грушівській громаді троє людей поранені.")]
        errors = source_problems(report("У Зеленодольській громаді троє людей поранені. У Грушівській громаді є пошкодження."), posts)
        self.assertTrue(any("unsupported community: зеленодольськ" in e for e in errors))

    def test_accepts_correctly_scoped_casualties(self):
        text = report("У Любимівській громаді пошкоджено будинок культури, попередньо без загиблих та поранених. У Марганецькій та Покровській громадах троє людей дістали поранень.")
        self.assertFalse(source_problems(text, self.posts()))

    def test_later_positive_update_can_replace_initial_no_casualties(self):
        posts = [source("У Любимівській громаді загиблих та поранених немає."),
                 source("У Любимівській громаді троє людей поранені.")]
        self.assertFalse(source_problems(report("У Любимівській громаді троє людей поранені."), posts))

    def test_opening_total_can_belong_to_only_hospitalization_paragraph(self):
        posts = [source("Троє людей поранені. ▪️ У Дніпрі пошкоджені автівки. ▪️ У Синельниківському районі атакували Шахтарську та Петропавлівську громади. До лікарні доправили чоловіка 44 років та жінок 75 і 90 років. ▪️ У Червоногригорівській громаді є пошкодження.")]
        text = report("У Шахтарській та Петропавлівській громадах троє людей госпіталізовані. У Червоногригорівській громаді є пошкодження.")
        self.assertFalse(source_problems(text, posts))

    def test_source_paragraph_boundaries_are_preserved(self):
        post = source("Троє людей поранені. ▪️ У Любимівській громаді пошкоджений будинок. ▪️ У Покровській громаді поранені троє людей.")
        text = compact_evidence([post])[0]["text"]
        self.assertIn("\n\nУ Любимівській", text)
        self.assertIn("\n\nУ Покровській", text)

    def test_prompt_has_no_english_numbered_caption_template(self):
        prompt = build_compact_prompt([], "start", "end", [])
        self.assertNotIn("1.1. general security overview", prompt)
        self.assertIn("no English labels", prompt)

    def test_rejects_english_captions(self):
        text = VALID_REPORT.replace("1.2. У перевірених", "1.2. road closures and transport route changes\nУ перевірених")
        with self.assertRaisesRegex(ValueError, "non-Ukrainian"):
            validate_report(text, "17.10.2026")

    def test_rejects_english_caption_flattened_into_ukrainian_paragraph(self):
        text = VALID_REPORT.replace("1.2. У перевірених", "1.2. road closures and transport route changes У перевірених")
        with self.assertRaisesRegex(ValueError, "non-Ukrainian"):
            validate_report(text, "17.10.2026")

    def test_rejects_text_outside_numbered_sections(self):
        text = VALID_REPORT.replace("2. Події:\n", "2. Події:\nПовідомлень не виявлено.\n")
        with self.assertRaisesRegex(ValueError, "outside numbered"):
            validate_report(text, "17.10.2026")

    def test_rejects_false_empty_overview(self):
        text = VALID_REPORT.replace("1.1. Підтверджені повідомлення викладено нижче.", "1.1. У перевірених джерелах повідомлень за звітний період не виявлено.")
        with self.assertRaisesRegex(ValueError, "overview denies"):
            validate_report(text, "17.10.2026", posts=[source("Ворог атакував область.")])

    def test_rejects_yesterdays_power_schedule_in_present_tense(self):
        text = report("Відомостей про атаки немає.", "На 16 жовтня з 17:00 до 22:00 діє графік ГПВ ЦЕК.")
        with self.assertRaisesRegex(ValueError, "expired power schedule"):
            validate_report(text, "17.10.2026")

    def test_accepts_yesterdays_power_schedule_in_past_tense(self):
        text = report("Відомостей про атаки немає.", "На 16 жовтня діяв графік ГПВ ЦЕК.")
        self.assertEqual(validate_report(text, "17.10.2026"), text.strip())


if __name__ == "__main__":
    unittest.main()
