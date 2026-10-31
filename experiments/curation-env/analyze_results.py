"""Recompute descriptive results from every archived episode; no model calls.

Run after unpacking the reproduction bundle. No filtering by success, trajectory
length, parse validity, or submission status is performed.
"""
from collections import Counter
from pathlib import Path
import hashlib
import json

ROOT = Path(__file__).resolve().parent
EXPECTED = json.loads((ROOT / 'tasks/evaluation.json').read_text())
SPLITS = {x['task']['public']['id']: x['split'] for x in EXPECTED}

def load(path):
    return json.loads(path.read_text())

def summarize(directory):
    run = load(directory / 'summary.json')
    assert run['episodes_completed'] == len(SPLITS) == 48
    episodes = run['episodes']
    assert len({e['task_id'] for e in episodes}) == 48
    assert {e['task_id'] for e in episodes} == set(SPLITS)
    by_id = {e['task_id']: e for e in episodes}
    totals = Counter()
    failures = Counter()
    for e in episodes:
        raw = load(directory / f"episode-{e['task_id']}.json")
        assert raw['summary'] == e
        trace = raw['environment_trajectory']
        assert e['steps'] == len(trace['steps'])
        if trace['result'] is not None:
            assert trace['result'] == e['outcome']
        else:
            assert not e['success'] and e['reward'] == 0
        for turn in raw['turns']:
            prediction = turn.get('prediction')
            if prediction:
                hit_limit = prediction['generation_tokens'] >= prediction['max_tokens']
                totals['turns_hitting_generation_limit'] += hit_limit
                totals['malformed_json_at_generation_limit'] += hit_limit and prediction['parse_error'] is not None
        seen = set()
        repeated = 0
        for step in trace['steps']:
            a = step['action']
            if isinstance(a, dict) and a.get('tool') == 'lookup' and step['error'] is None:
                key = json.dumps(a, sort_keys=True, separators=(',', ':'))
                repeated += key in seen
                seen.add(key)
        totals['repeated_identical_successful_lookups'] += repeated
        totals['episodes_with_repeated_lookups'] += repeated > 0
        for k in ['generation_tokens', 'steps', 'invalid_json_count', 'invalid_action_count']:
            totals[k] += e[k]
        if not e['success']:
            out = e['outcome']
            if out['termination'] != 'submitted':
                failures['unsubmitted'] += 1
            else:
                failures['submitted_incomplete'] += 1
                for flag in ['safe', 'unique', 'provenance']:
                    failures[f'failed_{flag}'] += not out[flag]
                failures['incomplete_coverage'] += out['coverage'] < 1
                failures['incorrect_retained_labels'] += out['label_accuracy'] < 1
    pairs = [(by_id[f'composition-{i}'], by_id[f'policy_shift-{i}']) for i in range(2000, 2012)]
    split_results = {}
    for split in ['single_or_pair', 'composition', 'policy_shift']:
        group = [e for e in episodes if SPLITS[e['task_id']] == split]
        split_results[split] = {'episodes': len(group), 'successes': sum(e['success'] for e in group),
                                'mean_reward': sum(e['reward'] for e in group) / len(group)}
    return {'episodes': 48, 'successes': sum(e['success'] for e in episodes),
            'mean_reward': sum(e['reward'] for e in episodes) / len(episodes),
            'both_contracts_solved': sum(a['success'] and b['success'] for a, b in pairs),
            'policy_pairs': 12, 'splits': split_results, 'totals': dict(totals),
            'terminations': dict(Counter(e['termination'] for e in episodes)),
            'failure_diagnostics_nonexclusive': dict(failures),
            'elapsed_episode_seconds': sum(e['elapsed_seconds'] for e in episodes),
            'model': load(directory / 'run-manifest.json')}

def main():
    controls = load(ROOT / 'control-results.json')
    run_paths = {'base':'model/curation-eval-base','adapted':'model/curation-eval-sft',
                 'scale8b':'model/scale8b/curation-eval-base'}
    if (ROOT/'model/currentmoe/curation-eval-base/summary.json').exists():
        run_paths['currentmoe'] = 'model/currentmoe/curation-eval-base'
    results = {
        'version': 1,
        'environment_manifest_sha256': controls['environment_manifest_sha256'],
        'scope': 'Synthetic workflow completion; 48 episodes from 36 worlds. The 12 policy pairs are correlated. One seed per model. No downstream model utility was measured.',
        'unfinished_rollout_rule': 'Token-budget exhaustion without submission receives harness score zero, not a graded dataset score.',
        'models': {name: {**summarize(ROOT / path),'archive_directory':path} for name, path in run_paths.items()},
        'controls': [{k: p[k] for k in ['policy', 'successes', 'mean_reward']} for p in controls['policies']],
        'training': load(ROOT / 'model/curation-sft/training-summary.json'),
        'frozen_comparison_plan': load(ROOT / 'model/frozen-comparison-plan.json'),
        'exploratory_scale_plan': load(ROOT / 'model/scale8b/frozen-scale-plan.json'),
        'analysis_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    if 'currentmoe' in run_paths:
        results['exploratory_current_plan'] = load(ROOT/'model/currentmoe/frozen-current-plan.json')
    (ROOT / 'results.json').write_text(json.dumps(results, indent=2, sort_keys=True) + '\n')
    print(json.dumps({k: {field: v[field] for field in ['successes', 'mean_reward', 'both_contracts_solved', 'terminations']} for k, v in results['models'].items()}, indent=2))

if __name__ == '__main__':
    main()
