#!/usr/bin/env python3
"""Build a small actual-data SQLite fixture for the case1525 browser witness.

Python3.9+ standard library; no network, model, or original-database writes.
Keeps all original transactions_1k rows and their referenced customers.
Only these two user tables are created; SQLite creates sqlite_sequence itself.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile


HERE = Path(__file__).resolve().parent
SOURCE_QUERIES = {
    'customers': 'SELECT * FROM customers WHERE CustomerID IN (SELECT CustomerID FROM transactions_1k) ORDER BY CustomerID',
    'transactions_1k': 'SELECT * FROM transactions_1k ORDER BY TransactionID',
}


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def digest_rows(rows):
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def read_only(path):
    return sqlite3.connect(path.resolve().as_uri() + '?mode=ro&immutable=1', uri=True)


def query_results(path, queries):
    with read_only(path) as c:
        return {name: [list(row) for row in c.execute(sql).fetchall()] for name, sql in queries.items()}


def constraints(path):
    with read_only(path) as c:
        return {'integrity_check': [list(r) for r in c.execute('PRAGMA integrity_check')],
                'foreign_key_check': [list(r) for r in c.execute('PRAGMA foreign_key_check')],
                'tables': [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")],
                'transaction_count': c.execute('SELECT COUNT(*) FROM transactions_1k').fetchone()[0],
                'customer_count': c.execute('SELECT COUNT(*) FROM customers').fetchone()[0]}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source-db', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    source = args.source_db.resolve(strict=True)
    output = args.out.resolve()
    if output.exists():
        raise ValueError('Refusing to overwrite an existing fixture')
    spec = json.loads((HERE / 'fixture-inputs.json').read_text())
    assert sha(source) == spec['source_database_sha256'], 'Original database pin mismatch'
    schema, data, source_counts, source_constraints = {}, {}, {}, {}
    with read_only(source) as c:
        for name, select in SOURCE_QUERIES.items():
            schema[name] = c.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()[0]
            data[name] = c.execute(select).fetchall()
            source_counts[name] = c.execute('SELECT COUNT(*) FROM ' + name).fetchone()[0]
            source_constraints[name] = {
                'columns': [list(r) for r in c.execute('PRAGMA table_info(' + name + ')')],
                'foreign_keys': [list(r) for r in c.execute('PRAGMA foreign_key_list(' + name + ')')],
                'indexes': [list(r) for r in c.execute('PRAGMA index_list(' + name + ')')],
            }
        sequence = c.execute("SELECT seq FROM sqlite_sequence WHERE name='transactions_1k'").fetchone()[0]
    assert len(data['customers']) == 517 and len(data['transactions_1k']) == 1000
    output.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(output) as c:
        c.execute('PRAGMA page_size=4096')
        c.execute('PRAGMA foreign_keys=ON')
        assert c.execute('PRAGMA foreign_keys').fetchone()[0] == 1
        for name in ('customers', 'transactions_1k'):
            c.execute(schema[name])
            placeholders = ','.join('?' for _ in data[name][0])
            c.executemany('INSERT INTO ' + name + ' VALUES (' + placeholders + ')', data[name])
        assert c.execute("SELECT seq FROM sqlite_sequence WHERE name='transactions_1k'").fetchone()[0] == sequence
        c.commit()
    before_hash = sha(output)
    with read_only(output) as c:
        for name in ('customers', 'transactions_1k'):
            assert c.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()[0] == schema[name]
            selected = c.execute(SOURCE_QUERIES[name]).fetchall()
            assert selected == data[name], 'Projected source rows changed'
            assert [list(r) for r in c.execute('PRAGMA table_info(' + name + ')')] == source_constraints[name]['columns']
            assert [list(r) for r in c.execute('PRAGMA foreign_key_list(' + name + ')')] == source_constraints[name]['foreign_keys']
            assert [list(r) for r in c.execute('PRAGMA index_list(' + name + ')')] == source_constraints[name]['indexes']
    baseline = query_results(output, spec['queries'])
    full_baseline = query_results(source, spec['queries'])
    assert baseline == full_baseline == spec['expected_baseline']
    before_constraints = constraints(output)
    assert before_constraints['tables'] == ['customers', 'sqlite_sequence', 'transactions_1k']
    assert before_constraints['integrity_check'] == [['ok']]
    assert before_constraints['foreign_key_check'] == []
    # Verify the browser's precise insertion on a separate copy; leave the
    # deliverable baseline untouched so reset can reload its original bytes.
    with tempfile.TemporaryDirectory(prefix='latent-fixture-check-') as d:
        after = Path(d) / 'mutated.sqlite'
        shutil.copyfile(output, after)
        with sqlite3.connect(after) as c:
            c.execute('PRAGMA foreign_keys=ON')
            c.execute(spec['mutation']['statement'], spec['mutation']['parameters'])
            c.commit()
        after_results = query_results(after, spec['queries'])
        assert after_results == spec['expected_after_insert']
        after_constraints = constraints(after)
        assert after_constraints['integrity_check'] == [['ok']]
        assert after_constraints['foreign_key_check'] == []
        assert after_constraints['transaction_count'] == 1001
        assert after_constraints['customer_count'] == 517
    assert sha(output) == before_hash, 'Baseline fixture was modified during verification'
    assert sha(source) == spec['source_database_sha256'], 'Original database changed'
    manifest = {
        'format': 'latent-browser-sql-witness/v1', 'question_id': '1525',
        'fixture': {'file': output.name, 'bytes': output.stat().st_size, 'sha256': before_hash},
        'source': {'database_sha256': spec['source_database_sha256'], 'url': spec['source_database_url'],
                   'release': spec['source_database_release'], 'row_counts': source_counts},
        'projection': {'queries': SOURCE_QUERIES, 'row_counts': {k: len(v) for k, v in data.items()},
                       'ordered_row_hashes': {k: digest_rows(v) for k, v in data.items()},
                       'original_create_table_sql': schema, 'declared_constraints': source_constraints,
                       'all_transactions_preserved': True, 'all_referenced_customers_preserved': True,
                       'omitted_customers': source_counts['customers'] - len(data['customers']),
                       'omitted_user_tables': ['gasstations', 'products', 'yearmonth'],
                       'internal_table': 'sqlite_sequence is required by the unchanged AUTOINCREMENT declaration'},
        'queries': spec['queries'], 'baseline_results': baseline, 'after_insert_results': after_results,
        'mutation': {'statement': spec['mutation']['statement'], 'parameters': spec['mutation']['parameters']},
        'constraints_before': before_constraints, 'constraints_after_insert': after_constraints,
        'source_unchanged': True, 'baseline_fixture_unchanged_after_test': True,
        'full_database_witness_results_sha256': spec['source_witness_results_sha256'],
        'matches_full_database_baseline_and_mutated_witness': True,
        'runtime': {'sqlite_version': sqlite3.sqlite_version, 'created_utc': datetime.now(timezone.utc).isoformat()},
        'creator_sha256': sha(Path(__file__)), 'inputs_sha256': sha(HERE / 'fixture-inputs.json'),
        'license': spec['license'], 'license_url': spec['license_url'], 'attribution': spec['attribution'],
        'changes_notice': 'Projection to two original user tables; all1000 transactions retained and only their517 referenced customers retained. No retained cell values or CREATE TABLE declarations changed. Counterfactual insertion is optional and separately documented.',
        'limitations': ['Preserves the three provided queries and this documented insertion, not arbitrary SQL over all original data.',
                        'Queries counting all original customers or using omitted tables are not equivalent on this fixture.',
                        'This single post-hoc counterexample is not a model failure-frequency estimate.'],
    }
    manifest_path = output.with_suffix('.manifest.json')
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False, allow_nan=False) + '\n')
    print(json.dumps({'fixture': manifest['fixture'], 'rows': manifest['projection']['row_counts'],
                      'baseline': baseline, 'after_insert': after_results, 'manifest': str(manifest_path)}, indent=2))


if __name__ == '__main__':
    main()
