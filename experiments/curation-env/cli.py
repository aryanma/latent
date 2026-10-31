#!/usr/bin/env python3
"""JSONL environment transport. One request and one response per line; no network."""
import argparse
import json
import sys
from latent_curation.environment import CurationEnv, generate_task

parser = argparse.ArgumentParser(description='Latent Curation environment over stdin/stdout JSONL')
parser.add_argument('--seed',type=int,default=7)
parser.add_argument('--family',default='composition')
args = parser.parse_args()
env = CurationEnv(generate_task(args.seed,args.family))
print(json.dumps(env.reset()),flush=True)
for line in sys.stdin:
    try:
        request = json.loads(line)
        operation = request.get('op') if isinstance(request, dict) else None
        if operation == 'reset':
            env = CurationEnv(generate_task(request.get('seed',args.seed),request.get('family',args.family)))
            response = env.reset()
        elif operation == 'export': response = env.export_trajectory()
        else: response = env.step(request)
    except (ValueError,TypeError,KeyError,RuntimeError) as exc:
        response = {'transport_error':str(exc)}
    print(json.dumps(response),flush=True)
