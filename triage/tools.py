"""Tools the triage agent can call. Read tools hit the log store, the one write tool files a ticket."""
import json
import re
from pathlib import Path

LOGS = json.loads((Path(__file__).parent.parent / "fixtures" / "logs.json").read_text())

SECRET_PATTERNS = [
    re.compile(r"Bearer\s+[A-Za-z0-9._\-]+"),
    re.compile(r"\b(sk|pk|rk)_(live|test)_[A-Za-z0-9]+"),
    re.compile(r"\bwhsec_[A-Za-z0-9]+"),
    re.compile(r"://[^/\s:@]+:[^@\s]+@"),
]


def redact(text: str) -> str:
    for pattern in SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text


def search_logs(service: str = "", level: str = "", since: str = "", until: str = "") -> list[dict]:
    return [
        row for row in LOGS
        if (not service or row["service"] == service)
        and (not level or row["level"] == level)
        and (not since or row["ts"] >= since)
        and (not until or row["ts"] <= until)
    ]


def get_trace(trace_id: str) -> list[dict]:
    return [row for row in LOGS if row["trace_id"] == trace_id]


def create_ticket(title: str, body: str, severity: str, outbox: Path) -> dict:
    # ponytail: JSONL outbox stands in for the Linear API, swap the body of this function to go live
    outbox.parent.mkdir(parents=True, exist_ok=True)
    ticket = {"title": title, "body": body, "severity": severity}
    with outbox.open("a") as f:
        f.write(json.dumps(ticket) + "\n")
    return {"created": True, "id": f"TRI-{len(outbox.read_text().splitlines())}"}


SCHEMAS = [
    {
        "name": "search_logs",
        "description": "Search application logs. Filter by exact service name, level (error|warn|info) and an ISO timestamp window (since, until). Empty string means no filter. Keep the window tight around the alert time.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "service": {"type": "string"},
                "level": {"type": "string"},
                "since": {"type": "string"},
                "until": {"type": "string"},
            },
            "required": ["service", "level", "since", "until"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_trace",
        "description": "Return every log line that shares one trace_id, across services.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {"trace_id": {"type": "string"}},
            "required": ["trace_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "create_ticket",
        "description": "File a ticket for the on-call team. Only call after you have evidence.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "body": {"type": "string"},
                "severity": {"type": "string", "enum": ["low", "medium", "high"]},
            },
            "required": ["title", "body", "severity"],
            "additionalProperties": False,
        },
    },
    {
        "name": "submit_triage",
        "description": "Finish the run with your verdict. Call exactly once, last.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
                "root_cause_service": {"type": "string"},
                "severity": {"type": "string", "enum": ["low", "medium", "high"]},
                "evidence_trace_ids": {"type": "array", "items": {"type": "string"}},
                "next_action": {"type": "string"},
            },
            "required": ["summary", "root_cause_service", "severity", "evidence_trace_ids", "next_action"],
            "additionalProperties": False,
        },
    },
]
