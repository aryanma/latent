/** Static contract inspection, not a replacement for the upstream evaluator. */
export const VERSION = '0.1.0';
export const UPSTREAM_COMMIT = 'da0835f6c67baef58bdda18f2a3b037dfb3a1754';
export const MAX_BYTES = 5 * 1024 * 1024;
export const GATES = ['DB', 'COMMUNICATE', 'NL_ASSERTION', 'ENV_ASSERTION', 'ACTION'];
const DEFAULT_BASIS = ['DB', 'COMMUNICATE'];
const FIELDS = ['actions', 'communicate_info', 'nl_assertions', 'env_assertions'];
const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);

export function parseTasks(text) {
  if (new TextEncoder().encode(text).byteLength > MAX_BYTES) throw new Error('Use a JSON file smaller than 5 MB.');
  let data;
  try { data = JSON.parse(text); } catch { throw new Error('This file is not valid JSON. Choose a τ² task array or an object with a tasks array.'); }
  const tasks = Array.isArray(data) ? data : data?.tasks;
  if (!Array.isArray(tasks) || !tasks.length) throw new Error('Expected a nonempty task array, or {"tasks": [...]}.');
  if (tasks.length > 2000) throw new Error('Use at most 2,000 tasks per audit.');
  const ids = new Set();
  for (const [i, task] of tasks.entries()) {
    if (!object(task) || !['string', 'number'].includes(typeof task.id) || String(task.id).trim() === '') {
      throw new Error(`Task ${i + 1} needs a nonempty string or numeric id.`);
    }
    const id = String(task.id);
    if (ids.has(id)) throw new Error(`Duplicate task id: ${id}. Each task must have a unique id.`);
    ids.add(id);
  }
  return tasks;
}

function issue(code, message) { return { code, message }; }

export function inspectTask(task) {
  const id = String(task.id);
  const c = task.evaluation_criteria;
  const errors = [];
  if (!object(c)) errors.push('Missing or invalid evaluation_criteria object.');
  if (object(c)) {
    for (const field of FIELDS) {
      if (c[field] != null && !Array.isArray(c[field])) errors.push(`${field} must be an array or null.`);
    }
    if ('reward_basis' in c && (!Array.isArray(c.reward_basis) || c.reward_basis.some(g => typeof g !== 'string'))) {
      errors.push('reward_basis must be an array of strings; null is not the upstream default.');
    }
    for (const field of ['communicate_info', 'nl_assertions']) {
      if (Array.isArray(c[field]) && c[field].some(v => typeof v !== 'string' || !v.trim())) errors.push(`${field} must contain nonempty strings.`);
    }
    if (Array.isArray(c.actions) && c.actions.some(a => !object(a) || typeof a.name !== 'string' || !a.name.trim() || !object(a.arguments))) {
      errors.push('Each reference action needs a name and an arguments object.');
    }
    if (Array.isArray(c.env_assertions) && c.env_assertions.some(a => !object(a) || typeof a.func_name !== 'string' || !object(a.arguments))) {
      errors.push('Each environment assertion needs a func_name and an arguments object.');
    }
  }
  if (errors.length) return { id, status: 'unassessed', errors, findings: [], reward_basis: null, counts: null, model_free_candidate: false };
  const inherited = !Object.hasOwn(c, 'reward_basis');
  const basis = inherited ? [...DEFAULT_BASIS] : [...c.reward_basis];
  const unknown = basis.filter(g => !GATES.includes(g));
  const counts = Object.fromEntries(FIELDS.map(f => [f, c[f]?.length ?? 0]));
  const findings = [];
  const has = g => basis.includes(g);
  if (unknown.length) findings.push(issue('unknown_gate', `Unsupported reward components: ${unknown.join(', ')}. Their behavior is unassessed.`));
  if (new Set(basis).size !== basis.length) findings.push(issue('duplicate_gate', 'The reward basis repeats a component. Review the upstream configuration.'));
  if (!basis.length) findings.push(issue('empty_basis', 'No reward components are listed. Review this configuration before using its score.'));
  if (inherited) findings.push(issue('inherited_basis', 'No explicit reward_basis: this audit applies the pinned τ² schema default, DB × COMMUNICATE.'));
  if (has('COMMUNICATE') && counts.communicate_info === 0) findings.push(issue('empty_communication', 'COMMUNICATE gates reward but has no required facts. At the pinned upstream version, this check is neutral.'));
  if (counts.nl_assertions && !has('NL_ASSERTION')) findings.push(issue('ungated_nl', `${counts.nl_assertions} written assertion${counts.nl_assertions === 1 ? '' : 's'} not directly gated by NL_ASSERTION. Other components may enforce overlapping requirements; these assertions can also be used as diagnostics.`));
  if (counts.communicate_info && !has('COMMUNICATE')) findings.push(issue('ungated_communication', 'Required communication is present but COMMUNICATE does not gate reward.'));
  if (counts.env_assertions && !has('ENV_ASSERTION')) findings.push(issue('ungated_environment', 'Environment assertions are present but ENV_ASSERTION does not gate reward.'));
  for (const [gate, field] of [['NL_ASSERTION', 'nl_assertions'], ['ENV_ASSERTION', 'env_assertions'], ['ACTION', 'actions']]) {
    if (has(gate) && !counts[field]) findings.push(issue('empty_' + gate.toLowerCase(), `${gate} gates reward but ${field} is empty. Inspect evaluator handling.`));
  }
  if (has('DB') && counts.actions === 0) findings.push(issue('no_reference_actions', 'No reference actions: the DB target is the initialized state. This can be correct for a refusal; it does not verify the spoken response.'));
  const modelFree = !unknown.length && basis.length > 0 && !has('NL_ASSERTION') && (!has('COMMUNICATE') || counts.communicate_info === 0);
  return {
    id, status: unknown.length ? 'partial' : 'inspected', errors, reward_basis: basis,
    inherited_basis: inherited, counts, findings,
    // A candidate, never a guarantee: custom tools or environment assertions may perform I/O.
    model_free_candidate: modelFree,
    title: typeof task.description?.purpose === 'string' ? task.description.purpose : `Task ${id}`,
  };
}

export function auditTasks(tasks, source = 'Local task file') {
  const rows = tasks.map(inspectTask);
  const count = predicate => rows.filter(predicate).length;
  const withCode = code => count(t => t.findings.some(f => f.code === code));
  return {
    schema_version: 1, tool: 'Latent Signal', tool_version: VERSION,
    adapter: 'tau2-evaluation-criteria', adapter_commit: UPSTREAM_COMMIT,
    source, evidence: 'static-contract-audit',
    scope: 'Inspects task configuration only. Does not execute tools, judge task correctness, or certify reward coverage.',
    summary: {
      tasks: rows.length, inspected: count(t => t.status === 'inspected'), partial: count(t => t.status === 'partial'),
      unassessed: count(t => t.status === 'unassessed'), empty_communication: withCode('empty_communication'),
      ungated_nl: withCode('ungated_nl'), model_free_candidates: count(t => t.model_free_candidate),
      inherited_basis: withCode('inherited_basis'),
    }, tasks: rows,
  };
}

export function toCSV(report) {
  const quote = value => {
    let s = String(value ?? '');
    // Avoid formula execution when a report made from untrusted input is opened in a spreadsheet.
    if (/^[=+@\-\t\r]/.test(s)) s = "'" + s;
    return '"' + s.replaceAll('"', '""') + '"';
  };
  const rows = [['task_id', 'status', 'reward_basis', 'reference_actions', 'communication_facts', 'nl_assertions', 'findings', 'errors']];
  for (const t of report.tasks) rows.push([t.id, t.status, t.reward_basis?.join(' × '), t.counts?.actions, t.counts?.communicate_info, t.counts?.nl_assertions, t.findings.map(f => f.code).join('; '), t.errors.join('; ')]);
  return rows.map(r => r.map(quote).join(',')).join('\r\n') + '\r\n';
}
