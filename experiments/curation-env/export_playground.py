"""Export fixed illustrative worlds and executable reference traces for the website."""
import argparse
import json
from pathlib import Path
from latent_curation.environment import CurationEnv, TOOLS, run_reference

ROOT=Path(__file__).resolve().parent
parser=argparse.ArgumentParser()
parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args()
all_tasks={x['task']['public']['id']:x['task'] for x in json.loads((ROOT/'tasks/evaluation.json').read_text())}
ids=['labels-1000','composition-2000','policy_shift-2000','permissions-1008','policy_shift-2004']
data={'tools':TOOLS,'tasks':[all_tasks[i] for i in ids],
      'references':{i:run_reference(CurationEnv(all_tasks[i])) for i in ids},
      'selection_note':'The default is the first authority pair by seed, selected before model evaluations. permissions-1008 and policy_shift-2004 are explicitly selected successful Qwen3.6 runs for illustration; aggregate results include every evaluation episode.'}
args.output.write_text(json.dumps(data,indent=2,sort_keys=True)+'\n')
