import os,json,hashlib,time
from pathlib import Path
os.environ['HF_HUB_DISABLE_IMPLICIT_TOKEN']='1';os.environ['HF_HUB_DISABLE_TELEMETRY']='1'
from huggingface_hub import HfApi,snapshot_download
ROOT=Path(__file__).resolve().parent
REPO='Qwen/Qwen3-8B-MLX-4bit';REVISION='383413e909f3bc5303ce195ebbdf0339c5a1a2a3'
info=HfApi(token=False).model_info(REPO,revision=REVISION,files_metadata=True)
assert info.sha==REVISION
expected={s.rfilename:s.lfs.sha256 for s in info.siblings if s.lfs}
(ROOT/'upstream-lfs-hashes.json').write_text(json.dumps(expected,indent=2)+'\n')
start=time.perf_counter()
snapshot_download(repo_id=REPO,revision=REVISION,token=False,local_dir=ROOT/'model',allow_patterns=['*.json','*.safetensors','*.txt','*.model','README.md','LICENSE*'])
files={}
for p in sorted((ROOT/'model').iterdir()):
 if p.is_file():
  h=hashlib.sha256(p.read_bytes()).hexdigest()
  if p.name in expected:assert h==expected[p.name]
  files[p.name]={'sha256':h,'bytes':p.stat().st_size}
manifest={'repository':REPO,'revision':REVISION,'license':'Apache-2.0','download_seconds':time.perf_counter()-start,'files':files,'total_bytes':sum(x['bytes'] for x in files.values()),'upstream_lfs_hashes_verified':True}
(ROOT/'model-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
print(json.dumps(manifest,indent=2))
