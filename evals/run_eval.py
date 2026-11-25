"""Live eval: runs every case against the real model, scores root cause + severity, writes evals/results.md.
Costs API credits. Run once: python3 -m evals.run_eval"""
import json
from pathlib import Path

from triage.agent import MODEL, triage

HERE = Path(__file__).parent


def score(case: dict, result: dict) -> bool:
    verdict = result.get("verdict", {})
    return (result["status"] == "ok"
            and verdict.get("root_cause_service") == case["root_cause_service"]
            and verdict.get("severity") == case["severity"])


def report(rows: list[tuple[dict, dict, bool]]) -> str:
    n = len(rows)
    passed = sum(ok for _, _, ok in rows)
    escalated = sum(r["status"] == "escalate" for _, r, _ in rows)
    usage = [r["usage"] for _, r, _ in rows]
    lines = [
        f"# Eval results ({MODEL})", "",
        f"- Pass rate: {passed}/{n} ({passed / n:.0%})",
        f"- Escalated to human: {escalated}/{n}",
        f"- Avg turns per run: {sum(u['turns'] for u in usage) / n:.1f}",
        f"- Avg tokens per run: {sum(u['input_tokens'] + u['output_tokens'] for u in usage) / n:,.0f}",
        f"- Avg cost per run: ${sum(u['cost_usd'] for u in usage) / n:.4f}",
        f"- Total cost: ${sum(u['cost_usd'] for u in usage):.4f}", "",
        "| Result | Alert | Expected | Got |", "|---|---|---|---|",
    ]
    for case, result, ok in rows:
        v = result.get("verdict", {})
        got = f"{v.get('root_cause_service')}/{v.get('severity')}" if v else result["status"]
        lines.append(f"| {'PASS' if ok else 'FAIL'} | {case['alert']} | {case['root_cause_service']}/{case['severity']} | {got} |")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    import anthropic

    from triage.env import load_env
    load_env()
    client = anthropic.Anthropic()
    rows = []
    for case in json.loads((HERE / "cases.json").read_text()):
        result = triage(client, case["alert"], log_path=Path("out/eval_runs.jsonl"))
        rows.append((case, result, score(case, result)))
        print("PASS" if rows[-1][2] else "FAIL", case["alert"][:70])
    (HERE / "results.md").write_text(report(rows))
    print(report(rows))
