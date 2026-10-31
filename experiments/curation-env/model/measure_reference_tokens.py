"""Reference JSON+EOS token budgets; this does not invoke a model."""
import os,json
from pathlib import Path
os.environ['HF_HUB_OFFLINE']='1';os.environ['TRANSFORMERS_OFFLINE']='1';os.environ['HF_HUB_DISABLE_IMPLICIT_TOKEN']='1'
from transformers import AutoTokenizer
root=Path(__file__).resolve().parent
tok=AutoTokenizer.from_pretrained(str(root/'model'),local_files_only=True)
controls=json.loads((root/'deterministic-controls.json').read_text());rows=[]
for e in controls['episodes']:
    counts=[]
    for t in e['reference']['steps']:
        action={'tool':t['action']['tool'],'args':t['action'].get('args',{})}
        counts.append(len(tok.encode(json.dumps(action,separators=(',',':'))+'<|im_end|>')))
    rows.append({'task_id':e['task_id'],'steps':len(counts),'per_action_tokens':counts,'total_action_tokens':sum(counts)})
report={'model_tokenizer':'pinned Qwen3-1.7B-MLX-4bit','episodes':rows,'max_single_action_tokens':max(max(r['per_action_tokens']) for r in rows),'max_episode_action_tokens':max(r['total_action_tokens'] for r in rows),'note':'Reference action JSON plus EOS counts, not measured model generations; demonstrations fit all frozen action/token budgets.'}
(root/'reference-token-budgets.json').write_text(json.dumps(report,indent=2)+'\n')
