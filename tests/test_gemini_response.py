import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

from gemini_transport import RequestBudget, extract_response, request_text


class GeminiResponseTests(unittest.TestCase):
    def body(self, reason="STOP"):
        return {"candidates": [{"finishReason": reason, "content": {"parts": [
            {"text": "private thought", "thought": True},
            {"text": "1.1. Початок\n"},
            {"thoughtSignature": "private signature"},
            {"text": "1.2. Продовження"},
        ]}}], "usageMetadata": {"promptTokenCount": 120, "candidatesTokenCount": 30,
                               "totalTokenCount": 150, "thoughtsTokenCount": 5}}

    def test_joins_all_final_text_and_omits_thoughts(self):
        text, meta = extract_response(self.body())
        self.assertEqual(text, "1.1. Початок\n1.2. Продовження")
        self.assertEqual(meta["text_part_count"], 2)
        self.assertEqual(meta["usage"]["totalTokenCount"], 150)
        self.assertNotIn("private", json.dumps(meta))

    def test_does_not_merge_alternative_candidates(self):
        body = self.body()
        body["candidates"].append({"content": {"parts": [{"text": "alternative"}]}})
        self.assertNotIn("alternative", extract_response(body)[0])

    @patch("gemini_transport.requests.post")
    def test_records_draft_validation_usage_and_redacts_key(self, post):
        body = self.body()
        body["candidates"][0]["content"]["parts"].append({"text": " secret-value"})
        post.return_value = Mock(status_code=200)
        post.return_value.json.return_value = body
        with tempfile.TemporaryDirectory() as folder, redirect_stdout(io.StringIO()) as log:
            path = Path(folder) / "debug.json"
            budget = RequestBudget(debug_path=path)
            text = request_text("endpoint", "secret-value", "prompt", budget)
            budget.validation(text, ValueError("section missing"))
            saved = path.read_text()
            record = json.loads(saved)["attempts"][0]
            self.assertEqual(record["validation"], "rejected")
            self.assertEqual(record["validation_error"], "section missing")
            self.assertEqual(record["usage"]["totalTokenCount"], 150)
            self.assertNotIn("private", saved)
            self.assertNotIn("secret-value", saved)
            self.assertNotIn("Початок", log.getvalue())
            budget.validation(text)
            self.assertEqual(json.loads(path.read_text())["attempts"][0]["validation"], "passed")

    @patch("gemini_transport.requests.post")
    def test_truncated_response_is_saved_and_rejected(self, post):
        post.return_value = Mock(status_code=200)
        post.return_value.json.return_value = self.body("MAX_TOKENS")
        with tempfile.TemporaryDirectory() as folder, redirect_stdout(io.StringIO()):
            path = Path(folder) / "debug.json"
            with self.assertRaisesRegex(RuntimeError, "MAX_TOKENS"):
                request_text("endpoint", "key", "prompt", RequestBudget(debug_path=path))
            self.assertIn("Початок", json.loads(path.read_text())["attempts"][0]["text"])
        self.assertEqual(post.call_count, 1)

    @patch("gemini_transport.requests.post")
    def test_blocked_response_is_saved_without_raw_feedback(self, post):
        post.return_value = Mock(status_code=200)
        post.return_value.json.return_value = {"promptFeedback": {
            "blockReason": "SAFETY", "private": "not persisted"}}
        with tempfile.TemporaryDirectory() as folder, redirect_stdout(io.StringIO()):
            path = Path(folder) / "debug.json"
            with self.assertRaisesRegex(RuntimeError, "no usable text"):
                request_text("endpoint", "key", "prompt", RequestBudget(debug_path=path))
            record = json.loads(path.read_text())["attempts"][0]
            self.assertEqual(record["block_reason"], "SAFETY")
            self.assertNotIn("private", str(record))

    def test_write_failure_does_not_discard_response(self):
        with patch("gemini_transport.Path.mkdir", side_effect=OSError), redirect_stdout(io.StringIO()):
            RequestBudget(debug_path="/unwritable/debug.json").save_debug()


if __name__ == "__main__":
    unittest.main()
