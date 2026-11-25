"""python -m triage "alert text" [--allow-write] [--replay]"""
import argparse
import json
import sys

from triage.agent import triage


def ask_on_call(ticket: dict) -> bool:
    if not sys.stdin.isatty():
        return False
    print(json.dumps(ticket, indent=2), file=sys.stderr)
    return input("File this ticket? [y/N] ").strip().lower() == "y"


parser = argparse.ArgumentParser(prog="triage")
parser.add_argument("alert")
parser.add_argument("--allow-write", action="store_true", help="let the agent file tickets (default: dry-run)")
parser.add_argument("--replay", action="store_true", help="use the scripted client, no API key needed")
parser.add_argument("--yes", action="store_true", help="approve tickets without asking (demo only)")
args = parser.parse_args()

if args.replay:
    from triage.replay import PAYMENT_TIMEOUT, ReplayClient
    client = ReplayClient(PAYMENT_TIMEOUT)
else:
    import anthropic

    from triage.env import load_env
    load_env()
    client = anthropic.Anthropic()

print(json.dumps(triage(client, args.alert, allow_write=args.allow_write,
                        approve=(lambda ticket: True) if args.yes else ask_on_call), indent=2))
