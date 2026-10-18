"""Bounded Gemini requests and safe quota diagnostics (no keys or raw bodies)."""
import json
import math
import re
import time
from dataclasses import dataclass

import requests


@dataclass
class RequestBudget:
    limit: int = 4
    used: int = 0
    rate_retry_used: bool = False


class GeminiAPIError(RuntimeError):
    def __init__(self, diagnostic):
        self.diagnostic = diagnostic
        super().__init__("Gemini API: " + json.dumps(diagnostic, ensure_ascii=False))


def _safe(value, api_key):
    text = str(value).replace(api_key, "[redacted]") if api_key else str(value)
    text = re.sub(r"AIza[A-Za-z0-9_-]+", "[redacted]", text)
    return re.sub(r"[^A-Za-z0-9_./: -]", "?", text)[:200]


def diagnose_response(response, api_key=""):
    diagnostic = {"http": response.status_code, "reason": "unknown", "violations": []}
    try:
        body = response.json()
    except (ValueError, TypeError):
        body = {}
    error = body.get("error", {}) if isinstance(body, dict) else {}
    if not isinstance(error, dict):
        error = {}
    diagnostic["status"] = _safe(error.get("status", "unknown"), api_key)
    details = error.get("details", [])
    if not isinstance(details, list):
        details = []
    retry_seconds = None
    for detail in details:
        if not isinstance(detail, dict):
            continue
        kind = str(detail.get("@type", ""))
        if kind.endswith("QuotaFailure"):
            violations = detail.get("violations", [])
            if not isinstance(violations, list):
                continue
            for violation in violations:
                if not isinstance(violation, dict):
                    continue
                item = {key: _safe(violation[key], api_key)
                        for key in ("quotaMetric", "quotaId", "quotaValue") if key in violation}
                dimensions = violation.get("quotaDimensions", {})
                if isinstance(dimensions, dict) and "model" in dimensions:
                    item["model"] = _safe(dimensions["model"], api_key)
                diagnostic["violations"].append(item)
        if kind.endswith("RetryInfo"):
            delay = detail.get("retryDelay", "")
            match = re.fullmatch(r"(\d+(?:\.\d+)?)s", str(delay))
            if match:
                retry_seconds = float(match.group(1))
    if retry_seconds is None:
        value = str(response.headers.get("Retry-After", ""))
        if re.fullmatch(r"\d+(?:\.\d+)?", value):
            retry_seconds = float(value)
    if retry_seconds is not None and math.isfinite(retry_seconds):
        diagnostic["retry_seconds"] = retry_seconds
    identifiers = " ".join(str(item) for item in diagnostic["violations"]).lower()
    if any(v.get("quotaValue") == "0" for v in diagnostic["violations"]):
        diagnostic["reason"] = "zero_quota"
    elif re.search(r"perday|per_day|daily", identifiers):
        diagnostic["reason"] = "daily_quota"
    elif re.search(r"perminute|per_minute|persecond|per_second", identifiers):
        diagnostic["reason"] = "short_rate_limit"
    elif response.status_code == 429:
        diagnostic["reason"] = "unclassified_429"
    elif response.status_code in (500, 502, 503, 504):
        diagnostic["reason"] = "service_unavailable"
    return diagnostic


def request_text(endpoint, api_key, prompt, budget=None, allow_rate_retry=False):
    budget = budget if budget is not None else RequestBudget(limit=1)
    payload = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
               "generationConfig": {"temperature": 0.1, "maxOutputTokens": 2200}}
    while True:
        if budget.used >= budget.limit:
            raise RuntimeError("Gemini request budget exhausted")
        budget.used += 1
        try:
            response = requests.post(
                endpoint, params={"key": api_key},
                headers={"Content-Type": "application/json"},
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), timeout=90)
        except requests.RequestException as error:
            # requests exception messages can contain the URL with its key.
            raise RuntimeError("Gemini transport error: " + type(error).__name__) from None
        if response.status_code == 200:
            try:
                return response.json()["candidates"][0]["content"]["parts"][0]["text"]
            except (KeyError, IndexError, TypeError, ValueError):
                raise RuntimeError("Gemini returned no usable text") from None
        diagnostic = diagnose_response(response, api_key)
        print("Gemini API diagnostic: " + json.dumps(diagnostic, ensure_ascii=False))
        delay = diagnostic.get("retry_seconds")
        can_retry = (
            allow_rate_retry and response.status_code == 429
            and diagnostic["reason"] == "short_rate_limit"
            and delay is not None and 0 <= delay <= 44
            and not budget.rate_retry_used and budget.used < budget.limit
        )
        if not can_retry:
            raise GeminiAPIError(diagnostic)
        budget.rate_retry_used = True
        wait = math.ceil(delay) + 1
        print(f"Gemini short rate limit: one retry in {wait}s within total budget {budget.limit}")
        time.sleep(wait)
