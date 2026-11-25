"""python -m triage "alert text" [--allow-write] [--replay]"""
import argparse
import json

from triage.agent import triage

parser = argparse.ArgumentParser(prog="triage")
parser.add_argument("alert")
parser.add_argument("--allow-write", action="store_true", help="let the agent file tickets (default: dry-run)")
parser.add_argument("--replay", action="store_true", help="use the scripted client, no API key needed")
args = parser.parse_args()

if args.replay:
    from triage.replay import PAYMENT_TIMEOUT, ReplayClient
    client = ReplayClient(PAYMENT_TIMEOUT)
else:
    import anthropic
    client = anthropic.Anthropic()

print(json.dumps(triage(client, args.alert, allow_write=args.allow_write), indent=2))
