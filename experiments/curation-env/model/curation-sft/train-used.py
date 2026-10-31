"""Fixed QLoRA supervised behavior-cloning run. No reward optimization or eval selection."""
import hashlib,json,math,time
from pathlib import Path
import sys
sys.dont_write_bytecode=True
from local_runtime import LocalQwen,network_attempts,MODEL_REVISION,MODEL_REPOSITORY
import mlx.core as mx
import mlx.nn as nn
import mlx.optimizers as optim
from mlx.utils import tree_flatten
import numpy as np
from mlx_lm.tuner.trainer import TrainingArgs,TrainingCallback,train,evaluate
from mlx_lm.tuner.utils import linear_to_lora_layers
ROOT=Path(__file__).resolve().parent
OUT=ROOT/'curation-sft'
ADAPTER=OUT/'adapter'

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
class TokenizedPrefixes:
    def __init__(self,path,max_len):
        self.rows=[json.loads(x) for x in path.read_text().splitlines()]
        assert all(0<e['prompt_length']<len(e['token_ids'])<=max_len for e in self.rows)
    def __len__(self):return len(self.rows)
    def __getitem__(self,i):
        r=self.rows[i];return (r['token_ids'],r['prompt_length'])

# The library's default mask includes position == sequence length, which can
# supervise an extra padded token. We exclude padding explicitly. This loss
# leaves upstream trainer and model source unchanged.
def action_only_loss(model,batch,lengths):
    logits=model(batch[:,:-1])
    targets=batch[:,1:]
    positions=mx.arange(1,targets.shape[1]+1)
    mask=(positions>=lengths[:,0:1]) & (positions<lengths[:,1:])
    ce=nn.losses.cross_entropy(logits,targets)
    count=mask.sum()
    return (ce.astype(mx.float32)*mask).sum()/count,count

class Recorder(TrainingCallback):
    def __init__(self):self.records=[];self.start=time.perf_counter()
    def record(self,kind,info):
        row={'kind':kind,'elapsed_seconds':time.perf_counter()-self.start,**info}
        self.records.append(row)
        with (OUT/'training-metrics.jsonl').open('a') as f:f.write(json.dumps(row)+'\n')
    def on_train_loss_report(self,info):self.record('train',info)
    def on_val_loss_report(self,info):self.record('validation',info)

if __name__=='__main__':
    data=json.loads((OUT/'data-manifest.json').read_text())
    plan=json.loads((ROOT/'frozen-comparison-plan.json').read_text())['training_plan']
    assert not ADAPTER.exists(),'Never overwrite a completed or partial run'
    ADAPTER.mkdir()
    (OUT/'train-used.py').write_bytes(Path(__file__).read_bytes())
    max_len=data['max_seq_length']
    train_data=TokenizedPrefixes(OUT/'train.jsonl',max_len)
    val_data=TokenizedPrefixes(OUT/'valid.jsonl',max_len)
    # Fixed, independent monitor: one preselected decision prefix per validation
    # world, so every validation report evaluates the identical 12 examples.
    monitor_rng=np.random.RandomState(84)
    monitor=[]
    for task_id in dict.fromkeys(r['task_id'] for r in val_data.rows):
        candidates=[r for r in val_data.rows if r['task_id']==task_id]
        monitor.append(candidates[int(monitor_rng.randint(len(candidates)))])
    assert len(monitor)==12
    val_data.rows=monitor
    (OUT/'validation-monitor.json').write_text(json.dumps([{'task_id':r['task_id'],'step':r['step'],'token_count':len(r['token_ids'])} for r in monitor],indent=2)+'\n')
    assert sha(OUT/'train.jsonl')==data['splits']['train']['jsonl_sha256']
    assert sha(OUT/'valid.jsonl')==data['splits']['valid']['jsonl_sha256']
    # Check supervision mask: prompt positions and all padding are excluded.
    for dataset in (train_data,val_data):
        for tokens,offset in dataset:
            idx=list(range(1,len(tokens)+128))
            supervised=[i for i in idx if offset<=i<len(tokens)]
            assert supervised==list(range(offset,len(tokens)))
    config={'fine_tune_type':'lora','num_layers':plan['num_layers'],
        'lora_parameters':{'rank':plan['rank'],'scale':plan['scale'],'dropout':plan['dropout']},
        'model_repository':MODEL_REPOSITORY,'model_revision':MODEL_REVISION,
        'batch_size':1,'iters':plan['iterations'],'learning_rate':plan['learning_rate'],
        'optimizer':'Adam','optimizer_defaults':{'betas':[0.9,0.999],'eps':1e-8,'bias_correction':False},
        'max_seq_length':max_len,'grad_checkpoint':True,'seed':42,
        'steps_per_eval':20,'validation_completed_updates':[0,19,39,59,79,99,119,120],
        'val_batches':12,'steps_per_save':40,'steps_per_report':10,
        'selection':'final iteration120, no heldout selection',
        'loss':'only action JSON and EOS, prompt and padding excluded',
        'source_sha256':data['source_sha256'],'data_manifest_sha256':sha(OUT/'data-manifest.json'),
        'script_sha256':sha(Path(__file__)),'network_disabled':True}
    (ADAPTER/'adapter_config.json').write_text(json.dumps(config,indent=2)+'\n')
    np.random.seed(42);mx.random.seed(42)
    runtime=LocalQwen();model=runtime.model
    model.freeze()
    linear_to_lora_layers(model,plan['num_layers'],config['lora_parameters'])
    params=dict(tree_flatten(model.trainable_parameters()))
    assert params and all(k.endswith(('lora_a','lora_b')) for k in params)
    parameter_count=sum(v.size for v in params.values())
    (OUT/'trainable-parameters.json').write_text(json.dumps({'count':parameter_count,'shapes':{k:list(v.shape) for k,v in params.items()}},indent=2)+'\n')
    mx.eval(model.parameters())
    callback=Recorder()
    args=TrainingArgs(batch_size=1,iters=120,val_batches=12,steps_per_report=10,
         steps_per_eval=20,steps_per_save=40,max_seq_length=max_len,
         adapter_file=ADAPTER/'adapters.safetensors',grad_checkpoint=True,
         grad_accumulation_steps=1)
    optimizer=optim.Adam(learning_rate=plan['learning_rate'])
    begin=time.perf_counter()
    train(model=model,optimizer=optimizer,train_dataset=train_data,val_dataset=val_data,
          args=args,loss=action_only_loss,training_callback=callback)
    final_validation_loss=evaluate(model=model,dataset=val_data,batch_size=1,num_batches=12,max_seq_length=max_len,loss=action_only_loss)
    callback.record("final_validation",{"iteration":120,"val_loss":final_validation_loss})
    mx.synchronize()
    # Trainer stores intermediate/final adapters. Preserve final optimizer tensors
    # separately, plus deterministic seeds/config/data, for reproducibility.
    flat_optimizer=dict(tree_flatten(optimizer.state))
    mx.save_safetensors(str(OUT/'final-optimizer.safetensors'),flat_optimizer)
    assert not network_attempts
    summary={'elapsed_seconds':time.perf_counter()-begin,'trainable_parameters':parameter_count,
             'peak_mlx_memory_bytes':mx.get_peak_memory(),'network_attempts':network_attempts,
             'training_method':'QLoRA supervised behavior cloning, not reinforcement learning',
             'iterations':120,'final_checkpoint_sha256':sha(ADAPTER/'adapters.safetensors'),
             'checkpoints':{p.name:sha(p) for p in ADAPTER.glob('*.safetensors')},
             'metrics':callback.records}
    (OUT/'training-summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary),flush=True)
