import io
import json
import os
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from ai_report import generate_gemini_report, generate_report
from quota_budget import UsageLedger, local_limits
from test_ai_report import VALID_REPORT


ARGS = ([], "08:00 16.10.2026", "08:00 17.10.2026",
        "08:05 17.10.2026", "17.10.2026", [])


class BackupGeminiTests(unittest.TestCase):
    def setUp(self):
        self.log = self.enterContext(redirect_stdout(io.StringIO()))
        self.enterContext(patch.dict(os.environ, {
            "REPORT_PROVIDER": "auto", "GEMINI_API_KEY": "primary-test",
            "GEMINI_BACKUP_API_KEY": "backup-test", "GROQ_API_KEY": "groq-test",
            "GITHUB_ACTIONS": "false",
        }))

    @patch("ai_report.generate_gemini_report", return_value=VALID_REPORT)
    @patch("ai_report.generate_backup_gemini_report")
    @patch("groq_report.generate_groq_report")
    def test_primary_success_never_uses_backups(self, groq, backup, primary):
        self.assertEqual(generate_report(*ARGS), VALID_REPORT)
        backup.assert_not_called()
        groq.assert_not_called()

    @patch("ai_report.generate_gemini_report", side_effect=RuntimeError("primary blocked"))
    @patch("ai_report.generate_backup_gemini_report", return_value=VALID_REPORT)
    @patch("groq_report.generate_groq_report")
    def test_backup_precedes_groq(self, groq, backup, primary):
        self.assertEqual(generate_report(*ARGS), VALID_REPORT)
        backup.assert_called_once_with(*ARGS)
        groq.assert_not_called()

    @patch("ai_report.generate_gemini_report", side_effect=RuntimeError("primary blocked"))
    @patch("ai_report.generate_backup_gemini_report", side_effect=RuntimeError("backup blocked"))
    @patch("groq_report.generate_groq_report", return_value=VALID_REPORT)
    def test_both_gemini_fail_then_groq(self, groq, backup, primary):
        self.assertEqual(generate_report(*ARGS), VALID_REPORT)
        groq.assert_called_once()

    @patch("ai_report.generate_gemini_report")
    @patch("ai_report.generate_backup_gemini_report", return_value=VALID_REPORT)
    @patch("groq_report.generate_groq_report")
    def test_explicit_backup_never_uses_primary_or_groq(self, groq, backup, primary):
        with patch.dict(os.environ, {"REPORT_PROVIDER": "gemini_backup"}):
            self.assertEqual(generate_report(*ARGS), VALID_REPORT)
        primary.assert_not_called()
        groq.assert_not_called()

    @patch("ai_report.generate_gemini_report", side_effect=RuntimeError("primary blocked"))
    @patch("ai_report.generate_backup_gemini_report")
    def test_explicit_primary_never_switches_to_backup(self, backup, primary):
        with patch.dict(os.environ, {"REPORT_PROVIDER": "gemini"}):
            with self.assertRaisesRegex(RuntimeError, "primary blocked"):
                generate_report(*ARGS)
        backup.assert_not_called()

    @patch("ai_report._request_report")
    def test_duplicate_key_rejected_before_network(self, request):
        with patch.dict(os.environ, {"GEMINI_BACKUP_API_KEY": "primary-test"}):
            with self.assertRaisesRegex(RuntimeError, "duplicates primary"):
                generate_gemini_report(*ARGS, backup=True)
        request.assert_not_called()

    @patch("ai_report._request_report")
    def test_missing_backup_key_does_not_call_api(self, request):
        with patch.dict(os.environ, {"GEMINI_BACKUP_API_KEY": ""}):
            with self.assertRaisesRegex(RuntimeError, "not configured"):
                generate_gemini_report(*ARGS, backup=True)
        request.assert_not_called()

    @patch("ai_report._request_report", return_value=VALID_REPORT)
    def test_backup_passes_own_key_and_same_validation(self, request):
        self.assertEqual(generate_gemini_report(*ARGS, backup=True), VALID_REPORT.strip())
        self.assertEqual(request.call_count, 2)
        self.assertTrue(all(call.args[1] == "backup-test" for call in request.call_args_list))
        self.assertIn("gemini-3.5-flash-lite", request.call_args.args[0])
        self.assertNotIn("backup-test", self.log.getvalue())

    @patch("ai_report._request_report", return_value="invalid report")
    def test_invalid_backup_never_bypasses_content_checks(self, request):
        with self.assertRaisesRegex(RuntimeError, "failed validation"):
            generate_gemini_report(*ARGS, backup=True)
        self.assertEqual(request.call_count, 2)

    def test_primary_and_backup_have_separate_ledgers_and_reserves(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "usage.json"
            clock = lambda: datetime(2026, 10, 18, 16, tzinfo=timezone.utc)
            primary = UsageLedger("gemini-2.5-flash-lite", path, "workflow_dispatch", clock)
            backup = UsageLedger("gemini_backup:gemini-2.5-flash-lite", path, "workflow_dispatch", clock)
            for _ in range(10):
                primary.reserve("author")
            backup.reserve("author")
            self.assertEqual(len(json.loads(path.read_text())["events"]), 11)
            self.assertEqual(local_limits(backup.model), (8, 12))

    @patch("ai_report._request_report", return_value=VALID_REPORT)
    def test_backup_debug_and_usage_namespace_are_separate(self, request):
        with TemporaryDirectory() as folder, \
             patch("ai_report.__file__", str(Path(folder) / "ai_report.py")), \
             patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}):
            generate_gemini_report(*ARGS, backup=True)
            budget = request.call_args.args[3]
            self.assertEqual(budget.ledger.model, "gemini_backup:gemini-3.5-flash-lite")
            self.assertTrue((Path(folder) / "data" / "gemini_backup_debug.json").exists())
            self.assertFalse((Path(folder) / "data" / "gemini_debug.json").exists())

    @patch("ai_report._request_report", side_effect=[VALID_REPORT, RuntimeError("editor unavailable")])
    @patch("ai_report.generate_backup_gemini_report")
    def test_primary_valid_draft_with_failed_editor_never_uses_backup(self, backup, request):
        self.assertEqual(generate_report(*ARGS), VALID_REPORT.strip())
        backup.assert_not_called()


if __name__ == "__main__":
    unittest.main()
