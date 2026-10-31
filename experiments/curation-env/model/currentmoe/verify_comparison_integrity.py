"""Verify shared frozen harness fields across supplied result directories."""
import argparse,json,hashlib
from pathlib import Path
parser=argparse.ArgumentParser();parser.add_argument('runs',nargs='+',type=Path);args=parser.parse_args()
assert len(args.runs)>=2
manifests=[json.loads((r/'run-manifest.json').read_text()) for r in args.runs]
keys=['driver_sha256','system_prompt','environment_manifest_digest','per_turn_generation_limit','episode_generation_limit','max_steps','seed','temperature','task_ids']
for key in keys:assert all(m[key]==manifests[0][key] for m in manifests),key
prompts=[json.loads((r/'episode-labels-1000.json').read_text())['turns'][0]['prediction']['prompt_text'] for r in args.runs]
assert len(set(prompts))==1
print(json.dumps({'identical_fields':keys,'first_prompt_sha256':hashlib.sha256(prompts[0].encode()).hexdigest(),'verified_runs':len(args.runs)},indent=2))
