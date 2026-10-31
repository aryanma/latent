#!/usr/bin/env python3
"""Package the published experiment. Run from any directory; no network calls."""
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data/signal'
EXPERIMENT = ROOT / 'experiments/reward-boundary'

def read(name):
    return json.loads((DATA / name).read_text())

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def write(name, obj):
    (DATA / name).write_text(json.dumps(obj, indent=2, ensure_ascii=False) + '\n')

receipt = read('reproducibility.json')
for name, info in receipt['files'].items():
    assert digest(DATA / name) == info['sha256'], f'Published artifact differs from verified run: {name}'
assert digest(EXPERIMENT / 'run_audit.py') == receipt['audit_script_sha256']
assert receipt['all_outputs_byte_identical']

labels = {
    'reference_neutral': ('Reference replay', 'All supplied reference actions, followed by a neutral statement.'),
    'reference_irrelevant': ('Reference + unrelated reply', 'The same reference actions; only the final reply changes.'),
    'no_tool': ('No tool calls', 'No actions; a statement that no actions were performed. Unchanged state can be valid for a refusal.'),
    'no_tool_irrelevant': ('No tools + unrelated reply', 'No actions and an unrelated final reply. This is a constructed scoring probe.'),
    'omit_first_mutating_action': ('Omit the first state change', 'Remove the first state-changing reference action and execute the remaining sequence afresh.'),
    'reference_max_steps': ('Change termination metadata', 'Reference actions, but the record is marked MAX_STEPS. No actual timeout is simulated.'),
    'explicit_refusal': ('Explicit refusal', 'A constructed refusal consistent with the cited written obligation.'),
    'contradictory_approval': ('Contradictory approval', 'A spoken approval, opposing the written assertion. No actual cancellation occurs.'),
    'contradictory_refund_offer': ('Contradictory refund offer', 'A spoken refund offer, opposing the written assertion. No refund is issued.'),
    'paraphrased_refusal': ('Paraphrased refusal', 'A meaning-preserving refusal variation; this does not test semantic judge quality.'),
    'reference_plus_harmless_read': ('Reference + harmless read', 'Reference cancellation followed by an additional reservation lookup; the final outcome is preserved.'),
}

raw = read('results.json')
keys = {key for t in raw for key in t['probes']}
unknown = keys - labels.keys()
assert not unknown, f'Add explicit labels for probe names: {unknown}'
rows = []
for t in raw:
    probes = []
    for key in labels:
        if key not in t['probes']:
            continue
        p = t['probes'][key]
        assert 'error' not in p and not p['tool_errors']
        label, description = labels[key]
        probes.append(dict(key=key, label=label, description=description,
            reward=p['reward'], components=p['reward_breakdown'] or {},
            final_text=p['final_text'], termination=p['termination'],
            action_names=p['action_names'], evidence=p))
    a = 'reference_neutral'
    b = 'reference_irrelevant'
    if 'explicit_refusal' in t['probes']:
        a = 'explicit_refusal'
        b = 'contradictory_approval' if t['task_id'] == '1' else 'contradictory_refund_offer'
    elif t['task_id'] in ['17', '19']:
        b = 'omit_first_mutating_action'
    rows.append(dict(id=t['task_id'], default_a=a, default_b=b, probes=probes))
write('replays.json', dict(schema_version=1, evidence='recorded-upstream-evaluator-output',
    upstream_commit=read('summary.json')['upstream_commit'], tasks=rows))

manifest = {
    'experiment': 'Latent / The reward boundary / 001',
    'date': '2026-10-30',
    'upstream_commit': read('summary.json')['upstream_commit'],
    'upstream_files_sha256': read('source-manifest.json'),
    'reproducibility': receipt,
    'artifact_sha256': {p.name: digest(p) for p in sorted(DATA.glob('*.json')) if p.name != 'manifest.json'},
    'harness_sha256': {p.name: digest(p) for p in sorted(EXPERIMENT.iterdir()) if p.is_file()},
    'interpretation': 'Constructed scoring probes on 44 eligible tasks. No models or user simulator. Not a benchmark-wide failure rate or training result.',
}
write('manifest.json', manifest)

with zipfile.ZipFile(DATA / 'reproduction.zip', 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
    files = [(p, p.name) for p in sorted(EXPERIMENT.iterdir()) if p.is_file()]
    files += [(DATA / name, 'recorded/' + name) for name in receipt['files']]
    files += [(DATA / name, 'recorded/' + name) for name in ['manifest.json', 'reproducibility.json', 'airline-tasks.json']]
    for path, name in files:
        info = zipfile.ZipInfo('latent-reward-boundary/' + name, date_time=(2026, 10, 30, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        z.writestr(info, path.read_bytes())
print(f'Packaged {len(rows)} tasks, {sum(len(t["probes"]) for t in rows)} probes; bundle {(DATA / "reproduction.zip").stat().st_size:,} bytes.')
