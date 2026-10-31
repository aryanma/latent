import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
const {JSDOM}=require(process.env.LATENT_JSDOM_PATH||'jsdom');
const root=new URL('../',import.meta.url);

test('the actual playground executes, resets, changes policy, exposes evidence, and exports',async()=>{
  const html=await readFile(new URL('curation.html',root),'utf8');
  const dom=new JSDOM(html,{url:'https://aryanma.github.io/latent/curation.html'});
  globalThis.document=dom.window.document;
  const requests=[];
  globalThis.fetch=async path=>{
    requests.push(path);
    try{return {ok:true,json:async()=>JSON.parse(await readFile(new URL(path,root),'utf8'))};}
    catch{return {ok:false};}
  };
  const downloads=[],blobs=[];
  URL.createObjectURL=blob=>{blobs.push(blob);return 'blob:test';};
  URL.revokeObjectURL=()=>{};
  dom.window.HTMLAnchorElement.prototype.click=function(){downloads.push(this.download);};
  await import('./app.mjs');
  const $=id=>document.getElementById(id);
  for(let i=0;i<100&&$('playground').hidden;i++)await new Promise(r=>setTimeout(r,5));
  assert.equal($('playground').hidden,false,$('loading').textContent);
  const initial=$('rows').textContent;
  assert.match($('contract-summary').textContent,/case resolution/);
  assert.equal(document.querySelectorAll('details[open]').length,0);
  $('run-reference').click();
  assert.match($('score').textContent,/Complete:/);
  assert.equal($('submit').disabled,true);
  const first=JSON.parse($('trajectory').textContent);
  assert.equal(first.result.reward,1);
  $('export').click();
  assert.deepEqual(downloads,['curation-trajectory.json']);
  assert.equal(JSON.parse(await blobs[0].text()).result.success,true);
  document.querySelector('[data-task="policy_shift-2000"]').click();
  assert.equal($('rows').textContent,initial);
  assert.match($('contract-summary').textContent,/human review/);
  $('run-reference').click();
  const second=JSON.parse($('trajectory').textContent);
  assert.equal(second.result.reward,1);
  assert.notDeepEqual(first.dataset,second.dataset);
  $('reset').click();$('discard').click();$('submit').click();
  assert.equal(JSON.parse($('trajectory').textContent).result.reward,0);
  assert.match($('score').textContent,/Incomplete:/);
  $('reset').click();$('sources').click();
  assert.match($('source-records').textContent,/case_resolution/);
  $('action-input').value='{invalid';$('step').click();
  assert.equal(JSON.parse($('trajectory').textContent).steps.length,4);
  $('action-input').value='{"tool":"repair","args":{"updates":[{"id":"<img src=x onerror=alert(1)>","label":"x","evidence_id":"x"}]}}';$('step').click();
  assert.equal($('observation').querySelectorAll('img,script').length,0);
  assert.equal(JSON.parse($('trajectory').textContent).steps.length,5);
  for(const id of ['run-model','run-adapted','run-scale','run-scale-secondary']){
    if(!$(id).disabled){$(id).click();assert.doesNotMatch($('status').textContent,/verification failed/);assert.match($('run-context').textContent,/recorded/);}
  }
  document.querySelector('[data-task="policy_shift-2004"]').click();
  assert.equal($('policy-choices').hidden,true);
  assert.match($('policy-heading').textContent,/completed curation/);
  $('run-reference').click();
  assert.equal(JSON.parse($('trajectory').textContent).result.reward,1);
  if($('run-scale').textContent==='Replay Qwen3.6'){
    $('run-scale').click();assert.equal(JSON.parse($('trajectory').textContent).result.reward,1);
  }
  document.querySelector('#pair-return button').click();assert.equal($('policy-choices').hidden,false);
  assert.deepEqual(requests,['./data/curation/playground.json','./data/curation/model-replays.json']);
  dom.window.close();
});
