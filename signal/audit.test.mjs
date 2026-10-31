import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { auditTasks, inspectTask, parseTasks, toCSV } from './audit.mjs';
const task = c => ({ id: '0', evaluation_criteria: c });

test('pin-specific airline counts are derived from the raw task file', () => {
  const tasks = parseTasks(readFileSync(new URL('../data/signal/airline-tasks.json', import.meta.url), 'utf8'));
  const before = JSON.stringify(tasks);
  const report = auditTasks(tasks);
  assert.deepEqual(report.summary, { tasks: 50, inspected: 50, partial: 0, unassessed: 0, empty_communication: 44, ungated_nl: 50, model_free_candidates: 44, inherited_basis: 0 });
  assert.equal(JSON.stringify(tasks), before, 'audit must not mutate uploaded data');
});
test('a nonempty communication gate and gated NL assertions are not flagged as absent', () => {
  const t = inspectTask(task({reward_basis: ['COMMUNICATE', 'NL_ASSERTION'], communicate_info: ['Refund denied'], nl_assertions: ['No refund offered']}));
  assert.deepEqual(t.findings, []);
  assert.equal(t.model_free_candidate, false);
});
test('missing basis follows the pinned default, explicit empty does not', () => {
  assert.deepEqual(inspectTask(task({})).reward_basis, ['DB', 'COMMUNICATE']);
  const t = inspectTask(task({ reward_basis: [] }));
  assert.deepEqual(t.reward_basis, []);
  assert.equal(t.model_free_candidate, false);
  assert(t.findings.some(f => f.code === 'empty_basis'));
  assert.equal(inspectTask(task({ reward_basis: null })).status, 'unassessed');
});
test('unknown components remain partial and never become model-free candidates', () => {
  const t = inspectTask(task({reward_basis: ['FUTURE_GATE']}));
  assert.equal(t.status, 'partial');
  assert.equal(t.model_free_candidate, false);
});
test('bad shapes remain unassessed instead of producing optimistic counts', () => {
  for (const criteria of [null, [], {actions: 'oops'}, {reward_basis: [0]}, {nl_assertions: [{}]}, {actions: [{name: 'x'}]}, {env_assertions: ['x']}, {communicate_info: ['']}]) {
    const t = inspectTask(task(criteria));
    assert.equal(t.status, 'unassessed');
    assert.equal(t.counts, null);
  }
});
test('input rejects empty, malformed, duplicate, missing-ID, and oversized documents', () => {
  for (const s of ['bad', '{}', '[]', '[{}]', '[{"id":0},{"id":"0"}]', '[{"id":null}]', ' '.repeat(5 * 1024 * 1024 + 1)]) assert.throws(() => parseTasks(s));
  assert.equal(parseTasks('{"tasks":[{"id":"a"}]}')[0].id, 'a');
});
test('CSV escapes delimiters, quotes, and spreadsheet formula prefixes', () => {
  const csv = toCSV(auditTasks([{id: '=HYPERLINK("bad")', evaluation_criteria: {reward_basis: ['DB']}}]));
  assert(csv.includes('"\'=HYPERLINK(""bad"")"'));
});
test('CLI is usable without installation and strict mode is distinguishable from errors', () => {
  const cli = new URL('./cli.mjs', import.meta.url);
  const input = new URL('../data/signal/airline-tasks.json', import.meta.url);
  const result = spawnSync(process.execPath, [cli.pathname, input.pathname, '--strict'], {encoding: 'utf8'});
  assert.equal(result.status, 2);
  assert.equal(JSON.parse(result.stdout).summary.tasks, 50);
  const bad = spawnSync(process.execPath, [cli.pathname, input.pathname, '--bogus'], {encoding: 'utf8'});
  assert.equal(bad.status, 1);
});
