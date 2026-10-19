"""Conservative local limits; Google's project usage remains authoritative."""
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path


USAGE_FILE = Path(__file__).resolve().parent / "data" / "gemini_usage.json"


def local_limits(model):
    # Local ceilings, not a claim about Google's available server quota.
    # Raising both ceilings by two retains four scheduled attempts.
    return (10, 14) if model == "gemini-2.5-flash-lite" else (8, 12)


class UsageLedger:
    def __init__(self, model, path=USAGE_FILE, event=None, now=None):
        self.model = model
        self.path = Path(path)
        self.event = event if event is not None else os.getenv("GITHUB_EVENT_NAME", "manual")
        self.clock = now or (lambda: datetime.now(timezone.utc))

    @classmethod
    def from_environment(cls, model):
        if os.getenv("GITHUB_ACTIONS") != "true":
            return None
        event = ("production_dispatch" if os.getenv("GITHUB_EVENT_NAME") == "workflow_dispatch"
                 and os.getenv("PRODUCTION_MONITOR") == "true" else None)
        if (os.getenv("GITHUB_EVENT_NAME") == "workflow_dispatch"
            and os.getenv("USE_MORNING_RESERVE") == "true"
            and os.getenv("FORCE_MORNING_REPORT") == "true"
            and os.getenv("SEND_MORNING_REPORT") == "false"
            and os.getenv("REPORT_PROVIDER") == "gemini_backup"
            and model.startswith("gemini_backup:")):
            event = "manual_reserve_check"
        return cls(model, event=event)

    def _read(self):
        if not self.path.exists():
            return {"events": [], "blocked_until": {}}
        try:
            state = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(state, dict) or not isinstance(state.get("events"), list) or not isinstance(state.get("blocked_until"), dict):
                raise ValueError("invalid structure")
            for row in state["events"]:
                datetime.fromisoformat(row["at"])
            return state
        except (OSError, ValueError, KeyError, TypeError):
            raise RuntimeError("Gemini usage ledger unreadable; API disabled until repaired") from None

    def _write(self, state):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        cutoff = self.clock() - timedelta(hours=72)
        state["events"] = [r for r in state["events"] if datetime.fromisoformat(r["at"]) >= cutoff]
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.path)

    def reserve(self, stage):
        state = self._read()
        now = self.clock()
        blocked = state["blocked_until"].get(self.model)
        if blocked:
            try:
                if now < datetime.fromisoformat(blocked):
                    raise RuntimeError(f"Gemini quota cooldown active until {blocked}; no API request")
            except ValueError:
                raise RuntimeError("Invalid Gemini cooldown; API disabled until repaired") from None
        cutoff = now - timedelta(hours=24)
        rows = [r for r in state["events"] if r.get("model") == self.model and datetime.fromisoformat(r["at"]) > cutoff]
        manual_limit, total_limit = local_limits(self.model)
        if self.event == "manual_reserve_check" and sum(
            r.get("event") == "manual_reserve_check" for r in rows) >= 2:
            raise RuntimeError("Controlled reserve check exhausted: 2 attempts in rolling 24h; no API request")
        limit = total_limit if self.event in {"schedule", "production_dispatch", "manual_reserve_check"} else manual_limit
        if len(rows) >= limit:
            raise RuntimeError(f"Local Gemini budget blocked {self.event}: {len(rows)}/{limit} attempts in rolling 24h; no API request")
        run_id = os.getenv("GITHUB_RUN_ID", "local")
        request_id = f"{run_id}:{now.isoformat()}:{len(state['events'])}"
        state["events"].append({"id": request_id, "at": now.isoformat(), "model": self.model,
            "event": self.event, "run_id": run_id, "stage": stage, "outcome": "reserved"})
        self._write(state)
        print(f"AI request reserved: model={self.model} stage={stage} event={self.event} "
              f"rolling24h={len(rows)+1}/{total_limit} preview_stop={manual_limit}")
        return request_id

    def finish(self, request_id, outcome, diagnostic=None):
        state = self._read()
        for row in state["events"]:
            if row.get("id") == request_id:
                row["outcome"] = outcome
                if diagnostic:
                    row["reason"] = diagnostic["reason"]
                break
        if diagnostic and diagnostic["reason"] in ("daily_quota", "zero_quota"):
            seconds = diagnostic.get("retry_seconds")
            if isinstance(seconds, (int, float)) and 0 <= seconds <= 172800:
                state["blocked_until"][self.model] = (self.clock()+timedelta(seconds=seconds+1)).isoformat()
        self._write(state)
