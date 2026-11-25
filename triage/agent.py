"""Incident triage agent: alert in, grounded verdict (and optionally a ticket) out."""
import json
import time
import uuid
from pathlib import Path

from triage import tools

MODEL = "claude-opus-5"
MAX_TURNS = 8
READ_TOOLS = {"search_logs", "get_trace"}
WRITE_TOOLS = {"create_ticket"}

SYSTEM = """You are the first responder for production alerts.
Use search_logs and get_trace to find the service where the failure starts, not where it surfaces.
Cite the trace ids you looked at. If the logs do not support a conclusion, say so in the summary and pick severity "medium".
Severity: high = customer-facing requests failing, medium = degraded or internal impact, low = threshold noise with no failed work.
If a create_ticket call is denied, carry on and still finish with submit_triage."""


class Run:
    """State for one triage run: what the agent has seen and what it did."""

    def __init__(self, allow_write: bool, outbox: Path, log_path: Path):
        self.id = uuid.uuid4().hex[:8]
        self.allow_write = allow_write
        self.outbox = outbox
        self.log_path = log_path
        self.seen_rows: list[dict] = []

    def log(self, event: dict) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a") as f:
            f.write(json.dumps({"run_id": self.id, **event}) + "\n")

    def call_tool(self, name: str, args: dict) -> tuple[str, bool]:
        """Returns (content, is_error). Every result is redacted before the model sees it."""
        if name in WRITE_TOOLS and not self.allow_write:
            return "denied: write tools are disabled for this run (dry-run). Do not retry.", True
        if name == "search_logs":
            rows = tools.search_logs(**args)
        elif name == "get_trace":
            rows = tools.get_trace(**args)
        elif name == "create_ticket":
            args = {k: tools.redact(v) for k, v in args.items()}
            return json.dumps(tools.create_ticket(**args, outbox=self.outbox)), False
        else:
            return f"unknown tool {name}", True
        self.seen_rows.extend(rows)
        return tools.redact(json.dumps(rows)), False

    def check_verdict(self, verdict: dict) -> str | None:
        """Grounding check: the verdict may only cite services and traces the agent actually fetched."""
        services = {r["service"] for r in self.seen_rows}
        traces = {r["trace_id"] for r in self.seen_rows}
        if verdict["root_cause_service"] not in services:
            return f"root_cause_service {verdict['root_cause_service']!r} is not in any log you fetched. Fetched services: {sorted(services)}"
        unknown = set(verdict["evidence_trace_ids"]) - traces
        if unknown:
            return f"trace ids {sorted(unknown)} were never fetched. Fetch them or drop them."
        return None


def triage(client, alert: str, allow_write: bool = False,
           outbox: Path = Path("out/tickets.jsonl"), log_path: Path = Path("out/runs.jsonl")) -> dict:
    run = Run(allow_write, outbox, log_path)
    messages = [{"role": "user", "content": alert}]
    run.log({"event": "start", "alert": alert, "allow_write": allow_write})

    for turn in range(1, MAX_TURNS + 1):
        started = time.monotonic()
        response = client.beta.messages.create(
            model=MODEL,
            max_tokens=16000,
            system=SYSTEM,
            tools=tools.SCHEMAS,
            messages=messages,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        run.log({
            "event": "model_call", "turn": turn, "stop_reason": response.stop_reason,
            "input_tokens": response.usage.input_tokens, "output_tokens": response.usage.output_tokens,
            "latency_ms": round((time.monotonic() - started) * 1000),
        })

        if response.stop_reason in ("refusal", "max_tokens"):
            return finish(run, "escalate", reason=f"model stopped with {response.stop_reason}")
        calls = [b for b in response.content if b.type == "tool_use"]
        if not calls:
            return finish(run, "escalate", reason="model ended without submit_triage")

        messages.append({"role": "assistant", "content": response.content})
        results = []
        for call in calls:
            if call.name == "submit_triage":
                problem = run.check_verdict(call.input)
                if problem is None:
                    return finish(run, "ok", verdict=call.input)
                content, is_error = problem, True
            else:
                try:
                    content, is_error = run.call_tool(call.name, call.input)
                except Exception as exc:  # a broken tool must not kill the run, the model can route around it
                    content, is_error = f"tool failed: {exc}", True
            run.log({"event": "tool", "turn": turn, "name": call.name, "is_error": is_error})
            results.append({"type": "tool_result", "tool_use_id": call.id, "content": content, "is_error": is_error})
        messages.append({"role": "user", "content": results})

    return finish(run, "escalate", reason=f"hit MAX_TURNS={MAX_TURNS}")


def finish(run: Run, status: str, **extra) -> dict:
    result = {"run_id": run.id, "status": status, **extra}
    run.log({"event": "finish", **result})
    return result
