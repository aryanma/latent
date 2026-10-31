"""Measure deterministic controls on the exact frozen evaluation suite."""
from copy import deepcopy
from pathlib import Path
import hashlib
import json
from latent_curation.environment import CurationEnv, solve_visible, run_reference, digest

ROOT = Path(__file__).resolve().parent

def read_sources(env):
    rows = env.step({'tool': 'inspect'})['observation']['rows']
    regs = env.step({'tool':'lookup','args':{'table':'registry','keys':[r['ticket_id'] for r in rows]}})['observation']['records']
    env.step({'tool':'lookup','args':{'table':'evaluation','keys':list(dict.fromkeys(r['lineage_id'] for r in regs))}})
    env.step({'tool':'lookup','args':{'table':'events','keys':list(dict.fromkeys(r['case_id'] for r in regs))}})

def apply_answer(env, answer):
    for reason in ['permission','evaluation_overlap','duplicate','other']:
        ids = [i for i,a in answer.items() if not a['keep'] and a.get('reason','other') == reason]
        if ids: env.step({'tool':'exclude','args':{'ids':ids,'reason':reason}})
    originals = {r['id']:r for r in env.task['public']['candidates']}
    changes = [dict(id=i,label=a['label'],evidence_id=a['evidence_id']) for i,a in answer.items()
               if a['keep'] and a['label'] != originals[i]['label']]
    if changes: env.step({'tool':'repair','args':{'updates':changes}})
    env.step({'tool':'submit'})

def run(task, policy):
    env = CurationEnv(task)
    if policy == 'schema_aware': return run_reference(env)
    if policy == 'keep_all': env.step({'tool':'submit'})
    elif policy == 'discard_all':
        env.step({'tool':'exclude','args':{'ids':[r['id'] for r in env.rows],'reason':'other'}})
        env.step({'tool':'submit'})
    elif policy == 'normalized_text_dedup':
        seen, remove = set(), []
        for r in env.rows:
            key = ' '.join(r['text'].lower().split())
            if key in seen: remove.append(r['id'])
            seen.add(key)
        if remove: env.step({'tool':'exclude','args':{'ids':remove,'reason':'duplicate'}})
        env.step({'tool':'submit'})
    elif policy in ['newest_event', 'fixed_authority']:
        read_sources(env)
        public = deepcopy(task['public'])
        if policy == 'fixed_authority': public['contract']['authority'] = 'case_resolution'
        answer = solve_visible(public)
        if policy == 'newest_event':
            regs = {r['ticket_id']:r for r in public['tables']['registry']}
            for row in public['candidates']:
                a = answer[row['id']]
                if a['keep']:
                    latest = max((e for e in public['tables']['events'] if e['case_id'] == regs[row['ticket_id']]['case_id']), key=lambda e:e['revision'])
                    a['label'] = public['contract']['aliases'].get(latest['category'],latest['category'])
                    a['evidence_id'] = latest['id']
        apply_answer(env, answer)
    else: raise ValueError(policy)
    return env.export_trajectory()

if __name__ == '__main__':
    manifest = json.loads((ROOT/'tasks/manifest.json').read_text())
    assert manifest['source_sha256'] == hashlib.sha256((ROOT/'latent_curation/environment.py').read_bytes()).hexdigest()
    tasks = json.loads((ROOT/'tasks/evaluation.json').read_text())
    policies = ['schema_aware','keep_all','discard_all','normalized_text_dedup','newest_event','fixed_authority']
    results = []
    for p in policies:
        episodes = []
        for item in tasks:
            trace = run(item['task'],p)
            episodes.append(dict(task_id=item['task']['public']['id'],split=item['split'],result=trace['result'],steps=len(trace['steps']),trajectory=trace))
        results.append(dict(policy=p,episodes=episodes,successes=sum(e['result']['success'] for e in episodes),
                            mean_reward=sum(e['result']['reward'] for e in episodes)/len(episodes)))
    output = {'environment_manifest_sha256':digest(manifest),'scope':'Deterministic policies over synthetic tasks; schema_aware knows the declared schema and procedure.', 'policies':results}
    (ROOT/'control-results.json').write_text(json.dumps(output,indent=2,sort_keys=True)+'\n')
    print(json.dumps([{k:v for k,v in r.items() if k != 'episodes'} for r in results],indent=2))
