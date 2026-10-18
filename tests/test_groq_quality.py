import io
import json
import os
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from ai_report import enforce_report_frame, validate_report
from groq_report import build_compact_prompt, correction_prompt, generate_groq_report, _request_groq, save_debug
from test_ai_report import VALID_REPORT
from test_groq_report import ARGS, json_sections
from test_source_accuracy import source, report


class GroqQualityTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(redirect_stdout(io.StringIO()))
        self.enterContext(patch.dict(os.environ, {"GROQ_API_KEY": "groq-secret", "GITHUB_ACTIONS": "false"}))

    def frame(self, text):
        return enforce_report_frame(text, *ARGS[1:4])

    def test_missing_final_dots_normalized_without_changing_content(self):
        raw = VALID_REPORT
        for group in (1, 2):
            for item in range(1, 5):
                raw = raw.replace(f"{group}.{item}. ", f"{group}.{item} ")
        self.assertEqual(self.frame(raw), VALID_REPORT)
        validate_report(self.frame(raw), "17.10.2026")

    def test_mixed_punctuation_normalized(self):
        self.assertEqual(self.frame(VALID_REPORT.replace("2.1. ", "2.1 ")), VALID_REPORT)

    def test_normalization_never_hides_duplicate_or_missing_points(self):
        raw = VALID_REPORT.replace("2.1. ", "2.1 Duplicate.\n2.1 ")
        with self.assertRaises(ValueError):
            validate_report(self.frame(raw), "17.10.2026")
        raw = VALID_REPORT.replace("2.4.", "2.5.")
        with self.assertRaises(ValueError):
            validate_report(self.frame(raw), "17.10.2026")

    def test_groq_prompt_receives_communities_counts_and_current_notice_rules(self):
        posts = [source("Вдень понад 30 разів атакував три райони. Покровська громада.")]
        prompt = build_compact_prompt(posts, "start", "end", [])
        self.assertIn("Покровська", prompt)
        self.assertIn("[30]", prompt)
        self.assertIn("Current transport restrictions stay current", prompt)
        self.assertIn("weather warnings valid after 08:00", prompt)

    def test_correction_uses_specific_actions_and_previous_json_when_it_fits(self):
        raw = '{"1.1":"wrong"}'
        prompt = correction_prompt([], "start", "end", [], raw,
                                   ValueError("missing attack community: Покровській"))
        self.assertIn("поверни громаду", prompt)
        self.assertIn("Покровській", prompt)
        self.assertIn(raw, prompt)

    def test_large_previous_draft_omitted_without_cutting_source_facts(self):
        fact = "У Любимівській громаді пошкоджено будинок культури."
        prompt = correction_prompt([source(fact)], "start", "end", [],
                                   "x" * 20000, ValueError("unsupported attack total"))
        self.assertIn(fact, prompt)
        self.assertNotIn("x" * 20000, prompt)
        self.assertIn("не складай", prompt)

    @patch("groq_report.time.sleep")
    @patch("groq_report._request_groq")
    def test_saves_rejected_and_corrected_drafts(self, request, sleep):
        request.side_effect = [json_sections(report("Четверо людей госпіталізовані.")),
                               json_sections(report("Троє людей госпіталізовані."))]
        with TemporaryDirectory() as folder, \
             patch("groq_report.__file__", str(Path(folder) / "groq_report.py")), \
             patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}):
            generate_groq_report([source("Троє людей поранені.")], *ARGS[1:])
            data = json.loads((Path(folder) / "data" / "groq_debug.json").read_text())
        self.assertEqual([r["validation"] for r in data["attempts"]], ["rejected", "passed"])
        self.assertIn("Четверо", data["attempts"][0]["raw_text"])
        self.assertIn("Троє", data["attempts"][1]["rendered_text"])
        self.assertIn("Correct the rejected JSON", request.call_args.args[0])
        self.assertIn("Четверо людей", request.call_args.args[0])
        sleep.assert_called_once_with(60)

    @patch("groq_report.requests.post")
    def test_debug_excludes_reasoning_and_redacts_key(self, post):
        r = Mock(status_code=200)
        r.json.return_value = {
            "choices": [{"message": {"content": "text groq-secret", "reasoning": "private thought"},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13}}
        post.return_value = r
        record = {}
        _request_groq("prompt", "groq-secret", "model", None, record)
        with TemporaryDirectory() as folder:
            path = Path(folder) / "debug.json"
            save_debug(path, {"attempts": [record]}, "groq-secret")
            saved = path.read_text()
        self.assertNotIn("groq-secret", saved)
        self.assertNotIn("private thought", saved)
        self.assertEqual(record["usage"]["total_tokens"], 13)

    @patch("groq_report.requests.post")
    def test_truncated_response_retained_for_diagnosis_and_rejected(self, post):
        post.return_value = Mock(status_code=200)
        post.return_value.json.return_value = {"choices": [
            {"message": {"content": "partial"}, "finish_reason": "length"}]}
        record = {}
        with self.assertRaisesRegex(RuntimeError, "truncated"):
            _request_groq("prompt", "secret", "model", None, record)
        self.assertEqual(record["raw_text"], "partial")
        self.assertEqual(record["finish_reason"], "length")

    def test_debug_write_failure_does_not_break_report(self):
        with patch("groq_report.Path.mkdir", side_effect=OSError):
            save_debug(Path("/not-writable/debug.json"), {"attempts": []}, "secret")


if __name__ == "__main__":
    unittest.main()
