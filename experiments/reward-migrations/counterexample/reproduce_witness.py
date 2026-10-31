#!/usr/bin/env python3
"""Reproduce one constructed SQL counterexample without inference or source writes.

Requires Python 3.9+ and the byte-pinned BIRD debit_card_specializing.sqlite.
Keep inputs.json, executor_snapshot.py, and prompt_protocol.py beside this file.
The output directory must not already exist. It contains a mutated database copy.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import platform
import shutil
import sqlite3
import time


HERE = Path(__file__).resolve().parent


def file_hash(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    obj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


def quote(identifier):
    return '"' + identifier.replace('"', '""') + '"'


def read_connection(path):
    return sqlite3.connect(path.resolve().as_uri() + '?mode=ro&immutable=1', uri=True)


def inspect(path, executor):
    with read_connection(path) as c:
        schema = c.execute("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name COLLATE BINARY").fetchall()
        tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name COLLATE BINARY")]
        constraints, contents = {}, {}
        for name in tables:
            constraints[name] = {
                'table_info': c.execute('PRAGMA table_info(' + quote(name) + ')').fetchall(),
                'foreign_keys': c.execute('PRAGMA foreign_key_list(' + quote(name) + ')').fetchall(),
                'indexes': c.execute('PRAGMA index_list(' + quote(name) + ')').fetchall(),
            }
            h, count = hashlib.sha256(), 0
            for row in c.execute('SELECT rowid,* FROM ' + quote(name) + ' ORDER BY rowid'):
                h.update((executor.row_key(row) + '\n').encode())
                count += 1
            contents[name] = {'rows': count, 'ordered_rowid_content_sha256': h.hexdigest()}
        ddls = c.execute("SELECT name,sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND sql IS NOT NULL ORDER BY name COLLATE BINARY").fetchall()
        ddl = '\n\n'.join(row[1].rstrip(';\n ') + ';' for row in ddls)
        counts = c.execute("SELECT COUNT(*), COUNT(DISTINCT t.CustomerID), SUM(CASE WHEN c.Currency='EUR' THEN 1 ELSE 0 END), COUNT(DISTINCT CASE WHEN c.Currency='EUR' THEN t.CustomerID END) FROM transactions_1k t JOIN customers c ON c.CustomerID=t.CustomerID WHERE t.Date='2012-08-25'").fetchone()
        return {'schema': schema, 'schema_sha256': canonical_hash(schema),
                'constraints': constraints, 'table_contents': contents, 'ddl': ddl,
                'ddl_sha256': hashlib.sha256(ddl.encode()).hexdigest(),
                'integrity_check': c.execute('PRAGMA integrity_check').fetchall(),
                'foreign_key_check': c.execute('PRAGMA foreign_key_check').fetchall(),
                'date_subset': dict(zip(['transactions', 'distinct_customers', 'eur_transactions', 'distinct_eur_customers'], counts)),
                'sqlite_sequence': c.execute('SELECT * FROM sqlite_sequence ORDER BY name').fetchall()}


def grade(path, spec, executor):
    outputs = {name: executor.execute(path, query, timeout=60.0, clock=spec['clock'])
               for name, query in [('candidate', spec['candidate']['sql']),
                                   ('old_reference', spec['old']['SQL']),
                                   ('new_reference', spec['new']['SQL'])]}
    if any(r['status'] != 'ok' for r in outputs.values()):
        raise RuntimeError('Witness execution unresolved: ' + json.dumps(outputs))
    return {'executions': outputs,
            'candidate_old_reward': executor.reward(outputs['candidate'], outputs['old_reference']),
            'candidate_new_reward': executor.reward(outputs['candidate'], outputs['new_reference'])}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source-db', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    source = args.source_db.resolve(strict=True)
    out = args.out.resolve()
    if out.exists():
        raise ValueError('Refusing to overwrite an existing witness directory')
    spec = json.loads((HERE / 'inputs.json').read_text())
    assert file_hash(source) == spec['database']['sha256'], 'Source database pin mismatch'
    assert file_hash(HERE / 'executor_snapshot.py') == spec['executor_sha256']
    assert file_hash(HERE / 'prompt_protocol.py') == spec['protocol_sha256']
    executor = module('witness_executor', HERE / 'executor_snapshot.py')
    protocol = module('witness_protocol', HERE / 'prompt_protocol.py')
    started = time.monotonic()
    before = inspect(source, executor)
    assert before['integrity_check'] == [('ok',)]
    assert before['foreign_key_check'] == []
    assert protocol.messages_for(spec['old'], before['ddl']) == spec['prompt']['messages'], 'Schema renderer differs from actual recorded prompt'
    assert hashlib.sha256(spec['prompt']['prompt_text'].encode()).hexdigest() == spec['candidate']['prompt_text_sha256']
    before_result = grade(source, spec, executor)
    assert before_result['candidate_new_reward'] == 1, 'Candidate must match the revised reference on the original database'
    out.mkdir(parents=True)
    mutated = out / 'counterfactual.sqlite'
    shutil.copyfile(source, mutated)
    assert file_hash(mutated) == spec['database']['sha256']

    with sqlite3.connect(mutated) as c:
        c.execute('PRAGMA foreign_keys=ON')
        assert c.execute('PRAGMA foreign_keys').fetchone()[0] == 1
        c.execute('BEGIN IMMEDIATE')
        columns = [r[1] for r in c.execute('PRAGMA table_info(transactions_1k)')]
        source_row = c.execute('SELECT * FROM transactions_1k WHERE TransactionID=?', (spec['mutation_selection']['source_transaction_id'],)).fetchone()
        assert source_row is not None
        source_values = dict(zip(columns, source_row))
        assert source_values['Date'] == spec['mutation_selection']['date']
        currency = c.execute('SELECT Currency FROM customers WHERE CustomerID=?', (source_values['CustomerID'],)).fetchone()
        assert currency == (spec['mutation_selection']['currency'],)
        # These relationships are semantically useful but are not declared FKs
        # on transactions_1k; report them separately from SQLite FK checks.
        links = {}
        for column, table in [('CustomerID', 'customers'), ('GasStationID', 'gasstations'), ('ProductID', 'products')]:
            links[column] = c.execute('SELECT COUNT(*) FROM ' + quote(table) + ' WHERE ' + quote(column) + '=?', (source_values[column],)).fetchone()[0]
            assert links[column] == 1
        max_id = c.execute('SELECT MAX(TransactionID) FROM transactions_1k').fetchone()[0]
        sequence = c.execute("SELECT seq FROM sqlite_sequence WHERE name='transactions_1k'").fetchone()[0]
        fresh_id = max(max_id, sequence) + 1
        inserted = list(source_row)
        inserted[columns.index('TransactionID')] = fresh_id
        statement = 'INSERT INTO transactions_1k (' + ','.join(quote(col) for col in columns) + ') VALUES (' + ','.join('?' for _ in columns) + ')'
        c.execute(statement, inserted)
        assert c.execute('SELECT * FROM transactions_1k WHERE TransactionID=?', (fresh_id,)).fetchone() == tuple(inserted)
        assert c.execute('PRAGMA foreign_key_check').fetchall() == []
        assert c.execute('PRAGMA integrity_check').fetchall() == [('ok',)]
        c.commit()
    after = inspect(mutated, executor)
    assert after['integrity_check'] == [('ok',)] and after['foreign_key_check'] == []
    assert after['schema'] == before['schema']
    assert after['constraints'] == before['constraints']
    assert after['ddl'] == before['ddl']
    assert protocol.messages_for(spec['old'], after['ddl']) == spec['prompt']['messages']
    for name, content in before['table_contents'].items():
        if name not in ('transactions_1k', 'sqlite_sequence'):
            assert after['table_contents'][name] == content, 'Unexpected change to another table'
    assert after['table_contents']['transactions_1k']['rows'] == before['table_contents']['transactions_1k']['rows'] + 1
    # Exact set differences prove all original transaction rows survive and
    # only the specified new row has appeared (PK makes each row unique).
    with read_connection(mutated) as c:
        c.execute('ATTACH DATABASE ? AS original', (source.as_uri() + '?mode=ro&immutable=1',))
        added = c.execute('SELECT * FROM main.transactions_1k EXCEPT SELECT * FROM original.transactions_1k').fetchall()
        removed = c.execute('SELECT * FROM original.transactions_1k EXCEPT SELECT * FROM main.transactions_1k').fetchall()
    assert added == [tuple(inserted)] and removed == []
    after_result = grade(mutated, spec, executor)
    assert after_result['candidate_new_reward'] == 0
    assert executor.reward(before_result['executions']['new_reference'], after_result['executions']['new_reference']) == 1
    assert file_hash(source) == spec['database']['sha256'], 'Original database changed'
    assert file_hash(HERE / 'executor_snapshot.py') == spec['executor_sha256']
    proof = {'question_id': spec['question_id'], 'selection': spec['selection'],
             'clock': spec['clock'], 'clock_adapter': executor.CLOCK_ADAPTER, 'comparator': executor.COMPARATOR,
             'source_sha256': spec['database']['sha256'], 'counterfactual_sha256': file_hash(mutated),
             'executor_sha256': spec['executor_sha256'], 'input_spec_sha256': file_hash(HERE / 'inputs.json'),
             'source_database_unchanged': True, 'schema_and_prompt_unchanged': True,
             'policy_prompt_sha256': spec['candidate']['prompt_text_sha256'],
             'mutation': {'statement': statement, 'parameters': inserted, 'columns': columns,
                          'source_row': source_values, 'fresh_primary_key': fresh_id,
                          'foreign_keys_enabled_during_insert': True, 'existing_parent_rows': links,
                          'exact_added_rows': added, 'exact_removed_rows': removed,
                          'changed_user_tables': ['transactions_1k'],
                          'internal_autoincrement_sequence_change': [before['sqlite_sequence'], after['sqlite_sequence']]},
             'before': before, 'after': after, 'before_result': before_result, 'after_result': after_result,
             'limitations': ['One post-hoc constructed counterfactual; not a model failure frequency estimate.',
                             'All declared SQLite constraints pass; undeclared business rules are not verified.',
                             'No inference is rerun. A recorded fixed query is reexecuted.',
                             'The original policy saw schema, question and evidence only, with no database tools or row samples; identical prompt is established for this one-shot protocol, not arbitrary interactive agents.',
                             'Execution agreement on the original database does not establish semantic equivalence of SQL queries.']}
    # Remove measured latency from the reproducible proof fingerprint only.
    stable = json.loads(json.dumps(proof))
    for phase in ('before_result', 'after_result'):
        for execution in stable[phase]['executions'].values():
            execution.pop('seconds', None)
    proof['proof_sha256_excluding_latency'] = canonical_hash(stable)
    proof['runtime'] = {'python': platform.python_version(), 'sqlite': sqlite3.sqlite_version,
                        'elapsed_seconds': round(time.monotonic() - started, 6),
                        'created_utc': datetime.now(timezone.utc).isoformat()}
    (out / 'results.json').write_text(json.dumps(proof, indent=2, ensure_ascii=False, allow_nan=False) + '\n')
    print(json.dumps({'before': before_result, 'after': after_result,
                      'mutation': proof['mutation'], 'proof_sha256_excluding_latency': proof['proof_sha256_excluding_latency']}, indent=2))


if __name__ == '__main__':
    main()
