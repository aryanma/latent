import {CurationEnv} from './env.mjs';
const $=id=>document.getElementById(id);
const el=(tag,text,className)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(className)e.className=className;return e;};
let data,models,env,recordedOutcome=null,selected='composition-2000';
const task=()=>data.tasks.find(t=>t.public.id===selected);
const percent=n=>`${Math.round(n*100)}%`;
const primaryModel=()=>models?.currentmoe?'currentmoe':'scale8b';
const exportTrace=()=>({...env.export(),...(recordedOutcome?{recorded_harness_outcome:recordedOutcome}:{})});
function render(){
  const originals=new Map(task().public.candidates.map(r=>[r.id,r]));
  $('rows').replaceChildren(...env.rows.map(r=>{
    const tr=el('tr',undefined,r.keep?'':'excluded'),id=el('th',r.id.slice(-6));id.scope='row';id.title=r.id;
    tr.append(id,el('td',originals.get(r.id).label),el('td',r.label,r.label!==originals.get(r.id).label?'changed':''),el('td',r.keep?'Keep':'Exclude'));
    return tr;
  }));
  $('status').textContent=`${env.steps} / ${env.maxSteps} actions${env.done?' · episode ended':''}`;
  const r=env.result;
  $('score').replaceChildren();
  if(r){
    const score=el('div',undefined,'score');
    for(const [value,label] of [[Number(r.reward.toFixed(3)),'reward'],[r.coverage===undefined?'—':percent(r.coverage),'coverage'],[r.label_accuracy===undefined?'—':percent(r.label_accuracy),'label accuracy'],[r.safe===undefined?'—':r.safe?'pass':'fail','permissions / split']]){
      const p=el('p');p.append(el('strong',String(value)),document.createTextNode(label));score.append(p);
    }
    $('score').append(score,el('p',r.success?'Complete: the submitted dataset satisfies this task’s contract.':r.termination==='budget_exhausted'?'Action budget exhausted before submission.':'Incomplete: the submitted dataset misses one or more requirements.','outcome-note small'));
    if(r.termination==='submitted'&&!r.success){
      const issues=[];
      if(!r.kept_rows)issues.push('No records retained.');
      if(r.covered_lineages<r.required_lineages)issues.push(`${r.required_lineages-r.covered_lineages} eligible lineages missing.`);
      const wrong=Math.round((1-r.label_accuracy)*r.kept_rows);
      if(wrong)issues.push(`${wrong} retained labels incorrect.`);
      if(r.violations.length)issues.push(`${r.violations.length} permission or split violations.`);
      if(r.duplicate_lineages.length)issues.push(`${r.duplicate_lineages.length} duplicated lineages.`);
      if(r.unsupported_edits.length)issues.push(`${r.unsupported_edits.length} label edits cite unsupported evidence.`);
      $('score').append(el('p',issues.join(' '),'small'));
    }
  }
  if(recordedOutcome&&!env.done){
    $('status').textContent=`${env.steps} / ${env.maxSteps} actions · recorded run ended before submission`;
    const reason=recordedOutcome.termination==='generation_budget_exhausted'?'exhausted its generation budget':`stopped (${recordedOutcome.termination.replaceAll('_',' ')})`;
    $('score').append(el('p',`The recorded model ${reason} without submitting. Harness score: 0. No dataset was graded. Reset to start a new episode.`,'small outcome-note'));
  }
  $('trajectory').textContent=JSON.stringify(exportTrace(),null,2);
  for(const id of ['inspect','sources','discard','submit','step'])$(id).disabled=env.done||!!recordedOutcome;
}
function reset(){
  recordedOutcome=null;
  env=new CurationEnv(task(),data.tools);
  const c=task().public.contract;
  const paired=selected==='composition-2000'||selected==='policy_shift-2000';
  const permissions=selected==='permissions-1008';
  const completed=selected==='policy_shift-2004';
  $('policy-heading').textContent=paired?'Same records. Different policy.':completed?'A completed curation run':permissions?'A permissions check':'Source-grounded label repair';
  $('scenario-description').textContent=paired?'Two sources disagree. The contract determines which one to trust. Switching the authority below changes the correct labels while keeping every record and source event the same.':completed?'In this selected successful run, Qwen3.6 corrects two labels and removes forbidden, evaluation-overlapping, and duplicate records while preserving every eligible lineage. The research note reports all 48 episodes.':permissions?'Some records are not permitted for training. Keep every eligible lineage and exclude the forbidden ones. This example was selected from successful Qwen3.6 runs; the research note reports all 48 episodes.':'Repair the labels using approved source events under the declared authority and revision cutoff. Preserve all eligible cases.';
  $('policy-choices').hidden=!paired;$('pair-return').hidden=paired;$('evidence-example').hidden=!paired;
  $('contract-summary').textContent=`Use the latest approved ${c.authority.replaceAll('_',' ')} at or before revision ${c.cutoff_revision}. Keep one row per eligible lineage.`;
  const exampleRow=task().public.candidates.find(r=>r.id===data.references[selected].dataset[0].id);
  const exampleCase=task().public.tables.registry.find(r=>r.ticket_id===exampleRow.ticket_id).case_id;
  const labels=['case_resolution','human_review'].map(authority=>{
    const event=task().public.tables.events.filter(e=>e.case_id===exampleCase&&e.authority===authority&&e.status==='approved'&&e.revision<=c.cutoff_revision).sort((a,b)=>b.revision-a.revision)[0];
    return c.aliases[event.category]??event.category;
  });
  $('evidence-example').textContent=`For example, record …${exampleRow.id.slice(-6)} has two source decisions: case resolution says “${labels[0]}”; human review says “${labels[1]}”. The contract chooses which label belongs in the output.`;
  const list=el('ul');c.rules.forEach(r=>list.append(el('li',r)));$('contract').replaceChildren(list);
  $('source-records').textContent='Inspect sources using the tools below to reveal the same evidence an agent can access.';
  $('observation').textContent=JSON.stringify(env.reset(),null,2);
  document.querySelectorAll('[data-task]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.task===selected)));
  $('run-model').disabled=!models?.base?.[selected];$('run-adapted').disabled=!models?.adapted?.[selected];
  $('run-scale').disabled=!models?.[primaryModel()]?.[selected];
  $('run-scale').textContent=primaryModel()==='currentmoe'?'Replay Qwen3.6':'Replay 8B model';
  $('run-scale-secondary').hidden=primaryModel()!=='currentmoe';
  $('run-scale-secondary').disabled=!models?.scale8b?.[selected];
  $('run-context').textContent='The reference is a deterministic program that follows the declared schema and rules. Model buttons replay recorded runs; no model runs in your browser.';
  render();
}
function step(action){const response=env.step(action);$('observation').textContent=JSON.stringify(response,null,2);render();return response;}
function inspectSources(){
  const rows=step({tool:'inspect'}).observation.rows;
  if(env.done)return;
  const regs=step({tool:'lookup',args:{table:'registry',keys:rows.map(r=>r.ticket_id)}}).observation.records;
  if(env.done)return;
  const evaluation=step({tool:'lookup',args:{table:'evaluation',keys:[...new Set(regs.map(r=>r.lineage_id))]}}).observation.records;
  if(env.done)return;
  const events=step({tool:'lookup',args:{table:'events',keys:[...new Set(regs.map(r=>r.case_id))]}}).observation.records;
  $('source-records').textContent=JSON.stringify({registry:regs,evaluation,events},null,2);
}
function replay(trace,label){
  reset();
  for(const recorded of trace.steps){
    if(env.done)break;
    step(recorded.action);
  }
  const expected=trace.result;
  if(expected?.termination==='submitted'||expected?.termination==='budget_exhausted'){
    if(!env.result||env.result.reward!==expected.reward||env.result.success!==expected.success)throw new Error('Replay verification failed: browser outcome differs from the recorded Python result.');
  }
  recordedOutcome=trace.recorded_outcome??null;
  render();
  $('source-records').textContent=JSON.stringify(Object.fromEntries(Object.entries(task().public.tables).map(([k,rows])=>[k,rows.filter(r=>env.inspected.has(r.id))])),null,2);
  $('run-context').textContent=label;
}
function handle(fn){try{fn();}catch(e){$('status').textContent=e.message;}}
async function fetchJSON(path){const r=await fetch(path);if(!r.ok)throw new Error(`Could not load ${path}`);return r.json();}
async function init(){
  try{
    data=await fetchJSON('./data/curation/playground.json');
    const requested=new URL(document.URL).searchParams.get('task');
    if(data.tasks.some(t=>t.public.id===requested))selected=requested;
    try{models=await fetchJSON('./data/curation/model-replays.json');}catch{models=null;}
    reset();$('loading').hidden=true;$('playground').hidden=false;
  }catch(e){$('loading').textContent=e.message;return;}
  document.querySelectorAll('[data-task]').forEach(b=>b.addEventListener('click',()=>{selected=b.dataset.task;reset();}));
  $('reset').addEventListener('click',reset);
  $('run-reference').addEventListener('click',()=>handle(()=>replay(data.references[selected],'Executed the deterministic reference policy through the environment. It uses the visible sources and the declared contract.')));
  $('run-model').addEventListener('click',()=>handle(()=>replay(models.base[selected],'Replayed the recorded base-model actions through the environment. Scores are recomputed locally; generation occurred in the published experiment.')));
  $('run-adapted').addEventListener('click',()=>handle(()=>replay(models.adapted[selected],'Replayed the recorded adapted-model actions through the environment. This is the published checkpoint’s run, not live inference.')));
  $('run-scale').addEventListener('click',()=>handle(()=>replay(models[primaryModel()][selected],`Replayed the recorded ${primaryModel()==='currentmoe'?'Qwen3.6-35B-A3B':'Qwen3-8B'} actions through the environment. Scores are recomputed locally; this is not live inference.`)));
  $('run-scale-secondary').addEventListener('click',()=>handle(()=>replay(models.scale8b[selected],'Replayed the recorded Qwen3-8B actions through the environment. Scores are recomputed locally; this is not live inference.')));
  $('inspect').addEventListener('click',()=>handle(()=>step({tool:'inspect'})));
  $('sources').addEventListener('click',()=>handle(inspectSources));
  $('discard').addEventListener('click',()=>handle(()=>step({tool:'exclude',args:{ids:env.rows.map(r=>r.id),reason:'other'}})));
  $('submit').addEventListener('click',()=>handle(()=>step({tool:'submit'})));
  $('step').addEventListener('click',()=>handle(()=>step(JSON.parse($('action-input').value))));
  $('export').addEventListener('click',()=>{
    const url=URL.createObjectURL(new Blob([JSON.stringify(exportTrace(),null,2)],{type:'application/json'}));
    const a=el('a');a.href=url;a.download='curation-trajectory.json';document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
  });
}
init();
