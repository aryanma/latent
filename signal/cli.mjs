#!/usr/bin/env node
import { readFileSync, statSync } from 'node:fs';
import { auditTasks, parseTasks, toCSV, MAX_BYTES } from './audit.mjs';

const args = process.argv.slice(2);
if (!args.length || args.includes('--help')) {
  console.log('Usage: node signal/cli.mjs tasks.json [--csv] [--strict]\n\nStatic τ² contract audit. JSON goes to stdout by default.\n--strict exits 2 if any task has a finding or is unassessed; findings are review items, not proven errors.\nInput/configuration errors exit 1. No tools or models are executed.');
  process.exit(args.includes('--help') ? 0 : 1);
}
try {
  if (args.slice(1).some(a => !['--csv', '--strict'].includes(a))) throw new Error('Unknown option. Use --help.');
  if (statSync(args[0]).size > MAX_BYTES) throw new Error('Use a JSON file smaller than 5 MB.');
  const report = auditTasks(parseTasks(readFileSync(args[0], 'utf8')), args[0]);
  console.log(args.includes('--csv') ? toCSV(report).trimEnd() : JSON.stringify(report, null, 2));
  if (args.includes('--strict') && report.tasks.some(t => t.status !== 'inspected' || t.findings.length)) process.exitCode = 2;
} catch (error) {
  console.error(`Signal: ${error.message}`);
  process.exitCode = 1;
}
