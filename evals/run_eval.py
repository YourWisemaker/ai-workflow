"""Live eval: runs every case against the real model and scores root cause + severity. Costs API credits."""
import json
from pathlib import Path

import anthropic

from triage.agent import triage

cases = json.loads((Path(__file__).parent / "cases.json").read_text())
client = anthropic.Anthropic()
passed = 0
for case in cases:
    result = triage(client, case["alert"], log_path=Path("out/eval_runs.jsonl"))
    verdict = result.get("verdict", {})
    ok = (result["status"] == "ok"
          and verdict.get("root_cause_service") == case["root_cause_service"]
          and verdict.get("severity") == case["severity"])
    passed += ok
    print(f"{'PASS' if ok else 'FAIL'}  {case['alert'][:60]:60}  -> {verdict.get('root_cause_service')}/{verdict.get('severity')} ({result['status']})")
print(f"\n{passed}/{len(cases)} cases passed")
