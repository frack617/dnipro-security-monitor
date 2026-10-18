import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock, patch

import requests
from gemini_transport import GeminiAPIError, RequestBudget, diagnose_response, request_text


def response(quota=None, value="20", delay="2s", code=429):
    details = []
    if quota:
        details.append({"@type": "type.googleapis.com/google.rpc.QuotaFailure",
                        "violations": [{"quotaId": quota, "quotaValue": value,
                        "quotaDimensions": {"model": "gemini-2.5-flash-lite"}}]})
    if delay is not None:
        details.append({"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": delay})
    r = Mock(status_code=code, headers={})
    r.json.return_value = {"error": {"status": "RESOURCE_EXHAUSTED", "details": details}}
    return r


def success():
    r = Mock(status_code=200)
    r.json.return_value = {"candidates": [{"content": {"parts": [{"text": "Довідка"}]}}]}
    return r


class QuotaDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(redirect_stdout(io.StringIO()))

    def test_identifies_daily_quota(self):
        self.assertEqual(diagnose_response(response("GenerateRequestsPerDayPerProjectPerModel-FreeTier"))["reason"], "daily_quota")

    def test_identifies_zero_quota(self):
        self.assertEqual(diagnose_response(response("GenerateRequestsPerMinute", "0"))["reason"], "zero_quota")

    def test_retry_delay_alone_is_not_proof_of_minute_limit(self):
        self.assertEqual(diagnose_response(response())["reason"], "unclassified_429")

    def test_daily_limit_wins_over_minute_limit(self):
        r = response("GenerateRequestsPerMinute")
        r.json.return_value["error"]["details"][0]["violations"].append({"quotaId": "GenerateRequestsPerDay"})
        self.assertEqual(diagnose_response(r)["reason"], "daily_quota")

    def test_never_logs_raw_message_or_key(self):
        r = response("GenerateRequestsPerMinute")
        r.json.return_value["error"]["message"] = "secret-key private body"
        r.json.return_value["error"]["details"][0]["violations"][0]["quotaMetric"] = "secret-key"
        self.assertNotIn("secret-key", str(diagnose_response(r, "secret-key")))
        self.assertNotIn("private body", str(diagnose_response(r, "secret-key")))

    @patch("gemini_transport.time.sleep")
    @patch("gemini_transport.requests.post")
    def test_one_short_retry_succeeds(self, post, sleep):
        post.side_effect = [response("GenerateRequestsPerMinute"), success()]
        budget = RequestBudget()
        self.assertEqual(request_text("endpoint", "key", "prompt", budget, True), "Довідка")
        self.assertEqual(post.call_count, 2)
        sleep.assert_called_once_with(3)
        self.assertEqual(budget.used, 2)

    @patch("gemini_transport.time.sleep")
    @patch("gemini_transport.requests.post")
    def test_does_not_retry_daily_zero_or_unknown_limits(self, post, sleep):
        for r in (response("GenerateRequestsPerDay"), response("GenerateRequestsPerMinute", "0"), response()):
            with self.subTest(response=r):
                post.reset_mock()
                post.return_value = r
                with self.assertRaises(GeminiAPIError):
                    request_text("endpoint", "key", "prompt", RequestBudget(), True)
                self.assertEqual(post.call_count, 1)
        sleep.assert_not_called()

    @patch("gemini_transport.time.sleep")
    @patch("gemini_transport.requests.post")
    def test_no_second_short_retry(self, post, sleep):
        post.return_value = response("GenerateRequestsPerMinute")
        with self.assertRaises(GeminiAPIError):
            request_text("endpoint", "key", "prompt", RequestBudget(), True)
        self.assertEqual(post.call_count, 2)
        sleep.assert_called_once()

    @patch("gemini_transport.time.sleep")
    @patch("gemini_transport.requests.post")
    def test_no_long_wait(self, post, sleep):
        post.return_value = response("GenerateRequestsPerMinute", delay="60s")
        with self.assertRaises(GeminiAPIError):
            request_text("endpoint", "key", "prompt", RequestBudget(), True)
        sleep.assert_not_called()

    @patch("gemini_transport.requests.post")
    def test_total_budget_is_enforced(self, post):
        with self.assertRaisesRegex(RuntimeError, "budget exhausted"):
            request_text("endpoint", "key", "prompt", RequestBudget(used=4), True)
        post.assert_not_called()

    @patch("gemini_transport.requests.post")
    def test_no_quota_retry_for_editor_with_valid_draft(self, post):
        post.return_value = response("GenerateRequestsPerMinute")
        with self.assertRaises(GeminiAPIError):
            request_text("endpoint", "key", "prompt", RequestBudget(), False)
        self.assertEqual(post.call_count, 1)

    @patch("gemini_transport.requests.post")
    def test_connection_errors_do_not_expose_request_url(self, post):
        post.side_effect = requests.ConnectionError("https://example?key=secret-key")
        with self.assertRaises(RuntimeError) as caught:
            request_text("endpoint", "secret-key", "prompt")
        self.assertNotIn("secret-key", str(caught.exception))

    def test_handles_non_json_errors(self):
        r = Mock(status_code=503, headers={})
        r.json.side_effect = ValueError("not json")
        self.assertEqual(diagnose_response(r)["reason"], "service_unavailable")


if __name__ == "__main__":
    unittest.main()
