"""Verify the unpacked release and replay all recorded actions without a model.

Python standard library only. Hashes establish archive consistency, not a signed
attestation. Regenerating model outputs requires the separately pinned weights.
"""
from pathlib import Path
import hashlib
import json
from latent_curation.environment import CurationEnv, digest

ROOT = Path(__file__).resolve().parent
EXPECTED_MANIFEST = '6893521e0391e831b45a414390246e0fb0a06d1c203892b66082a91f8ae22730'

def read(p): return json.loads(p.read_text())
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    files = read(ROOT/'ARTIFACTS.json')['files']
    for name, expected in files.items():
        p = ROOT/name
        assert p.is_file() and sha(p) == expected['sha256'], f'Artifact changed: {name}'
        assert p.stat().st_size == expected['bytes']
    manifest = read(ROOT/'tasks/manifest.json')
    assert digest(manifest) == EXPECTED_MANIFEST
    assert sha(ROOT/'latent_curation/environment.py') == manifest['source_sha256']
    tasks = {x['task']['public']['id']:x['task'] for x in read(ROOT/'tasks/evaluation.json')}
    for item in manifest['evaluation']:
        assert digest(tasks[item['id']]) == item['sha256']
    count = 0
    def replay(trace):
        nonlocal count
        env = CurationEnv(tasks[trace['task_id']],max_steps=trace['max_steps'])
        for step in trace['steps']:
            assert env.step(step['action']) == step['response'], (trace['task_id'],step['step'])
        assert env.export_trajectory() == trace, trace['task_id']
        count += 1
    for policy in read(ROOT/'control-results.json')['policies']:
        for e in policy['episodes']: replay(e['trajectory'])
    models = read(ROOT/'results.json')['models']
    for model in models.values():
        path = model['archive_directory']
        directory = ROOT/path
        run = read(directory/'run-manifest.json')
        assert run['environment_manifest_digest'] == EXPECTED_MANIFEST
        assert sha(directory/'driver-used.py') == run['driver_sha256']
        assert sha(directory/'runtime-used.py') == run['runtime_sha256']
        summary = read(directory/'summary.json')
        assert summary['episodes_completed'] == 48
        for episode in summary['episodes']:
            raw = read(directory/f"episode-{episode['task_id']}.json")
            assert raw['summary'] == episode
            replay(raw['environment_trajectory'])
    assert count == 288 + 48*len(models)
    training = read(ROOT/'model/curation-sft/training-summary.json')
    assert sha(ROOT/'model/curation-sft/adapter/adapters.safetensors') == training['final_checkpoint_sha256']
    print(f'Verified {len(files)} artifact hashes and replayed {count} recorded trajectories. No model, GPU, or network used.')

if __name__ == '__main__': main()
