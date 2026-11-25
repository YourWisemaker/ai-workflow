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

    def run_agent(self, client, allow_write=False, approve=lambda ticket: True):
        return triage(client, ALERT, allow_write=allow_write, approve=approve, outbox=self.outbox, log_path=self.log)

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

    def test_reviewer_can_decline_ticket(self):
        result = self.run_agent(ReplayClient(PAYMENT_TIMEOUT), allow_write=True, approve=lambda ticket: False)
        self.assertFalse(self.outbox.exists())
        self.assertEqual(result["status"], "ok")

    def test_no_reviewer_means_no_ticket(self):
        triage(ReplayClient(PAYMENT_TIMEOUT), ALERT, allow_write=True, outbox=self.outbox, log_path=self.log)
        self.assertFalse(self.outbox.exists())

    def test_usage_and_cost_are_reported(self):
        usage = self.run_agent(ReplayClient(PAYMENT_TIMEOUT))["usage"]
        self.assertEqual(usage["turns"], 4)
        self.assertEqual(usage["input_tokens"], 4000)
        self.assertAlmostEqual(usage["cost_usd"], 4 * (1000 * 5 + 200 * 25) / 1_000_000)

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


class RedactTest(unittest.TestCase):
    def test_known_secret_shapes(self):
        from triage.tools import redact
        cases = {"Bearer abc.def-ghi": "abc.def", "sk_live_123abc": "123abc", "whsec_9f8e7d": "9f8e7d",
                 "postgres://user:pw@host/db": "user:pw"}
        for text, secret in cases.items():
            self.assertNotIn(secret, redact(f"x {text} y"), text)


class EnvTest(unittest.TestCase):
    def test_env_file_fills_gaps_but_real_env_wins(self):
        import os
        from triage.env import load_env
        path = Path(tempfile.mkdtemp()) / ".env"
        path.write_text("# comment\nTRIAGE_TEST_A='from-file'\nTRIAGE_TEST_B=from-file\nTRIAGE_TEST_EMPTY=\n")
        os.environ["TRIAGE_TEST_B"] = "from-shell"
        load_env(path)
        self.assertEqual(os.environ.pop("TRIAGE_TEST_A"), "from-file")
        self.assertEqual(os.environ.pop("TRIAGE_TEST_B"), "from-shell")
        self.assertNotIn("TRIAGE_TEST_EMPTY", os.environ)


class EvalReportTest(unittest.TestCase):
    def test_report_scores_root_cause_and_severity(self):
        from evals.run_eval import report, score
        case = {"alert": "a", "root_cause_service": "payment-gateway", "severity": "high"}
        usage = {"turns": 4, "input_tokens": 4000, "output_tokens": 800, "cost_usd": 0.04}
        good = {"status": "ok", "verdict": {"root_cause_service": "payment-gateway", "severity": "high"}, "usage": usage}
        wrong = {"status": "ok", "verdict": {"root_cause_service": "checkout-api", "severity": "high"}, "usage": usage}
        rows = [(case, good, score(case, good)), (case, wrong, score(case, wrong))]
        text = report(rows)
        self.assertIn("Pass rate: 1/2 (50%)", text)
        self.assertIn("Avg cost per run: $0.0400", text)


if __name__ == "__main__":
    unittest.main()
