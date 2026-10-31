// Browser implementation of the public playground. Python is the experiment runtime.
// Every released reference/model trajectory is cross-checked against this implementation.
const clone = value => structuredClone(value);
export class CurationEnv {
  constructor(task, tools, maxSteps = 18) { this.task = clone(task); this.tools = tools; this.maxSteps = maxSteps; this.reset(); }
  reset() {
    this.rows = this.task.public.candidates.map(r => ({...clone(r), keep: true, evidence_id: null, exclusion_reason: null}));
    this.inspected = new Set(); this.steps = 0; this.done = false; this.result = null; this.history = [];
    return {task_id:this.task.public.id,contract:clone(this.task.public.contract),candidate_count:this.rows.length,tools:clone(this.tools),max_steps:this.maxSteps,reward:0,done:false};
  }
  step(action) {
    if (this.done) throw new Error('Episode ended. Reset to start another.');
    this.steps++;
    let observation, error = null;
    try {
      if (!action || typeof action !== 'object' || Array.isArray(action)) throw new Error('Action must be a JSON object');
      const args = Object.hasOwn(action,'args') ? action.args : {};
      if (!args || typeof args !== 'object' || Array.isArray(args)) throw new Error('args must be an object');
      const tool = this.tools.find(t => t.name === action.tool);
      if (!tool) throw new Error('Unknown tool. Read the available tool definitions.');
      if (Object.keys(args).some(k => !Object.hasOwn(tool.input_schema.properties,k))) throw new Error('Unknown argument for this tool');
      observation = this.act(action.tool,args);
    } catch (e) { observation = {error:e.message}; error = 'ValueError'; }
    if (this.steps >= this.maxSteps && !this.done) { this.done = true; this.result = {reward:0,success:false,termination:'budget_exhausted'}; }
    const response = {observation,reward:this.done ? this.result.reward : 0,done:this.done,steps:this.steps,remaining_steps:Math.max(0,this.maxSteps-this.steps)};
    if (this.done) response.result = clone(this.result);
    this.history.push({step:this.steps,action:clone(action),response:clone(response),error});
    return response;
  }
  getRows(ids) {
    if (!Array.isArray(ids) || !ids.length || ids.length > 20 || ids.some(i=>typeof i !== 'string')) throw new Error('ids must contain 1–20 row IDs');
    const rows = new Map(this.rows.map(r=>[r.id,r]));
    if (ids.some(i=>!rows.has(i))) throw new Error('Unknown row ID; no changes applied');
    return ids.map(i=>rows.get(i));
  }
  act(name,args) {
    if (name === 'inspect') {
      const offset = Object.hasOwn(args,'offset') ? args.offset : 0, limit = Object.hasOwn(args,'limit') ? args.limit : 20;
      if (!Number.isInteger(offset) || !Number.isInteger(limit) || offset < 0 || limit < 1 || limit > 20) throw new Error('offset must be nonnegative; limit must be 1–20');
      return {rows:clone(this.rows.slice(offset,offset+limit)),total:this.rows.length};
    }
    if (name === 'lookup') {
      const {table,keys} = args;
      if (typeof table!=='string'||!Object.hasOwn(this.task.public.tables,table)) throw new Error('Unknown source table');
      if (!Array.isArray(keys) || !keys.length || keys.length > 20 || keys.some(k=>typeof k !== 'string')) throw new Error('keys must contain 1–20 strings');
      const field = {registry:'ticket_id',events:'case_id',evaluation:'lineage_id'}[table];
      const found = this.task.public.tables[table].filter(r=>keys.includes(r[field]));
      found.forEach(r=>this.inspected.add(r.id));
      return {table,records:clone(found),keys_without_matches:keys.filter(k=>!found.some(r=>r[field]===k))};
    }
    if (name === 'repair') {
      const {updates} = args;
      if (!Array.isArray(updates) || !updates.length || updates.length > 20) throw new Error('updates must contain 1–20 edits');
      if (updates.some(u=>!u || typeof u !== 'object' || Array.isArray(u))) throw new Error('Each edit must be an object');
      const rows = this.getRows(updates.map(u=>u.id));
      if (new Set(updates.map(u=>u.id)).size !== updates.length) throw new Error('Duplicate row IDs in updates');
      for (const u of updates) {
        if (!this.task.public.contract.labels.includes(u.label)) throw new Error('Use a canonical label from the contract');
        if (typeof u.evidence_id !== 'string' || !this.inspected.has(u.evidence_id)) throw new Error('Inspect the cited source event before using it; no changes applied');
      }
      rows.forEach((r,i)=>{r.label=updates[i].label;r.evidence_id=updates[i].evidence_id;});
      return {edited:updates.map(u=>u.id)};
    }
    if (name === 'exclude' || name === 'restore') {
      const rows = this.getRows(args.ids);
      if (name==='exclude' && !['permission','evaluation_overlap','duplicate','other'].includes(args.reason)) throw new Error('Unknown exclusion reason');
      rows.forEach(r=>{r.keep=name==='restore';r.exclusion_reason=name==='exclude'?args.reason:null;});
      return {updated:rows.map(r=>r.id)};
    }
    if (name === 'check') return {kept_rows:this.rows.filter(r=>r.keep).length,excluded_rows:this.rows.filter(r=>!r.keep).length,noncanonical_labels:this.rows.filter(r=>r.keep&&!this.task.public.contract.labels.includes(r.label)).map(r=>r.id),note:'Only public structural checks. Correct labels, eligible lineage coverage, and source validity are graded on submit.'};
    if (name === 'submit') { this.done=true;this.result={...this.grade(),termination:'submitted'}; return {dataset:this.dataset()}; }
  }
  grade() {
    const truth=this.task.private, originals=new Map(this.task.public.candidates.map(r=>[r.id,r]));
    const kept=this.rows.filter(r=>r.keep), counts=new Map(), violations=[], unsupported=[];
    let correct=0;
    for (const row of kept) {
      const t=truth.rows[row.id]; counts.set(t.lineage_id,(counts.get(t.lineage_id)??0)+1);
      if (!t.permitted) violations.push({id:row.id,type:'permission'});
      if (t.leaked) violations.push({id:row.id,type:'evaluation_overlap'});
      if (row.label===t.label) correct++;
      if (row.label!==originals.get(row.id).label && (row.evidence_id!==t.event_id || !this.inspected.has(t.event_id))) unsupported.push(row.id);
    }
    const required=Object.keys(truth.eligible_groups), covered=required.filter(g=>counts.has(g));
    const coverage=covered.length/required.length, accuracy=kept.length?correct/kept.length:0;
    const duplicates=[...counts].filter(([,n])=>n>1).map(([g])=>g);
    const safe=!violations.length,unique=!duplicates.length,provenance=!unsupported.length;
    const reward=coverage*accuracy*Number(safe)*Number(unique)*Number(provenance);
    return {reward,success:!!kept.length&&reward===1,coverage,label_accuracy:accuracy,safe,unique,provenance,kept_rows:kept.length,required_lineages:required.length,covered_lineages:covered.length,violations,duplicate_lineages:duplicates,unsupported_edits:unsupported};
  }
  dataset() { return this.rows.filter(r=>r.keep).map(({id,text,label,evidence_id})=>({id,text,label,evidence_id})); }
  export() { return {runtime:'browser-playground',task_id:this.task.public.id,source_sha256:this.task.fingerprint,max_steps:this.maxSteps,steps:clone(this.history),result:clone(this.result),dataset:this.dataset()}; }
}
