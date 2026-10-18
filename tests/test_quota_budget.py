import io
import json
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from gemini_transport import RequestBudget, request_text
from quota_budget import UsageLedger


class UsageLedgerTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(redirect_stdout(io.StringIO()))
        folder = self.enterContext(TemporaryDirectory())
        self.path = Path(folder) / "gemini_usage.json"
        self.now = datetime(2026, 11, 5, 12, tzinfo=timezone.utc)

    def ledger(self, event="workflow_dispatch", model="model"):
        return UsageLedger(model, self.path, event, lambda: self.now)

    def fill(self, ledger, count):
        for _ in range(count):
            request_id = ledger.reserve("author")
            ledger.finish(request_id, "http_200")

    def test_previews_stop_at_eight(self):
        self.fill(self.ledger(), 8)
        with self.assertRaisesRegex(RuntimeError, "no API request"):
            self.ledger().reserve("author")

    def test_four_attempts_remain_for_scheduled_report(self):
        self.fill(self.ledger(), 8)
        self.fill(self.ledger("schedule"), 4)
        with self.assertRaisesRegex(RuntimeError, "12/12"):
            self.ledger("schedule").reserve("author")

    def test_scheduled_attempts_also_reduce_preview_allowance(self):
        self.fill(self.ledger("schedule"), 4)
        self.fill(self.ledger(), 4)
        with self.assertRaises(RuntimeError):
            self.ledger().reserve("author")

    def test_attempt_is_counted_before_response(self):
        self.ledger().reserve("author")
        state = json.loads(self.path.read_text())
        self.assertEqual(len(state["events"]), 1)
        self.assertEqual(state["events"][0]["outcome"], "reserved")

    def test_old_attempts_expire(self):
        self.fill(self.ledger(), 8)
        self.now += timedelta(hours=24, seconds=1)
        self.ledger().reserve("author")

    def test_new_day_alone_does_not_clear_rolling_budget(self):
        self.fill(self.ledger(), 8)
        self.now += timedelta(hours=13)
        with self.assertRaises(RuntimeError):
            self.ledger().reserve("author")

    def test_known_daily_cooldown_is_persisted(self):
        ledger = self.ledger()
        request_id = ledger.reserve("author")
        ledger.finish(request_id, "http_429", {"reason": "daily_quota", "retry_seconds": 3600})
        with self.assertRaisesRegex(RuntimeError, "cooldown"):
            self.ledger("schedule").reserve("author")
        self.now += timedelta(seconds=3602)
        self.ledger("schedule").reserve("author")

    def test_counter_is_model_specific(self):
        self.fill(self.ledger(), 8)
        self.ledger(model="other-model").reserve("author")

    def test_corrupt_ledger_does_not_reset_budget(self):
        self.path.write_text("broken")
        with self.assertRaisesRegex(RuntimeError, "unreadable"):
            self.ledger().reserve("author")

    @patch("gemini_transport.requests.post")
    def test_denied_preview_never_contacts_google(self, post):
        self.fill(self.ledger(), 8)
        with self.assertRaises(RuntimeError):
            request_text("endpoint", "secret", "prompt", RequestBudget(ledger=self.ledger()))
        post.assert_not_called()

    @patch("gemini_transport.requests.post")
    def test_success_records_stage_and_outcome(self, post):
        r = Mock(status_code=200)
        r.json.return_value = {"candidates": [{"content": {"parts": [{"text": "result"}]}}]}
        post.return_value = r
        request_text("endpoint", "secret", "prompt", RequestBudget(ledger=self.ledger(), stage="editor"))
        row = json.loads(self.path.read_text())["events"][0]
        self.assertEqual((row["stage"], row["outcome"]), ("editor", "http_200"))
        self.assertNotIn("secret", self.path.read_text())


if __name__ == "__main__":
    unittest.main()
