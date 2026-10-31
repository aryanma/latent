import { createCounterexample } from './counterexample.mjs';

let sqliteLoader;

async function loadSQLite(document) {
  if (!sqliteLoader) {
    sqliteLoader = (async () => {
      const window = document.defaultView;
      if (!window.initSqlJs) {
        await new Promise((resolve, reject) => {
          const script = document.createElement('script');
          script.src = new URL('./vendor/sql-wasm.js', import.meta.url).href;
          script.onload = resolve;
          script.onerror = () => { script.remove(); reject(new Error('Local SQLite could not be loaded.')); };
          document.head.append(script);
        });
      }
      return window.initSqlJs({ locateFile: file => new URL(`./vendor/${file}`, import.meta.url).href });
    })().catch(error => { sqliteLoader = undefined; throw error; });
  }
  return sqliteLoader;
}

async function browserDatabase(document, manifest) {
  const SQL = await loadSQLite(document);
  const response = await fetch(new URL('../data/reward-migrations/browser-fixture.sqlite', import.meta.url));
  if (!response.ok) throw new Error('The published SQLite fixture could not be loaded.');
  const bytes = new Uint8Array(await response.arrayBuffer());
  const hash = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)))
    .map(value => value.toString(16).padStart(2, '0')).join('');
  if (bytes.byteLength !== manifest.fixture.bytes || hash !== manifest.fixture.sha256) {
    throw new Error('The fixture does not match its published fingerprint.');
  }
  return createCounterexample(SQL, bytes, manifest);
}

export function mountStudy(document, { databaseFactory = browserDatabase } = {}) {
  const source = document.getElementById('study-data');
  if (!source) return;
  const study = JSON.parse(source.textContent);
  const root = document.getElementById('recorded-witness');
  let currentCase = study.cases[0];
  let version = 'old';
  const setText = (id, text) => { document.getElementById(id).textContent = text; };
  const preview = execution => `${execution.distinct_rows} distinct result row${execution.distinct_rows === 1 ? '' : 's'}; preview: ${JSON.stringify(execution.preview)}`;

  function renderCase() {
    setText('case-question', currentCase.paraphrase);
    setText('case-id', `BIRD ${currentCase.id}`);
    setText('case-sql', currentCase.candidate_sql);
    setText('case-old-sql', currentCase.old_sql);
    setText('case-new-sql', currentCase.new_sql);
    setText('case-old-result', preview(currentCase.old_execution));
    setText('case-new-result', preview(currentCase.new_execution));
    setText('case-model-result', preview(currentCase.candidate_execution));
    setText('case-reward', String(currentCase[`${version}_reward`]));
    setText('case-verdict', currentCase[`${version}_reward`] ? 'Accepted by this reference' : 'Rejected by this reference');
    setText('case-explanation', currentCase[`${version}_explanation`]);
    setText('case-summary', `Recorded transition: ${currentCase.old_reward} → ${currentCase.new_reward}. The model output is identical in both passes.`);
    document.getElementById('case-record').setAttribute('href', `./experiments/reward-migrations/generation/full/${currentCase.id}.json`);
    for (const button of root.querySelectorAll('[data-case]')) {
      button.setAttribute('aria-pressed', String(button.dataset.case === currentCase.id));
    }
    for (const button of root.querySelectorAll('[data-version]')) {
      button.setAttribute('aria-pressed', String(button.dataset.version === version));
    }
  }

  for (const button of root.querySelectorAll('button')) {
    button.disabled = false;
    button.addEventListener('click', () => {
      if (button.dataset.case) currentCase = study.cases.find(item => item.id === button.dataset.case);
      if (button.dataset.version) version = button.dataset.version;
      renderCase();
    });
  }
  renderCase();

  const add = document.getElementById('add-transaction');
  const reset = document.getElementById('reset-transaction');
  const liveStatus = document.getElementById('live-status');
  let database;
  let busy = false;
  add.disabled = false;

  function renderWorld(result) {
    setText('live-candidate', `${result.candidate.toFixed(6)}%`);
    setText('live-reference', `${result.reference.toFixed(6)}%`);
    setText('live-reward', String(result.reward));
    setText('live-transactions', String(result.transactions));
    setText('live-customers', String(result.customers));
    setText('live-eur-transactions', String(result.eurTransactions));
    setText('live-eur-customers', String(result.eurCustomers));
    setText('live-world', result.mutated ? 'One transaction added' : 'Original data');
    liveStatus.textContent = result.mutated
      ? 'Executed locally. The same seven EUR customers now account for eight transactions. The model query is rejected.'
      : 'Executed locally. Both queries agree on the original data.';
    add.disabled = result.mutated;
    add.textContent = result.mutated ? 'Transaction added' : 'Add one transaction';
    reset.disabled = !result.mutated;
  }

  add.addEventListener('click', async () => {
    if (busy || add.disabled) return;
    busy = true;
    add.disabled = true;
    add.setAttribute('aria-busy', 'true');
    liveStatus.textContent = 'Loading and verifying local SQLite…';
    try {
      if (!database) database = await databaseFactory(document, study.browser);
      renderWorld(database.addTransaction());
    } catch (error) {
      liveStatus.textContent = `${error.message} The recorded results remain available in the reproduction package.`;
      add.disabled = false;
    } finally {
      busy = false;
      add.removeAttribute('aria-busy');
    }
  });

  reset.addEventListener('click', () => {
    if (!database || busy) return;
    renderWorld(database.reset());
  });
  return { dispose: () => database?.close() };
}

if (typeof document !== 'undefined') mountStudy(document);
