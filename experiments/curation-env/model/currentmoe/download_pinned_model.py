import os,json,hashlib,time
from pathlib import Path
os.environ['HF_HUB_DISABLE_IMPLICIT_TOKEN']='1';os.environ['HF_HUB_DISABLE_TELEMETRY']='1'
from huggingface_hub import HfApi,snapshot_download
ROOT=Path(__file__).resolve().parent
REPO='mlx-community/Qwen3.6-35B-A3B-4bit';REVISION='38740b847e4cb78f352aba30aa41c76e08e6eb46'
info=HfApi(token=False).model_info(REPO,revision=REVISION,files_metadata=True)
assert info.sha==REVISION
expected={s.rfilename:s.lfs.sha256 for s in info.siblings if s.lfs}
(ROOT/'upstream-lfs-hashes.json').write_text(json.dumps(expected,indent=2)+'\n')
start=time.perf_counter()
snapshot_download(repo_id=REPO,revision=REVISION,token=False,local_dir=ROOT/'model',allow_patterns=['*.json','*.safetensors','*.txt','*.model','*.jinja','README.md','LICENSE*'])
files={}
for p in sorted((ROOT/'model').iterdir()):
 if p.is_file():
  digest=hashlib.sha256()
  with p.open('rb') as f:
   for chunk in iter(lambda:f.read(8*1024*1024),b''):digest.update(chunk)
  h=digest.hexdigest()
  if p.name in expected:assert h==expected[p.name]
  files[p.name]={'sha256':h,'bytes':p.stat().st_size}
manifest={'repository':REPO,'revision':REVISION,'license':'Apache-2.0','download_seconds':time.perf_counter()-start,'files':files,'total_bytes':sum(x['bytes'] for x in files.values()),'upstream_lfs_hashes_verified':True}
(ROOT/'model-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
print(json.dumps(manifest,indent=2))

# Small official template/license sources only; never fetch full-precision weights.
snapshot_download(repo_id="Qwen/Qwen3.6-35B-A3B",revision="995ad96eacd98c81ed38be0c5b274b04031597b0",token=False,local_dir=ROOT/"official-template-source",allow_patterns=["chat_template.jinja","LICENSE"])
(ROOT/"LICENSE.txt").write_bytes((ROOT/"official-template-source/LICENSE").read_bytes())
