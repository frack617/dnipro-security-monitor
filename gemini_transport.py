"""Bounded Gemini requests and safe quota diagnostics (no keys or raw bodies)."""
import json
import math
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

import requests


@dataclass
class RequestBudget:
    limit: int = 4
    used: int = 0
    rate_retry_used: bool = False
    ledger: object = None
    stage: str = "author"
    debug_path: object = None
    records: list = field(default_factory=list)
    secret: str = field(default="", repr=False)

    def save_debug(self):
        if self.debug_path is None:
            return
        data = {"run_id": os.getenv("GITHUB_RUN_ID", "local"), "attempts": self.records}
        encoded = json.dumps(data, ensure_ascii=False, indent=2)
        if self.secret:
            encoded = encoded.replace(self.secret, "[redacted]")
        encoded = re.sub(r"AIza[A-Za-z0-9_-]+", "[redacted]", encoded)
        try:
            path = Path(self.debug_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".tmp")
            temporary.write_text(encoded + "\n", encoding="utf-8")
            temporary.replace(path)
        except OSError:
            print("Gemini diagnostics could not be saved")

    def validation(self, text, error=None):
        if self.records:
            self.records[-1].update({"validated_text": text,
                "validation": "rejected" if error else "passed",
                "validation_error": str(error) if error else None})
            self.save_debug()


def extract_response(body):
    """Read the first candidate, excluding thought parts and signatures."""
    candidates = body.get("candidates", [])
    candidate = candidates[0] if candidates else {}
    parts = candidate.get("content", {}).get("parts", [])
    texts = [p["text"] for p in parts if isinstance(p, dict)
             and p.get("thought") is not True and isinstance(p.get("text"), str)]
    text = "".join(texts)
    usage = body.get("usageMetadata", {})
    metadata = {
        "finish_reason": candidate.get("finishReason"),
        "block_reason": body.get("promptFeedback", {}).get("blockReason"),
        "part_count": len(parts), "text_part_count": len(texts),
        "text": text,
        "usage": {k: usage[k] for k in (
            "promptTokenCount", "candidatesTokenCount", "totalTokenCount",
            "thoughtsTokenCount", "cachedContentTokenCount")
            if isinstance(usage.get(k), int)},
    }
    return text, metadata


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
    budget.secret = api_key
    payload = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
               "generationConfig": {"temperature": 0.1, "maxOutputTokens": 2200}}
    while True:
        if budget.used >= budget.limit:
            raise RuntimeError("Gemini request budget exhausted")
        request_id = budget.ledger.reserve(budget.stage) if budget.ledger is not None else None
        budget.used += 1
        budget.records.append({"attempt": budget.used, "stage": budget.stage,
                               "status": "request_started"})
        budget.save_debug()
        try:
            response = requests.post(
                endpoint, params={"key": api_key},
                headers={"Content-Type": "application/json"},
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), timeout=90)
        except requests.RequestException as error:
            budget.records[-1]["status"] = "transport_error"
            budget.save_debug()
            if budget.ledger is not None:
                budget.ledger.finish(request_id, "transport_error")
            # requests exception messages can contain the URL with its key.
            raise RuntimeError("Gemini transport error: " + type(error).__name__) from None
        if response.status_code == 200:
            if budget.ledger is not None:
                budget.ledger.finish(request_id, "http_200")
            try:
                text, metadata = extract_response(response.json())
            except (AttributeError, KeyError, IndexError, TypeError, ValueError):
                budget.records[-1]["status"] = "invalid_response"
                budget.save_debug()
                raise RuntimeError("Gemini returned no usable text") from None
            budget.records[-1].update(metadata, status="http_200")
            budget.save_debug()
            summary = {k: metadata[k] for k in metadata if k != "text"}
            print("Gemini response diagnostic: " + json.dumps(summary, ensure_ascii=False))
            reason = metadata["finish_reason"]
            if reason and reason != "STOP":
                raise RuntimeError("Gemini incomplete response: " + _safe(reason, api_key))
            if not text.strip():
                raise RuntimeError("Gemini returned no usable text")
            return text
        diagnostic = diagnose_response(response, api_key)
        budget.records[-1].update(status=f"http_{response.status_code}", diagnostic=diagnostic)
        budget.save_debug()
        if budget.ledger is not None:
            budget.ledger.finish(request_id, f"http_{response.status_code}", diagnostic)
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
