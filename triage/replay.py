"""Scripted stand-in for the Anthropic client. Lets tests and the offline demo drive the real loop with no API key."""
from types import SimpleNamespace as NS


def tool_use(name: str, args: dict, id: str) -> NS:
    return NS(type="tool_use", name=name, input=args, id=id)


class ReplayClient:
    def __init__(self, turns: list[list[NS]], stop_reason: str = "tool_use"):
        self.turns = list(turns)
        self.stop_reason = stop_reason
        self.requests: list[dict] = []
        self.beta = NS(messages=NS(create=self.create))

    def create(self, **request) -> NS:
        self.requests.append(request)
        content = self.turns.pop(0) if self.turns else []
        stop = self.stop_reason if content else "end_turn"
        return NS(content=content, stop_reason=stop, usage=NS(input_tokens=0, output_tokens=0))


PAYMENT_TIMEOUT = [
    [tool_use("search_logs", {"service": "checkout-api", "level": "error", "since": "2026-11-20T00:00:00Z"}, "c1")],
    [tool_use("get_trace", {"trace_id": "t-100"}, "c2")],
    [tool_use("create_ticket", {
        "title": "payment-gateway timeouts failing checkout",
        "body": "Provider calls time out after 3 retries. Seen: Authorization: Bearer sk_live_51HxQe9fakeKEY0000",
        "severity": "high"}, "c3")],
    [tool_use("submit_triage", {
        "summary": "Checkout 5xx are caused by payment-gateway timing out against the provider.",
        "root_cause_service": "payment-gateway", "severity": "high",
        "evidence_trace_ids": ["t-100"], "next_action": "Page payments on-call, check provider status page."}, "c4")],
]
