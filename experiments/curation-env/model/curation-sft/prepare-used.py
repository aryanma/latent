"""Generate fresh public-evidence expert prefixes, never read evaluation worlds."""
from copy import deepcopy
import hashlib, importlib.util, json, math
from pathlib import Path
import sys
sys.dont_write_bytecode=True
from local_runtime import MODEL_DIR, NONTHINKING_PREFILL, network_attempts
from curation_driver import PROMPTS
from transformers import AutoTokenizer
ROOT=Path(__file__).resolve().parent
OUT=ROOT/'curation-sft'
OUT.mkdir(exist_ok=False)
source=ROOT/'curation-eval-base/environment-snapshot/latent_curation/environment.py'
spec=importlib.util.spec_from_file_location('frozen_env_training',source)
envmod=importlib.util.module_from_spec(spec);spec.loader.exec_module(envmod)
(OUT/'environment.py').write_bytes(source.read_bytes())
(OUT/'prepare-used.py').write_bytes(Path(__file__).read_bytes())
tok=AutoTokenizer.from_pretrained(str(MODEL_DIR),local_files_only=True)
compact=lambda x: json.dumps(x,ensure_ascii=False,separators=(',',':'))
families=['labels','duplicates','permissions','leakage','versions','pair']
manifest={'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'prompt_variant':'v2','train_worlds':96,'validation_worlds':12,'train_seeds':[10000,10095],'validation_seeds':[20000,20011],'families':families,'private_task_data_in_model_input':False,'examples':'one exact visible expert action per full observed prefix','loss':'next action JSON tokens plus im_end only; no prompt or padding loss','worlds':{},'splits':{}}
for split,start,count in [('train',10000,96),('valid',20000,12)]:
    examples=[];worlds=[];trajectories=[]
    for i in range(count):
        task=envmod.generate_task(start+i,families[i%len(families)])
        e=envmod.CurationEnv(task,max_steps=18)
        reset=e.reset()
        reference=envmod.run_reference(e)
        assert reference['result']['success'],task['public']['id']
        actions=[{'tool':h['action']['tool'],'args':h['action'].get('args',{})} for h in reference['steps']]
        e=envmod.CurationEnv(task,max_steps=18);assert e.reset()==reset
        messages=[{'role':'system','content':PROMPTS['v2']},{'role':'user','content':compact(reset)}]
        for j,action in enumerate(actions):
            prompt=''.join(f'<|im_start|>{m["role"]}\n{m["content"]}<|im_end|>\n' for m in messages)+'<|im_start|>assistant\n'+NONTHINKING_PREFILL
            target=compact(action)
            prompt_ids=tok.encode(prompt)
            tokens=tok.encode(prompt+target+'<|im_end|>')
            assert tokens[:len(prompt_ids)]==prompt_ids
            assert tok.decode(tokens[len(prompt_ids):])==target+'<|im_end|>'
            assert tokens[-1]==tok.eos_token_id
            examples.append({'task_id':task['public']['id'],'step':j+1,'messages':deepcopy(messages),'prompt':prompt,'target':target,'token_ids':tokens,'prompt_length':len(prompt_ids),'target_tokens':len(tokens)-len(prompt_ids)})
            response=e.step(action)
            assert response==reference['steps'][j]['response']
            messages += [{'role':'assistant','content':target},{'role':'user','content':compact(response)}]
        assert e.result['success']
        worlds.append(task)
        trajectories.append(e.export_trajectory())
    with (OUT/f'{split}.jsonl').open('w') as f:
        for ex in examples:f.write(compact(ex)+'\n')
    (OUT/f'{split}-worlds.json').write_text(json.dumps(worlds,indent=2)+'\n')
    (OUT/f'{split}-trajectories.json').write_text(json.dumps(trajectories,indent=2)+'\n')
    lengths=[len(e['token_ids']) for e in examples]
    manifest['worlds'][split]=[{'id':w['public']['id'],'fingerprint':w['fingerprint']} for w in worlds]
    manifest['splits'][split]={'examples':len(examples),'min_tokens':min(lengths),'max_tokens':max(lengths),'total_tokens':sum(lengths),'supervised_tokens':sum(e['target_tokens'] for e in examples),'max_action_tokens':max(e['target_tokens'] for e in examples),'jsonl_sha256':hashlib.sha256((OUT/f'{split}.jsonl').read_bytes()).hexdigest()}
manifest['max_seq_length']=128*math.ceil(max(s['max_tokens'] for s in manifest['splits'].values())/128)
assert manifest['max_seq_length']<=32768
assert not network_attempts
manifest['network_attempts']=network_attempts
(OUT/'data-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
print(json.dumps({k:v for k,v in manifest.items() if k!='worlds'},indent=2))
