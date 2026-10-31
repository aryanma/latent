import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {CurationEnv} from './env.mjs';
const root=new URL('../experiments/curation-env/',import.meta.url);
const read=path=>JSON.parse(readFileSync(new URL(path,root),'utf8'));
const tasks=new Map(read('tasks/evaluation.json').map(x=>[x.task.public.id,x.task]));
const tools=JSON.parse(readFileSync(new URL('../data/curation/playground.json',import.meta.url),'utf8')).tools;

function verify(trace){
  const env=new CurationEnv(tasks.get(trace.task_id),tools,trace.max_steps??18);
  for(const step of trace.steps){
    const actual=env.step(step.action);
    assert.equal(actual.reward,step.response.reward,`${trace.task_id} step${step.step} reward`);
    assert.equal(actual.done,step.response.done,`${trace.task_id} step${step.step} termination`);
    assert.equal(!!actual.observation.error,!!step.response.observation.error,`${trace.task_id} step${step.step} error`);
  }
  assert.deepEqual(env.result,trace.result,`${trace.task_id} grade`);
  assert.deepEqual(env.dataset(),trace.dataset,`${trace.task_id} dataset`);
}

test('all 288 deterministic control trajectories preserve Python outcomes in the browser',()=>{
  let n=0;
  for(const p of read('control-results.json').policies)for(const e of p.episodes){verify(e.trajectory);n++;}
  assert.equal(n,288);
});

for(const [label,model] of Object.entries(read('results.json').models)){
  const path=model.archive_directory;
  test(`all 48 ${label} model trajectories preserve Python outcomes in the browser`,()=>{
    const summary=read(`${path}/summary.json`);
    assert.equal(summary.episodes_completed,48);
    for(const e of summary.episodes)verify(read(`${path}/episode-${e.task_id}.json`).environment_trajectory);
  });
}
