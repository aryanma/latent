import { auditTasks, parseTasks, toCSV, MAX_BYTES } from './audit.mjs';

const $ = id => document.getElementById(id);
const node = (tag, text, className) => {
  const e = document.createElement(tag);
  if (text !== undefined) e.textContent = text;
  if (className) e.className = className;
  return e;
};
const state = { tasks: [], report: null, bundled: true, selected: '1', results: null, example: null };
const examples = {
  '1': ['Can the score distinguish a refusal from an approval?', 'The task requires declining an ineligible cancellation. Both traces below leave the reservation unchanged.'],
  '19': ['Does the score notice a missing cancellation?', 'The task requires canceling a reservation. Compare performing that action with omitting it.'],
  '17': ['Does the score notice an incomplete change?', 'The task requires changing the flight, passenger, and baggage details. Compare completing all three with omitting the first change.'],
  '26': ['Does the score distinguish a refusal from a refund offer?', 'The task requires refusing an ineligible refund. Neither trace below actually issues a refund.'],
};
const descriptions = {
  DB: 'Final database matches the reference outcome; alternative paths are allowed.',
  COMMUNICATE: 'Required facts in agent messages.',
  NL_ASSERTION: 'Written assertions judged against the interaction.',
  ENV_ASSERTION: 'Programmatic assertions over the environment.',
  ACTION: 'Explicit reference-call matching, only when this component gates reward.',
};

function error(message) { $('input-error').textContent = message; $('input-error').hidden = !message; }

function setData(tasks, source, bundled) {
  state.tasks = tasks; state.bundled = bundled;
  state.report = auditTasks(tasks, source);
  $('task-search').value = ''; $('task-filter').value = 'all';
  $('source-name').textContent = source;
  const s = state.report.summary;
  const metrics = [[s.tasks, 'tasks'], [s.empty_communication, 'empty communication checks'], [s.ungated_nl, 'tasks with ungated written assertions']];
  if (s.unassessed || s.partial) metrics.push([s.unassessed + s.partial, 'unassessed / partial']);
  $('audit-summary').replaceChildren(...metrics.map(([n, label]) => {
    const span = node('span'); span.append(document.createTextNode(`${n} ${label}. `)); return span;
  }));
  error('');
  renderOptions();
}

function renderOptions() {
  const search = $('task-search').value.toLowerCase().trim(), filter = $('task-filter').value;
  const rows = state.report.tasks.filter(t => {
    const matches = (t.id + ' ' + (t.title ?? '')).toLowerCase().includes(search);
    return matches && (filter === 'all' || (filter === 'unassessed' ? t.status !== 'inspected' : t.findings.some(f => f.code === filter)));
  });
  $('task-select').replaceChildren(...rows.map(t => {
    const title = t.title ?? 'Unassessed task';
    const option = node('option', `${t.id} — ${title.length > 62 ? title.slice(0, 59) + '…' : title}`); option.value = t.id; return option;
  }));
  if (!rows.some(t => t.id === state.selected)) state.selected = rows[0]?.id ?? null;
  $('task-select').value = state.selected ?? '';
  $('task-select').disabled = !rows.length; $('no-matches').hidden = !!rows.length;
  renderTask();
}

function detail(title, child) {
  const d = node('details'); d.append(node('summary', title), child); return d;
}

function renderTask() {
  const root = $('task-detail'); root.replaceChildren();
  document.querySelectorAll('[data-task]').forEach(b => b.setAttribute('aria-pressed', String(state.bundled && b.dataset.task === state.selected)));
  if (state.selected === null) { $('task-context').textContent = ''; $('task-goal').textContent = ''; $('replay-content').replaceChildren(node('p', 'Select a task to inspect its evidence.')); return; }
  const t = state.tasks.find(x => String(x.id) === state.selected);
  const audit = state.report.tasks.find(x => x.id === state.selected);
  const example = state.bundled && examples[audit.id];
  $('task-context').textContent = example ? example[0] : `Task ${audit.id}`;
  $('task-goal').textContent = example ? example[1] : audit.title ?? 'This contract could not be inspected.';
  if (!state.bundled) $('contract-details').open = true;
  root.append(node('h3', `Task ${audit.id}`, 'task-heading'), node('p', audit.title ?? 'This contract could not be inspected.'));
  if (audit.status === 'unassessed') {
    root.append(node('p', audit.errors.join(' '), 'error'));
  } else {
    root.append(node('p', 'reward = ' + (audit.reward_basis.join(' × ') || '(no components listed)'), 'reward-equation'));
    const c = t.evaluation_criteria;
    const table = node('table');
    const head = node('thead'), tr = node('tr');
    for (const label of ['Component', 'In reward?', 'Definition']) { const th = node('th', label); th.scope = 'col'; tr.append(th); }
    head.append(tr); table.append(head);
    const body = node('tbody');
    for (const gate of Object.keys(descriptions)) {
      const row = node('tr'), name = node('th', gate); name.scope = 'row';
      const active = audit.reward_basis.includes(gate);
      let explanation = descriptions[gate];
      if (gate === 'COMMUNICATE') explanation += ` ${audit.counts.communicate_info} required facts.`;
      if (gate === 'NL_ASSERTION') explanation += ` ${audit.counts.nl_assertions} assertions.`;
      if (gate === 'ENV_ASSERTION') explanation += ` ${audit.counts.env_assertions} assertions.`;
      if (gate === 'DB') explanation += ` ${audit.counts.actions} reference calls.`;
      row.append(name, node('td', active ? 'Yes' : 'No', active ? 'gate-on' : 'gate-off'), node('td', explanation)); body.append(row);
    }
    table.append(body); const wrap = node('div', undefined, 'table-wrap'); wrap.append(table); root.append(wrap);
    if (audit.findings.length) {
      const list = node('ul', undefined, 'finding-list');
      audit.findings.forEach(f => list.append(node('li', f.message))); root.append(list);
    } else root.append(node('p', 'No configuration review items from these checks. Semantic coverage remains unmeasured.', 'small'));
    if (c.nl_assertions?.length) { const ul = node('ul'); c.nl_assertions.forEach(a => ul.append(node('li', a))); const d = detail('Written assertions', ul); d.open = true; root.append(d); }
    root.append(detail('Reference actions and full task JSON', node('pre', JSON.stringify(t, null, 2))));
  }
  if (state.bundled) {
    const link = node('a', 'Link to this task'); link.href = `./signal.html?task=${encodeURIComponent(audit.id)}`;
    const p = node('p', undefined, 'small'); p.append(link); root.append(p);
  }
  renderReplays();
}

// Replay evidence is normalized at build time from the preserved Python output.
function renderReplays() {
  const root = $('replay-content'); root.replaceChildren();
  if (!state.bundled) { root.append(node('p', 'Unmeasured. This local file has only been inspected statically. Run an environment-specific replay before drawing conclusions about reward behavior.')); return; }
  if (!state.results) { root.append(node('p', 'Replay evidence could not be loaded. The static audit remains available; use the full results download below.')); return; }
  const task = state.results.tasks.find(t => t.id === state.selected);
  if (!task || !task.probes.length) { root.append(node('p', 'Not executed in this experiment. This task requires nonempty communication judging and was excluded from the model-free cohort.')); return; }
  const controls = node('div', undefined, 'probe-controls');
  const selects = ['A', 'B'].map(side => {
    const label = node('label', `Probe ${side}`); const select = node('select'); select.id = `probe-${side.toLowerCase()}`; label.htmlFor = select.id;
    task.probes.forEach(p => { const o = node('option', p.label); o.value = p.key; select.append(o); });
    label.append(select); controls.append(label); return select;
  });
  selects[0].value = task.default_a ?? task.probes[0].key;
  selects[1].value = task.default_b ?? task.probes.at(-1).key;
  const grid = node('div', undefined, 'probe-grid'), conclusion = node('p', undefined, 'comparison-result');
  root.append(grid, conclusion, detail('Compare other replays', controls));
  function draw() {
    const selected = selects.map(s => task.probes.find(p => p.key === s.value));
    grid.replaceChildren(...selected.map(p => {
      const section = node('div', undefined, 'probe');
      section.append(node('h3', p.label));
      const score = node('p', 'Reward', 'score-line'); score.append(node('strong', p.reward == null ? 'error' : String(p.reward))); section.append(score);
      section.append(node('blockquote', p.final_text || '(No final reply)'));
      if (['17', '19'].includes(state.selected)) section.append(node('p', p.action_names.length ? `${p.action_names.length} tool call${p.action_names.length === 1 ? '' : 's'}` : 'No tool calls', 'small'));
      const ul = node('ul');
      ul.append(node('li', `Tool calls: ${p.action_names.length ? p.action_names.join(', ') : 'none'}`));
      ul.append(node('li', `Termination: ${p.termination}`));
      for (const [component, value] of Object.entries(p.components)) ul.append(node('li', `${component}: ${value}`));
      const metadata = node('div'); metadata.append(node('p', p.description, 'small'), ul, detail('Raw evidence', node('pre', JSON.stringify(p.evidence, null, 2))));
      const evidence = detail('Details', metadata); evidence.className = 'probe-meta'; section.append(evidence);
      return section;
    }));
    const [a, b] = selected;
    if (a.key === b.key) conclusion.textContent = 'The same probe is selected twice. Choose another probe to compare.';
    else if (a.reward == null || b.reward == null) conclusion.textContent = 'One of these probes has an execution error. It is not counted as a normal reward rejection.';
    else if (a.reward === b.reward) conclusion.textContent = `Same scalar reward (${a.reward}). The score does not distinguish these two traces; that does not mean they are equally good responses.`;
    else conclusion.textContent = `Reward changed from ${a.reward} to ${b.reward}. This change is visible to the scorer. Component scores are in Details.`;
  }
  selects.forEach(s => s.addEventListener('change', draw)); draw();
}

function download(contents, name, mime) {
  const url = URL.createObjectURL(new Blob([contents], {type: mime}));
  const a = node('a'); a.href = url; a.download = name; document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

async function fetchJSON(path) { const r = await fetch(path); if (!r.ok) throw new Error(`Could not load ${path} (${r.status}).`); return r.json(); }

async function init() {
  const query = new URLSearchParams(location.search).get('task'); if (query !== null) state.selected = query;
  try {
    state.example = await fetchJSON('./data/signal/airline-tasks.json');
    try { state.results = await fetchJSON('./data/signal/replays.json'); } catch { /* The independent static audit still works. */ }
    setData(parseTasks(JSON.stringify(state.example)), 'τ²-bench / airline · 50 tasks · da0835f6c67b', true);
    $('load-status').textContent = ''; $('workspace').hidden = false;
  } catch (e) { $('load-status').textContent = e.message + ' Reload the page or use the CLI linked above.'; return; }
  $('task-search').addEventListener('input', renderOptions);
  document.querySelectorAll('[data-task]').forEach(button => button.addEventListener('click', () => {
    state.selected = button.dataset.task;
    setData(state.example, 'τ²-bench / airline · 50 tasks · da0835f6c67b', true);
    $('contract-details').open = false;
  }));
  $('task-filter').addEventListener('change', renderOptions);
  $('task-select').addEventListener('change', () => { state.selected = $('task-select').value; renderTask(); });
  $('load-example').addEventListener('click', () => { state.selected = '1'; setData(state.example, 'τ²-bench / airline · 50 tasks · da0835f6c67b', true); $('task-file').value = ''; });
  $('task-file').addEventListener('change', async e => {
    const file = e.target.files?.[0]; if (!file) return;
    try {
      if (file.size > MAX_BYTES) throw new Error('Use a JSON file smaller than 5 MB.');
      const tasks = parseTasks(await file.text()); state.selected = null;
      setData(tasks, `Local file: ${file.name}`, false);
    } catch (e) { error(e.message); }
  });
  $('inspect-paste').addEventListener('click', () => {
    try { const tasks = parseTasks($('json-input').value); state.selected = null; setData(tasks, 'Pasted task definitions · local static audit', false); }
    catch (e) { error(e.message); }
  });
  $('export-json').addEventListener('click', () => download(JSON.stringify(state.report, null, 2), 'latent-signal-audit.json', 'application/json'));
  $('export-csv').addEventListener('click', () => download(toCSV(state.report), 'latent-signal-audit.csv', 'text/csv'));
}
init();
