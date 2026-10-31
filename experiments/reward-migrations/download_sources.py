#!/usr/bin/env python3
"""Fetch byte-pinned public research inputs, without running SQL or models.

Python 3.9+ standard library. Default core group is approximately 347 MB.
  python download_sources.py --output ./sources
  python download_sources.py --output ./sources --group core --group legacy
  python download_sources.py --output ./sources --verify-only
Keep download-manifest.json, bird-db-manifest.json and cohort-357.json beside
this script. No credentials or remote inference endpoints are used.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import tempfile
import urllib.request
import zipfile


def sha256(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def safe_path(root, relative):
    part = PurePosixPath(relative)
    if part.is_absolute() or '..' in part.parts or '\\' in relative:
        raise ValueError('Unsafe source path: ' + relative)
    destination = root.joinpath(*part.parts)
    if not destination.resolve().is_relative_to(root.resolve()):
        raise ValueError('Source path escapes output directory')
    return destination


def verified(path, expected):
    return path.is_file() and path.stat().st_size == expected['bytes'] and sha256(path) == expected['sha256']


def download(root, entry, verify_only):
    target = safe_path(root, entry['path'])
    if verified(target, entry):
        return
    if verify_only:
        raise ValueError('Missing or mismatched source: ' + entry['path'])
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as out:
            temporary = Path(out.name)
            with urllib.request.urlopen(entry['url'], timeout=90) as response:
                for chunk in iter(lambda: response.read(8 * 1024 * 1024), b''):
                    out.write(chunk)
        if not verified(temporary, entry):
            raise ValueError('Downloaded bytes do not match pin: ' + entry['path'])
        os.replace(temporary, target)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def extract_zip(archive, root):
    with zipfile.ZipFile(archive) as z:
        for item in z.infolist():
            safe_path(root, item.filename)
            if stat.S_ISLNK(item.external_attr >> 16):
                raise ValueError('Archive symlinks are not supported')
        z.extractall(root)


def verify_cohort(root, specification):
    old_path = safe_path(root, specification['old_path'])
    new_path = safe_path(root, specification['new_path'])
    assert sha256(old_path) == specification['old_sha256']
    assert sha256(new_path) == specification['new_sha256']
    old = json.loads(old_path.read_text())
    new = json.loads(new_path.read_text())
    old_map = {str(r['question_id']): (i, r) for i, r in enumerate(old)}
    assert len(old_map) == len(old)
    assert len({str(r['question_id']) for r in new}) == len(new)
    actual = []
    for j, row in enumerate(new):
        i, previous = old_map[str(row['question_id'])]
        if all(previous[k] == row[k] for k in ('db_id', 'question', 'evidence')):
            contract = {k: previous[k] for k in ('db_id', 'question', 'evidence')}
            digest = hashlib.sha256(json.dumps(contract, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
            actual.append({'question_id': str(row['question_id']), 'db_id': row['db_id'], 'old_row_index': i, 'new_row_index': j, 'input_contract_sha256': digest, 'reference_sql_bytes_changed': previous['SQL'] != row['SQL']})
    actual.sort(key=lambda r: int(r['question_id']))
    assert actual == specification['rows'], 'Cohort differs from pinned specification'
    assert len(actual) == specification['count'] == 357


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--group', action='append', choices=['core', 'legacy', 'candidates'])
    ap.add_argument('--verify-only', action='store_true')
    args = ap.parse_args()
    groups = set(args.group or ['core'])
    here = Path(__file__).resolve().parent
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((here / 'download-manifest.json').read_text())
    selected = [f for f in manifest['files'] if f['group'] in groups]
    for entry in selected:
        download(root, entry, args.verify_only)
    if 'core' in groups:
        db_manifest = json.loads((here / 'bird-db-manifest.json').read_text())
        dbs_ready = all(verified(safe_path(root, f['path']), f) for f in db_manifest['databases'])
        if not dbs_ready and not args.verify_only:
            extract_zip(root / 'bird-dev-20240627.zip', root / 'bird-dev')
            nested = root / 'bird-dev/dev_20240627/dev_databases.zip'
            extract_zip(nested, root / 'bird-dev/dev_20240627')
        for entry in db_manifest['databases']:
            if not verified(safe_path(root, entry['path']), entry):
                raise ValueError('Database bytes differ: ' + entry['path'])
        verify_cohort(root, json.loads((here / 'cohort-357.json').read_text()))
    print(json.dumps({'verified_source_files': len(selected), 'groups': sorted(groups), 'databases': 11 if 'core' in groups else 0, 'cohort': 357 if 'core' in groups else None}))


if __name__ == '__main__':
    main()
