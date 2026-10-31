"""Write deterministic development and final-evaluation worlds with a frozen manifest."""
from pathlib import Path
import json
import hashlib
from latent_curation.environment import generate_task, digest, CurationEnv, run_reference

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'tasks'
OUT.mkdir(exist_ok=True)
development = [generate_task(i, family) for i, family in enumerate(['clean','labels','duplicates','permissions','leakage','versions','pair','composition'])]
test = []
for i in range(24):
    family = ['labels','duplicates','permissions','leakage','versions','pair'][i % 6]
    test.append(dict(split='single_or_pair', task=generate_task(1000+i, family)))
for i in range(12): test.append(dict(split='composition', task=generate_task(2000+i, 'composition')))
for i in range(12): test.append(dict(split='policy_shift', task=generate_task(2000+i, 'policy_shift')))
for item in test:
    assert run_reference(CurationEnv(item['task']))['result']['success']
manifest = {'version':1,'development_tasks':len(development),'evaluation_tasks':len(test),
            'source_sha256':hashlib.sha256(Path(__file__).with_name('latent_curation').joinpath('environment.py').read_bytes()).hexdigest(),
            'task_hash_encoding':'SHA-256 of UTF-8 JSON with sorted keys and compact separators',
            'development':[{'id':t['public']['id'],'sha256':digest(t)} for t in development],
            'evaluation':[{'id':x['task']['public']['id'],'split':x['split'],'sha256':digest(x['task'])} for x in test],
            'design':'48 episodes from 36 new evaluation worlds: 24 single/pair worlds and 12 composed worlds each evaluated under two authority contracts with identical records. Paired episodes are correlated. Development includes one composed example for harness debugging, so this is a complexity/policy-shift test, not a claim of unseen mechanism combinations.'}
for name, data in [('development.json',development),('evaluation.json',test),('manifest.json',manifest)]:
    (OUT/name).write_text(json.dumps(data,indent=2,sort_keys=True)+'\n')
print(json.dumps({'development':len(development),'evaluation':len(test),'manifest_sha256':digest(manifest)}))
