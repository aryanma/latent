import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {CurationEnv} from './env.mjs';
const data=JSON.parse(readFileSync(new URL('../data/curation/playground.json',import.meta.url),'utf8'));
test('browser executes the released Python reference actions with identical grades and datasets',()=>{
  for(const task of data.tasks){
    const env=new CurationEnv(task,data.tools),trace=data.references[task.public.id];
    for(const step of trace.steps){const r=env.step(step.action);assert.equal(r.reward,step.response.reward);assert.equal(r.done,step.response.done);}
    assert.deepEqual(env.result,trace.result);
    assert.deepEqual(env.dataset(),trace.dataset);
  }
});
test('browser cannot reward discarding all data; reset restores the fixture',()=>{
  const env=new CurationEnv(data.tasks[0],data.tools),initial=structuredClone(env.rows);
  env.step({tool:'exclude',args:{ids:env.rows.map(r=>r.id),reason:'other'}});
  assert.equal(env.step({tool:'submit'}).reward,0);
  assert.throws(()=>env.step({tool:'inspect'}));
  env.reset();assert.deepEqual(env.rows,initial);
});
test('browser mutations are atomic and observations do not change the source',()=>{
  const env=new CurationEnv(data.tasks[0],data.tools),initial=structuredClone(env.rows);
  const r=env.step({tool:'exclude',args:{ids:[env.rows[0].id,'wrong-id'],reason:'other'}});
  assert(r.observation.error);assert.deepEqual(env.rows,initial);
  const response=env.step({tool:'inspect'});response.observation.rows[0].label='tampered';
  assert.deepEqual(env.rows,initial);
});
test('browser does not coerce malformed JSON argument types or inherited property names',()=>{
  const env=new CurationEnv(data.tasks[0],data.tools);
  for(const action of [
    {tool:'submit',args:null},
    {tool:'inspect',args:{offset:null}},
    {tool:'lookup',args:{table:['registry'],keys:['anything']}},
    JSON.parse('{"tool":"submit","args":{"__proto__":{}}}'),
    {tool:'submit',args:{constructor:'ignored'}}
  ]){
    const response=env.step(action);
    assert(response.observation.error);assert.equal(response.done,false);
  }
  assert.equal(env.steps,5);assert.equal(env.result,null);
});
