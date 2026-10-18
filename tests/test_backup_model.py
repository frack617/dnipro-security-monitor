import io
import os
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock, patch

from ai_report import generate_gemini_report
from gemini_transport import diagnose_response
from test_ai_report import VALID_REPORT


ARGS = ([], "08:00 16.10.2026", "08:00 17.10.2026",
        "08:05 17.10.2026", "17.10.2026", [])


class BackupModelTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(redirect_stdout(io.StringIO()))
        self.enterContext(patch.dict(os.environ, {
            "GEMINI_API_KEY": "primary-test", "GEMINI_BACKUP_API_KEY": "backup-test",
            "GITHUB_ACTIONS": "false", "GEMINI_MODEL": "gemini-2.5-flash-lite",
            "GEMINI_BACKUP_MODEL": "",
        }))

    @patch("ai_report._request_report", return_value=VALID_REPORT)
    def test_backup_default_is_new_model_and_primary_stays_old(self, request):
        generate_gemini_report(*ARGS, backup=True)
        self.assertIn("/models/gemini-3.5-flash-lite:generateContent", request.call_args.args[0])
        request.reset_mock()
        generate_gemini_report(*ARGS)
        self.assertIn("/models/gemini-2.5-flash-lite:generateContent", request.call_args.args[0])

    @patch("ai_report._request_report", return_value=VALID_REPORT)
    def test_backup_model_is_configurable_independently(self, request):
        with patch.dict(os.environ, {"GEMINI_BACKUP_MODEL": "gemini-2.5-flash"}):
            generate_gemini_report(*ARGS, backup=True)
        self.assertIn("/models/gemini-2.5-flash:generateContent", request.call_args.args[0])

    def test_retired_model_error_has_safe_actionable_diagnostic(self):
        r = Mock(status_code=404, headers={})
        r.json.return_value = {"error": {"status": "NOT_FOUND", "message":
            "secret-key This model is no longer available to new users. "
            "Please update your code to use models/gemini-3.5-flash-lite."}}
        diagnostic = diagnose_response(r, "secret-key")
        self.assertEqual(diagnostic["reason"], "model_unavailable")
        self.assertEqual(diagnostic["suggested_model"], "gemini-3.5-flash-lite")
        self.assertNotIn("secret-key", str(diagnostic))
        self.assertNotIn("message", diagnostic)

    def test_unrelated_404_is_not_classified_as_retired_model(self):
        r = Mock(status_code=404, headers={})
        r.json.return_value = {"error": {"status": "NOT_FOUND", "message": "Other resource missing"}}
        self.assertNotEqual(diagnose_response(r)["reason"], "model_unavailable")


if __name__ == "__main__":
    unittest.main()
