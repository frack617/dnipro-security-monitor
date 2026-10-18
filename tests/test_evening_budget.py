import io
import json
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from gemini_transport import RequestBudget, request_text
from quota_budget import UsageLedger, local_limits


class EveningBudgetTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(redirect_stdout(io.StringIO()))
        self.folder = self.enterContext(TemporaryDirectory())
        self.path = Path(self.folder) / "usage.json"
        self.now = datetime(2026, 10, 18, 7, 20, tzinfo=timezone.utc)

    def ledger(self, event="workflow_dispatch", model="gemini-2.5-flash-lite"):
        return UsageLedger(model, self.path, event, lambda: self.now)

    def fill(self, ledger, count):
        for _ in range(count):
            ledger.finish(ledger.reserve("author"), "http_200")

    def test_two_evening_attempts_then_four_morning_attempts(self):
        self.fill(self.ledger(), 8)
        self.now += timedelta(hours=8)
        self.fill(self.ledger(), 2)
        with self.assertRaisesRegex(RuntimeError, "10/10"):
            self.ledger().reserve("editor")
        self.now = datetime(2026, 10, 19, 5, 3, tzinfo=timezone.utc)
        self.fill(self.ledger("schedule"), 4)
        with self.assertRaisesRegex(RuntimeError, "14/14"):
            self.ledger("schedule").reserve("author")
        self.assertEqual(len(json.loads(self.path.read_text())["events"]), 14)

    def test_groq_and_unknown_models_keep_original_limits(self):
        self.assertEqual(local_limits("groq:openai/gpt-oss-120b"), (8, 12))
        self.assertEqual(local_limits("unknown"), (8, 12))

    @patch("gemini_transport.requests.post")
    def test_no_network_request_after_manual_ceiling(self, post):
        self.fill(self.ledger(), 10)
        with self.assertRaisesRegex(RuntimeError, "no API request"):
            request_text("endpoint", "key", "prompt", RequestBudget(ledger=self.ledger()))
        post.assert_not_called()

    def test_server_cooldown_still_blocks_extra_allowance(self):
        self.fill(self.ledger(), 8)
        ledger = self.ledger()
        request_id = ledger.reserve("author")
        ledger.finish(request_id, "http_429",
                      {"reason": "daily_quota", "retry_seconds": 3600})
        with self.assertRaisesRegex(RuntimeError, "cooldown"):
            self.ledger().reserve("author")

    def test_scheduled_usage_reduces_manual_allowance(self):
        self.fill(self.ledger("schedule"), 4)
        self.fill(self.ledger(), 6)
        with self.assertRaisesRegex(RuntimeError, "10/10"):
            self.ledger().reserve("author")


if __name__ == "__main__":
    unittest.main()
