import json
import tempfile
import unittest
from pathlib import Path

from triage.agent import MAX_TURNS, triage
from triage.replay import PAYMENT_TIMEOUT, ReplayClient, tool_use

ALERT = "checkout error rate above 5%"


class AgentTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.outbox = self.tmp / "tickets.jsonl"
        self.log = self.tmp / "runs.jsonl"

    def run_agent(self, client, allow_write=False):
        return triage(client, ALERT, allow_write=allow_write, outbox=self.outbox, log_path=self.log)

    def test_happy_path_returns_grounded_verdict(self):
        result = self.run_agent(ReplayClient(PAYMENT_TIMEOUT), allow_write=True)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["verdict"]["root_cause_service"], "payment-gateway")

    def test_secrets_never_reach_the_model_or_the_ticket(self):
        client = ReplayClient(PAYMENT_TIMEOUT)
        self.run_agent(client, allow_write=True)
        tool_results = [block["content"] for request in client.requests for message in request["messages"]
                        if message["role"] == "user" and isinstance(message["content"], list)
                        for block in message["content"]]
        self.assertNotIn("sk_live_", "".join(tool_results))
        self.assertIn("[REDACTED]", "".join(tool_results))
        self.assertNotIn("sk_live_", self.outbox.read_text())

    def test_write_tool_denied_in_dry_run(self):
        client = ReplayClient(PAYMENT_TIMEOUT)
        result = self.run_agent(client, allow_write=False)
        self.assertFalse(self.outbox.exists())
        self.assertEqual(result["status"], "ok")
        denied = [e for e in map(json.loads, self.log.read_text().splitlines())
                  if e.get("name") == "create_ticket"]
        self.assertTrue(denied[0]["is_error"])

    def test_ungrounded_verdict_is_rejected(self):
        client = ReplayClient([
            [tool_use("submit_triage", {"summary": "guess", "root_cause_service": "dns", "severity": "high",
                                        "evidence_trace_ids": [], "next_action": "x"}, "c1")],
        ])
        result = self.run_agent(client)
        self.assertEqual(result["status"], "escalate")
        last_results = client.requests[-1]["messages"][-1]["content"]
        self.assertIn("not in any log you fetched", last_results[0]["content"])

    def test_turn_cap_escalates(self):
        loop = [[tool_use("get_trace", {"trace_id": "t-100"}, f"c{i}")] for i in range(MAX_TURNS + 5)]
        result = self.run_agent(ReplayClient(loop))
        self.assertEqual(result["status"], "escalate")
        self.assertIn("MAX_TURNS", result["reason"])

    def test_refusal_escalates(self):
        result = self.run_agent(ReplayClient(PAYMENT_TIMEOUT, stop_reason="refusal"))
        self.assertEqual(result["status"], "escalate")


if __name__ == "__main__":
    unittest.main()
