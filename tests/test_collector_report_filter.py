import unittest
from datetime import datetime

import collector


class ReportFilterTests(unittest.TestCase):
    def test_old_explicit_event_date_is_historical(self):
        post = {
            "published_at": "2026-10-16T07:51:00+00:00",
            "text": "15 жовтня ворог поцілив по громаді.",
        }
        start = datetime(2026, 10, 16, 8, 0, tzinfo=collector.KYIV)
        self.assertTrue(collector.is_historical_context(post, start))

    def test_current_explicit_event_date_is_not_historical(self):
        post = {
            "published_at": "2026-10-17T04:30:00+00:00",
            "text": "17 жовтня зафіксовано наслідки атаки.",
        }
        start = datetime(2026, 10, 16, 8, 0, tzinfo=collector.KYIV)
        self.assertFalse(collector.is_historical_context(post, start))

    def test_drone_warhead_is_uxo(self):
        post = {"text": "Виявили та вилучили бойову частину безпілотника."}
        self.assertEqual(collector.classify_post(post), "2.4")

    def test_unrelated_murder_is_not_weapon_event(self):
        post = {"text": "Поліцейські затримали підозрюваного у вбивстві жінки."}
        self.assertIsNone(collector.classify_post(post))

    def test_drug_case_with_general_weapon_reminder_is_not_weapon_event(self):
        post = {
            "text": (
                "Поліцейські викрили групу наркозбувачів та вилучили наркотики. "
                "Поліція також нагадує про процедуру декларування зброї."
            )
        }
        self.assertIsNone(collector.classify_post(post))

    def test_reconstruction_story_is_not_current_attack(self):
        post = {
            "text": (
                "У місті триває відновлення житлового будинку, який постраждав "
                "внаслідок ворожого обстрілу кілька місяців тому."
            )
        }
        self.assertIsNone(collector.classify_post(post))

    def test_official_visit_is_not_security_event(self):
        post = {
            "text": "До міста з візитом прибула посадовиця та обговорила співпрацю."
        }
        self.assertIsNone(collector.classify_post(post))

    def test_fallback_fact_line_has_no_channel_or_link(self):
        post = {
            "published_at": "2026-10-17T04:30:00+00:00",
            "channel": "example",
            "url": "https://t.me/example/1",
            "text": "Підтверджений факт.",
        }
        result = collector.fact_line(post)
        self.assertEqual(result, "• Підтверджений факт.")
        self.assertNotIn("@example", result)
        self.assertNotIn("https://", result)


if __name__ == "__main__":
    unittest.main()
