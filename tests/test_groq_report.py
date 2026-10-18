import io
import os
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock, patch

import collector
from ai_report import generate_report
from groq_report import _request_groq, build_compact_prompt, clean_source_text, compact_evidence, generate_groq_report
from test_ai_report import VALID_REPORT
from test_source_accuracy import report, source


ARGS = ([], "08:00 16.10.2026", "08:00 17.10.2026", "08:05 17.10.2026", "17.10.2026", [])


class GroqIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(redirect_stdout(io.StringIO()))

    @patch.dict(os.environ, {"REPORT_PROVIDER": "groq"})
    @patch("ai_report.generate_gemini_report")
    @patch("groq_report.generate_groq_report", return_value=VALID_REPORT)
    def test_explicit_groq_never_calls_gemini(self, groq, gemini):
        self.assertEqual(generate_report(*ARGS), VALID_REPORT)
        groq.assert_called_once()
        gemini.assert_not_called()

    @patch.dict(os.environ, {"REPORT_PROVIDER": "auto", "GROQ_API_KEY": "test"})
    @patch("ai_report.generate_gemini_report", side_effect=RuntimeError("Gemini daily quota"))
    @patch("groq_report.generate_groq_report", return_value=VALID_REPORT)
    def test_auto_uses_independent_fallback(self, groq, gemini):
        self.assertEqual(generate_report(*ARGS), VALID_REPORT)
        groq.assert_called_once()

    @patch.dict(os.environ, {"REPORT_PROVIDER": "auto", "GROQ_API_KEY": "test"})
    @patch("ai_report.generate_gemini_report", return_value=VALID_REPORT)
    @patch("groq_report.generate_groq_report")
    def test_valid_gemini_report_does_not_consume_groq_quota(self, groq, gemini):
        self.assertEqual(generate_report(*ARGS), VALID_REPORT)
        groq.assert_not_called()

    @patch.dict(os.environ, {"REPORT_PROVIDER": "gemini", "GROQ_API_KEY": "test"})
    @patch("ai_report.generate_gemini_report", side_effect=RuntimeError("Gemini unavailable"))
    @patch("groq_report.generate_groq_report")
    def test_explicit_gemini_does_not_switch_providers(self, groq, gemini):
        with self.assertRaises(RuntimeError):
            generate_report(*ARGS)
        groq.assert_not_called()

    def test_schedule_compaction_preserves_all_attack_text(self):
        attack = source("У Любимівській громаді пошкоджено будинок культури. " + "Наслідки. " * 100)
        old = source("Зміни ГПВ ЦЕК. Черга 1.2 10:00-12:00.", "1.4")
        old["published_at"] = "2026-11-05T07:00:00+00:00"
        new = source("Зміни ГПВ ЦЕК. Черга 1.2 17:00-20:00.", "1.4")
        evidence = compact_evidence([old, attack, new])
        self.assertEqual(len(evidence), 2)
        self.assertEqual(evidence[0]["text"], clean_source_text(attack["text"]))
        self.assertIn("17:00-20:00", str(evidence))
        self.assertNotIn("10:00-12:00", str(evidence))

    def test_distinct_operators_are_preserved(self):
        posts = [source("ГПВ ЦЕК. Черга 1.2.", "1.4"), source("ГПВ ДТЕК. Черга 1.2.", "1.4")]
        self.assertEqual(len(compact_evidence(posts)), 2)

    def test_cleaning_removes_links_and_social_footer_not_facts(self):
        cleaned = clean_source_text("Троє людей поранені.\n🆘\nСайт\nFb\nhttps://t.me/test/1\n#hashtag")
        self.assertEqual(cleaned, "Троє людей поранені.")

    @patch("groq_report.requests.post")
    def test_http_request_uses_supported_gpt_oss_fields(self, post):
        r = Mock(status_code=200)
        r.json.return_value = {"choices": [{"message": {"content": "Довідка"}, "finish_reason": "stop"}], "usage": {"total_tokens": 100}}
        post.return_value = r
        self.assertEqual(_request_groq("prompt", "secret", "openai/gpt-oss-120b", None), "Довідка")
        payload = post.call_args.kwargs["json"]
        self.assertFalse(payload["include_reasoning"])
        self.assertNotIn("reasoning_format", payload)

    @patch("groq_report.requests.post")
    def test_oversized_input_is_not_silently_truncated(self, post):
        with self.assertRaisesRegex(RuntimeError, "facts were not truncated"):
            _request_groq("А" * 20000, "secret", "model", None)
        post.assert_not_called()

    @patch("groq_report.requests.post")
    def test_truncated_output_is_rejected(self, post):
        r = Mock(status_code=200)
        r.json.return_value = {"choices": [{"message": {"content": "partial"}, "finish_reason": "length"}]}
        post.return_value = r
        with self.assertRaisesRegex(RuntimeError, "truncated"):
            _request_groq("prompt", "secret", "model", None)

    @patch.dict(os.environ, {"GROQ_API_KEY": "test"})
    @patch("groq_report._request_groq", return_value=VALID_REPORT)
    def test_groq_result_passes_existing_validation(self, request):
        self.assertEqual(generate_groq_report(*ARGS), VALID_REPORT.strip())

    @patch.dict(os.environ, {"GROQ_API_KEY": "test"})
    @patch("groq_report.time.sleep")
    @patch("groq_report._request_groq")
    def test_incorrect_casualties_are_corrected_once_after_pause(self, request, sleep):
        request.side_effect = [report("Четверо людей госпіталізовані."), report("Троє людей госпіталізовані.")]
        args = ([source("Троє людей дістали поранень.")],) + ARGS[1:]
        result = generate_groq_report(*args)
        self.assertIn("Троє людей", result)
        self.assertEqual(request.call_count, 2)
        sleep.assert_called_once_with(60)

    def test_app_announcement_is_not_attack(self):
        self.assertIsNone(collector.classify_post({"text": "Під час повітряних атак доступна карта орієнтовного руху ракет."}))

    def test_current_week_summary_is_not_a_daily_event(self):
        from datetime import datetime
        p = source("Понад 800 виїздів на обстріли від початку цього тижня.")
        self.assertTrue(collector.is_historical_context(p, datetime(2026, 11, 5, 8, tzinfo=collector.KYIV)))


if __name__ == "__main__":
    unittest.main()
