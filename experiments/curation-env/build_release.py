"""Package completed research runs; exclude downloaded base weights and environments.

Usage: python3 build_release.py --small-run /path/to/1.7b-run --large-run /path/to/8b-run
This packages existing evidence; it never performs model inference or changes results.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parent
SITE = ROOT.parents[1]
OUT = SITE / 'data/curation'

def read(path): return json.loads(path.read_text())
def write(path, value): path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()

def copy_file(source, target):
    assert source.is_file(), source
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        assert sha(source) == sha(target), f'Refusing to replace a different archived artifact: {target}'
    else:
        shutil.copy2(source, target)

def copy_tree(source, target):
    assert source.is_dir(), source
    for p in sorted(source.rglob('*')):
        if p.is_file() and '__pycache__' not in p.parts and not p.name.endswith('.pyc'):
            copy_file(p, target / p.relative_to(source))

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--small-run', type=Path, required=True)
    parser.add_argument('--large-run', type=Path, required=True)
    parser.add_argument('--current-run', type=Path)
    args = parser.parse_args()
    small, large = args.small_run, args.large_run
    if (ROOT/'model/currentmoe').exists() and not args.current_run:
        raise ValueError('This archive includes currentmoe; pass --current-run to preserve its replay data.')
    runs = {'base': small/'curation-eval-base', 'adapted': small/'curation-eval-sft',
            'scale8b': large/'curation-eval-base'}
    if args.current_run:
        runs['currentmoe'] = args.current_run/'curation-eval-base'
    for p in runs.values():
        assert read(p/'summary.json')['episodes_completed'] == 48, 'Never package a partial evaluation'
    dest = ROOT/'model'
    for name in ['local_runtime.py','curation_driver.py','prepare_sft.py','train_sft.py',
                 'download_pinned_model.py','model-manifest.json','requirements.lock.txt','frozen-comparison-plan.json',
                 'measure_reference_tokens.py','reference-token-budgets.json']:
        copy_file(small/name,dest/name)
    copy_file(small/'REPRODUCE.md',dest/'README.md')
    copy_file(small/'model/LICENSE',dest/'QWEN-LICENSE.txt')
    for name in ['curation-eval-base','curation-eval-sft','curation-dev-final-v1','curation-dev-final-v2']:
        copy_tree(small/name,dest/name)
    sft = small/'curation-sft'
    for p in sorted(sft.iterdir()):
        if p.is_file() and p.suffix in {'.py','.json','.jsonl'}:
            copy_file(p,dest/'curation-sft'/p.name)
    for name in ['adapter_config.json','adapters.safetensors']:
        copy_file(sft/'adapter'/name,dest/'curation-sft/adapter'/name)
    for name in ['local_runtime.py','curation_driver.py','download_pinned_model.py',
                 'model-manifest.json','requirements.lock.txt','frozen-scale-plan.json']:
        copy_file(large/name,dest/'scale8b'/name)
    copy_file(large/'model/LICENSE',dest/'scale8b/QWEN-LICENSE.txt')
    copy_tree(large/'environment-snapshot',dest/'scale8b/environment-snapshot')
    copy_tree(large/'curation-eval-base',dest/'scale8b/curation-eval-base')
    if (large/'README.md').exists(): copy_file(large/'README.md',dest/'scale8b/README.md')
    if args.current_run:
        current = args.current_run
        for p in sorted(current.iterdir()):
            if p.is_file() and p.suffix in {'.py','.json','.md','.txt','.jinja'}:
                copy_file(p,dest/'currentmoe'/p.name)
        copy_tree(current/'environment-snapshot',dest/'currentmoe/environment-snapshot')
        copy_tree(current/'curation-eval-base',dest/'currentmoe/curation-eval-base')
        if (current/'model/LICENSE').exists(): copy_file(current/'model/LICENSE',dest/'currentmoe/QWEN-LICENSE.txt')
    subprocess.run([sys.executable,str(ROOT/'analyze_results.py')],check=True)
    shutil.copy2(ROOT/'results.json',OUT/'results.json')
    ids = [t['public']['id'] for t in read(OUT/'playground.json')['tasks']]
    replays = {}
    for name, path in runs.items():
        replays[name] = {}
        for task_id in ids:
            episode = read(path/f'episode-{task_id}.json')
            trace = episode['environment_trajectory']
            trace['recorded_outcome'] = episode['summary']['outcome']
            trace['model_run'] = name
            replays[name][task_id] = trace
    write(OUT/'model-replays.json',replays)
    # A self-contained index allows offline verification after unpacking.
    artifacts = [p for p in sorted(ROOT.rglob('*')) if p.is_file()
                 and '__pycache__' not in p.parts and '.venv' not in p.parts
                 and p.suffix != '.pyc' and not p.name.startswith('.') and p.name != 'ARTIFACTS.json']
    assert not any(p.name == 'model.safetensors' for p in artifacts), 'Never bundle base weights'
    write(ROOT/'ARTIFACTS.json',{'files':{str(p.relative_to(ROOT)):{'bytes':p.stat().st_size,'sha256':sha(p)} for p in artifacts}})
    artifacts.append(ROOT/'ARTIFACTS.json')
    # Deterministic archive timestamps make identical evidence produce identical zips.
    with zipfile.ZipFile(OUT/'reproduction.zip','w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for p in artifacts:
            info=zipfile.ZipInfo(str(Path('curation-env')/p.relative_to(ROOT)),(2026,10,30,0,0,0))
            info.compress_type=zipfile.ZIP_DEFLATED
            z.writestr(info,p.read_bytes())
    files = {str(p.relative_to(ROOT)): {'bytes':p.stat().st_size,'sha256':sha(p)} for p in artifacts}
    write(OUT/'manifest.json',{
        'environment_manifest_sha256':read(ROOT/'results.json')['environment_manifest_sha256'],
        'artifact_root':'experiments/curation-env', 'files':files,
        'release_files':{p.name:{'bytes':p.stat().st_size,'sha256':sha(p)} for p in sorted(OUT.iterdir()) if p.is_file() and p.name!='manifest.json'},
        'omitted':'Base model weights and Python environments; download pinned weights with model/download_pinned_model.py. Intermediate adapters and optimizer tensors remain in the research archive but are not in this bundle; the final adapter is included.',
    })
    print(json.dumps({'artifacts':len(artifacts),'zip_bytes':(OUT/'reproduction.zip').stat().st_size,'zip_sha256':sha(OUT/'reproduction.zip')}))

if __name__ == '__main__': main()
