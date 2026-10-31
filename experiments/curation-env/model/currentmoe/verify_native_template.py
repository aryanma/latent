"""Verify current model's official plain-chat nonthinking format, without inference."""
import os,json,hashlib
from pathlib import Path
os.environ['HF_HUB_OFFLINE']='1';os.environ['TRANSFORMERS_OFFLINE']='1';os.environ['HF_HUB_DISABLE_IMPLICIT_TOKEN']='1'
from transformers import AutoTokenizer
ROOT=Path(__file__).resolve().parent
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
a=ROOT/'model/chat_template.jinja';b=ROOT/'official-template-source/chat_template.jinja'
assert a.read_bytes()==b.read_bytes()
tok=AutoTokenizer.from_pretrained(str(ROOT/'model'),local_files_only=True)
messages=[{'role':'system','content':'Return exactly one JSON action and stop.'},{'role':'user','content':'{"contract":"Only inspected approved source evidence is authoritative.","tools":[]}'},{'role':'assistant','content':'{"tool":"inspect","args":{}}'},{'role':'user','content':'{"observation":{"rows":[]},"reward":0.0,"done":false}'}]
expected=''.join(f'<|im_start|>{m["role"]}\n{m["content"]}<|im_end|>\n' for m in messages)+'<|im_start|>assistant\n<think>\n\n</think>\n\n'
native=tok.apply_chat_template(messages,tokenize=False,add_generation_prompt=True,enable_thinking=False,preserve_thinking=False)
assert native==expected
assert all(m['content'] in native for m in messages)
# Demonstrate why preserving raw output requires avoiding native trim/split transformations.
edge=[dict(m) for m in messages];edge[2]['content']='  {"tool":"inspect","args":{}}\n'
edge_native=tok.apply_chat_template(edge,tokenize=False,add_generation_prompt=True,enable_thinking=False,preserve_thinking=False)
report={'official_repository':'Qwen/Qwen3.6-35B-A3B','official_revision':'995ad96eacd98c81ed38be0c5b274b04031597b0','community_revision':'38740b847e4cb78f352aba30aa41c76e08e6eb46','chat_template_sha256':sha(a),'byte_identical_official_community_template':True,'native_enable_thinking_false_plain_chat_matches_verbatim_renderer':True,'native_preserves_outer_whitespace':edge[2]['content'] in edge_native,'history_policy':'Use verified native-compatible ChatML and nonthinking prefill, preserving every raw message byte including whitespace/reasoning-like spans instead of native trim/split. No added tools= template serialization; exact same JSON-action prompt protocol as earlier runs.','messages':messages,'native_render':native,'native_token_ids':tok.encode(native),'tokenizer_class':type(tok).__name__,'eos_token':tok.eos_token,'eos_token_id':tok.eos_token_id}
(ROOT/'native-template-verification.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({k:v for k,v in report.items() if k not in ['messages','native_render','native_token_ids']},indent=2))
