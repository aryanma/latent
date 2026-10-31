"""Public weight download only; never uses credentials or an inference endpoint."""
import hashlib,os
from pathlib import Path
os.environ['HF_HUB_DISABLE_IMPLICIT_TOKEN']='1'
os.environ['HF_HUB_DISABLE_TELEMETRY']='1'
from huggingface_hub import snapshot_download
root=Path(__file__).resolve().parent
snapshot_download(repo_id='Qwen/Qwen3-1.7B-MLX-4bit',revision='21457c6f51ed54a7c16e988c0844db973815c137',token=False,local_dir=root/'model',allow_patterns=['*.json','*.safetensors','*.txt','*.model','README.md','LICENSE*'])
assert hashlib.sha256((root/'model/model.safetensors').read_bytes()).hexdigest()=='42e688d626b3e144bf721af7517a82f3ea7e97bb5764fef1c89942bf9165072a'
print('Pinned model verified.')
