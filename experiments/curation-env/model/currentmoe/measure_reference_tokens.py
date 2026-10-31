"""Reference action budgets under the pinned current-model tokenizer; no inference."""
import argparse,os,json,hashlib
from pathlib import Path
os.environ['HF_HUB_OFFLINE']='1';os.environ['TRANSFORMERS_OFFLINE']='1';os.environ['HF_HUB_DISABLE_IMPLICIT_TOKEN']='1'
from transformers import AutoTokenizer
parser=argparse.ArgumentParser();parser.add_argument('--controls',type=Path,required=True);args=parser.parse_args()
root=Path(__file__).resolve().parent;tok=AutoTokenizer.from_pretrained(str(root/'model'),local_files_only=True)
controls=json.loads(args.controls.read_text());rows=[]
for episode in controls['episodes']:
    counts=[]
    for turn in episode['reference']['steps']:
        action={'tool':turn['action']['tool'],'args':turn['action'].get('args',{})}
        counts.append(len(tok.encode(json.dumps(action,separators=(',',':'))+'<|im_end|>')))
    rows.append({'task_id':episode['task_id'],'steps':len(counts),'per_action_tokens':counts,'total_action_tokens':sum(counts)})
report={'tokenizer':'pinned mlx-community/Qwen3.6-35B-A3B-4bit','controls_sha256':hashlib.sha256(args.controls.read_bytes()).hexdigest(),'episodes':rows,'max_single_action_tokens':max(max(r['per_action_tokens']) for r in rows),'max_episode_action_tokens':max(r['total_action_tokens'] for r in rows),'note':'Tokenized reference JSON+EOS, not model-generation measurements.'}
assert report['max_single_action_tokens']<=512 and report['max_episode_action_tokens']<=4096
(root/'reference-token-budgets.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({k:v for k,v in report.items() if k!='episodes'}))
