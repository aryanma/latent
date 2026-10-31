"""Summarize completed frozen runs; never select a checkpoint or alter a model."""
from collections import Counter
import hashlib,json,statistics
from pathlib import Path
ROOT=Path(__file__).resolve().parent

def aggregate(folder):
    summary=json.loads((folder/'summary.json').read_text())
    episodes=summary['episodes'];assert len(episodes)==48
    manifest=json.loads((folder/'run-manifest.json').read_text())
    source=json.loads((folder/'environment-snapshot/tasks/evaluation.json').read_text())
    split_by_id={r['task']['public']['id']:r['split'] for r in source}
    def group(es):
        return {'episodes':len(es),'successes':sum(e['success'] for e in es),'mean_reward':statistics.mean(e['reward'] for e in es),'steps':sum(e['steps'] for e in es),'invalid_json':sum(e['invalid_json_count'] for e in es),'invalid_actions':sum(e['invalid_action_count'] for e in es),'generated_tokens':sum(e['generation_tokens'] for e in es),'prompt_tokens_total':sum(e['prompt_tokens_total'] for e in es),'summed_episode_seconds':sum(e['elapsed_seconds'] for e in es),'terminations':dict(Counter(e['termination'] for e in es)),'inference_errors':sum(e['driver_termination']=='inference_error' for e in es),'max_prompt_tokens':max(e['max_prompt_tokens'] for e in es)}
    submitted=[e['outcome'] for e in episodes if e['termination']=='submitted']
    components={'submitted_and_graded':len(submitted),'not_graded':len(episodes)-len(submitted),
        'coverage_below_one':sum(e['coverage']<1 for e in submitted),
        'label_accuracy_below_one':sum(e['label_accuracy']<1 for e in submitted),
        'unsafe':sum(not e['safe'] for e in submitted),
        'nonunique':sum(not e['unique'] for e in submitted),
        'unsupported_provenance':sum(not e['provenance'] for e in submitted),
        'note':'Overlapping counts conditional on actual submit; unfinished episodes have no private component grades.'}
    by_id={e['task_id']:e for e in episodes}
    pairs=[(e,by_id['policy_shift-'+e['task_id'].split('-')[-1]]) for e in episodes if e['task_id'].startswith('composition-')]
    assert len(pairs)==12
    paired={'pairs':len(pairs),'both_successful':sum(a['success'] and b['success'] for a,b in pairs),'either_successful':sum(a['success'] or b['success'] for a,b in pairs)}
    return {'submitted_component_failures':components,'paired_worlds':paired,'overall':group(episodes),'splits':{s:group([e for e in episodes if split_by_id[e['task_id']]==s]) for s in sorted(set(split_by_id.values()))},'network_attempts':summary['network_attempts'],'run_manifest_sha256':hashlib.sha256((folder/'run-manifest.json').read_bytes()).hexdigest(),'driver_sha256':manifest['driver_sha256'],'runtime_sha256':manifest['runtime_sha256'],'system_prompt':manifest['system_prompt']}

if __name__=='__main__':
    result=aggregate(ROOT/'curation-eval-base')
    result.pop('system_prompt')
    result['design']='Exploratory2026 newer-architecture baseline added after small-model difficulty; frozen before current-model inference; no prompt selection or model training.'
    (ROOT/'current-summary.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))
