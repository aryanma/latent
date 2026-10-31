"""Reproduce the frozen-input SQL reward migration study, without model calls.

Run download_sources.py first. Reference execution and candidate evaluation are
separate stages so model generation never needs access to revised answers.
"""

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import sqlite3
import time

from latent_migration import sql as engine
from latent_migration.contract import digest
from admission import admit


OLD = "bird-mini-dev-previous/mini_dev_sqlite.json"
NEW = "arcwise-plat-hf/arcwise_plat_sql_only_with_diff.json"
OCTOBER = "bird-mini-dev/data/mini_dev_sqlite.jsonl"
QUERY_TIMEOUT = 60.0
INPUT_FIELDS = ("db_id", "question", "evidence")


def load(path):
    text = Path(path).read_text()
    return [json.loads(line) for line in text.splitlines() if line.strip()] if str(path).endswith(".jsonl") else json.loads(text)


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
    temp.replace(path)


def keyed(rows):
    result = {str(row["question_id"]): row for row in rows}
    if len(result) != len(rows):
        raise ValueError("Duplicate question identity in source")
    return result


def verify_sources(sources, manifest):
    for name in (OLD, NEW, OCTOBER):
        item = next(item for item in manifest["files"] if item["path"] == name)
        if engine.file_hash(sources / name) != item["sha256"]:
            raise ValueError("Source changed: " + name)


def inventory(sources):
    previous, revised = keyed(load(sources / OLD)), keyed(load(sources / NEW))
    old, new = list(previous.values()), list(revised.values())
    rows, counts = [], Counter()
    for key in sorted(set(previous) | set(revised), key=int):
        before, after = previous.get(key), revised.get(key)
        if before is None or after is None:
            kind = "added" if before is None else "removed"
            rows.append({"question_id": key, "classification": kind})
            counts[kind] += 1
            continue
        if before["db_id"] != after["db_id"]:
            raise ValueError("Lineage requires review: database changed under legacy ID " + key)
        changed = [field for field in INPUT_FIELDS if before.get(field) != after.get(field)]
        gold_changed = before["SQL"] != after["SQL"]
        kind = "changed_input" if changed else ("reference_edit" if gold_changed else "unchanged")
        counts[kind] += 1
        rows.append({"question_id": key, "db_id": before["db_id"], "classification": kind,
                     "changed_input_fields": changed, "reference_changed": gold_changed,
                     "old_input_digest": digest({f: before.get(f) for f in INPUT_FIELDS}),
                     "new_input_digest": digest({f: after.get(f) for f in INPUT_FIELDS})})
    october = load(sources / OCTOBER)
    old_inputs = Counter(digest({f: item.get(f) for f in INPUT_FIELDS}) for item in old)
    oct_inputs = Counter(digest({f: item.get(f) for f in INPUT_FIELDS}) for item in october)
    # This inventory does not establish new-release lineage. A reused bare
    # numeric ID is specifically NOT accepted as a cross-release primary key.
    return {"counts": dict(counts), "old_count": len(old), "revised_count": len(new),
            "same_input_count": counts["reference_edit"] + counts["unchanged"],
            "october_release_count": len(october),
            "october_exact_input_content_matches": sum((old_inputs & oct_inputs).values()),
            "rows": rows}


def db_catalog(sources, manifest):
    result = {}
    for item in manifest["databases"]:
        path = sources / item["path"]
        if engine.file_hash(path) != item["sha256"]:
            raise ValueError("Database changed: " + item["path"])
        result[path.stem] = {"path": str(path), "sha256": item["sha256"]}
    return result


def job(db, query, cache_root):
    provenance = {"database_sha256": db["sha256"], "query_sha256": engine.sha256(query.encode()).hexdigest(),
                  "executor_sha256": engine.file_hash(engine.__file__),
                  "sqlite_version": sqlite3.sqlite_version, "comparator": engine.COMPARATOR,
                  "runtime": engine.runtime_fingerprint(),
                  "clock": engine.CLOCK, "clock_adapter": engine.CLOCK_ADAPTER,
                  "timeout_seconds": QUERY_TIMEOUT, "max_rows": engine.MAX_ROWS}
    key = digest(provenance)
    return {"key": key, "db_path": db["path"], "query": query,
            "provenance": provenance, "cache_path": str(cache_root / (key + ".json"))}


def execute_job(item):
    path = Path(item["cache_path"])
    if path.exists():
        result = load(path)
        if result["provenance"] != item["provenance"]:
            raise ValueError("Cache provenance mismatch")
        return item["key"], result, True
    result = {"provenance": item["provenance"],
              "execution": engine.execute(item["db_path"], item["query"], timeout=QUERY_TIMEOUT)}
    write(path, result)
    return item["key"], result, False


def run_jobs(jobs, workers):
    unique = {item["key"]: item for item in jobs}
    result, cached = {}, 0
    with ProcessPoolExecutor(max_workers=workers) as pool:
        pending = [pool.submit(execute_job, item) for item in unique.values()]
        for i, future in enumerate(as_completed(pending), 1):
            key, record, hit = future.result()
            result[key] = record
            cached += hit
            if i % 50 == 0 or i == len(pending):
                print(f"queries {i}/{len(pending)}; cache hits {cached}", flush=True)
    return result, cached


def references(sources, out, dbs, inv, workers):
    before, after = keyed(load(sources / OLD)), keyed(load(sources / NEW))
    rows, jobs = [], []
    for item in inv["rows"]:
        if item["classification"] not in ("reference_edit", "unchanged"):
            continue
        key = item["question_id"]
        a = job(dbs[item["db_id"]], before[key]["SQL"], out / "query-cache")
        b = job(dbs[item["db_id"]], after[key]["SQL"], out / "query-cache")
        jobs.extend((a, b))
        rows.append(dict(item, old_reference=a["key"], new_reference=b["key"]))
    started = time.monotonic()
    records, cached = run_jobs(jobs, workers)
    for row in rows:
        a = records[row["old_reference"]]["execution"]
        b = records[row["new_reference"]]["execution"]
        row["same_result"] = None if a["status"] != "ok" or b["status"] != "ok" else bool(engine.reward(a, b))
        row["old_status"], row["new_status"] = a["status"], b["status"]
    summary = {"cases": len(rows), "unique_queries": len(records), "cache_hits": cached,
               "seconds": round(time.monotonic() - started, 3),
               "result_changes": sum(r["same_result"] is False for r in rows),
               "same_results": sum(r["same_result"] is True for r in rows),
               "unresolved": sum(r["same_result"] is None for r in rows)}
    write(out / "references.json", {"summary": summary, "rows": rows})
    return summary


def evaluate(sources, out, dbs, predictions_path, generation, workers):
    """Candidate interchange is JSONL: {question_id, db_id, sql, ...provenance}."""
    reference = load(out / "references.json")
    before, after = keyed(load(sources / OLD)), keyed(load(sources / NEW))
    expected_rows = [row for row in inventory(sources)["rows"] if row["classification"] in ("unchanged", "reference_edit")]
    if [row["question_id"] for row in reference["rows"]] != [row["question_id"] for row in expected_rows]:
        raise ValueError("Reference cohort does not match the current pinned source inventory")
    admission = admit(generation, predictions_path, before, after, dbs, [row["question_id"] for row in expected_rows])
    write(out / "generation-admission.json", admission)
    # Never let a previous run's references silently certify a new executor.
    for row in reference["rows"]:
        for side, dataset in (("old", before), ("new", after)):
            key = row["question_id"]
            expected = job(dbs[dataset[key]["db_id"]], dataset[key]["SQL"], out / "query-cache")
            if row[side + "_reference"] != expected["key"]:
                raise ValueError("Stale reference dependency; rerun the references stage")
            cached = load(Path(expected["cache_path"]))
            if cached["provenance"] != expected["provenance"]:
                raise ValueError("Reference cache provenance mismatch")
    candidates = keyed(load(predictions_path))
    eligible = {row["question_id"] for row in reference["rows"]}
    if set(candidates) != eligible:
        raise ValueError("Predictions must contain exactly the frozen same-input cohort, including failures")
    jobs, by_id = [], {}
    for row in reference["rows"]:
        candidate = candidates[row["question_id"]]
        if candidate["db_id"] != row["db_id"]:
            raise ValueError("Prediction/database identity mismatch")
        if candidate["sql"] is None and candidate["status"] != "error":
            raise ValueError("Missing SQL without an explicit generation error")
        item = job(dbs[row["db_id"]], candidate["sql"] or "", out / "query-cache")
        jobs.append(item)
        by_id[row["question_id"]] = item["key"]
    records, cached = run_jobs(jobs, workers)
    result, matrix = [], Counter()
    for row in reference["rows"]:
        candidate = records[by_id[row["question_id"]]]["execution"]
        old = load(out / "query-cache" / (row["old_reference"] + ".json"))["execution"]
        new = load(out / "query-cache" / (row["new_reference"] + ".json"))["execution"]
        r0, r1 = engine.reward(candidate, old), engine.reward(candidate, new)
        # No model response is a generation failure, never a valid empty result.
        if not (candidates[row["question_id"]]["sql"] or "").strip():
            r0 = 0 if old["status"] == "ok" else None
            r1 = 0 if new["status"] == "ok" else None
        transition = "unresolved" if r0 is None or r1 is None else f"{r0}->{r1}"
        matrix[transition] += 1
        result.append(dict(row, candidate=by_id[row["question_id"]], old_reward=r0, new_reward=r1,
                           candidate_status=candidate["status"], transition=transition))
    summary = {"cases": len(result), "matrix": dict(matrix), "candidate_cache_hits": cached,
               "old_accepted": sum(row["old_reward"] == 1 for row in result),
               "new_accepted": sum(row["new_reward"] == 1 for row in result),
               "resolved_pairs": sum(row["transition"] != "unresolved" for row in result),
               "candidate_statuses": dict(Counter(row["candidate_status"] for row in result))}
    write(out / "results.json", {"predictions_sha256": engine.file_hash(predictions_path),
                                 "summary": summary, "rows": result})
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("inventory", "references", "evaluate"))
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--predictions", type=Path)
    parser.add_argument("--generation", type=Path, help="Frozen fresh-inference artifact directory")
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()
    here = Path(__file__).parent
    manifest = load(here / "download-manifest.json")
    verify_sources(args.sources, manifest)
    inv = inventory(args.sources)
    write(args.out / "inventory.json", inv)
    if args.stage == "inventory":
        print(json.dumps({k: v for k, v in inv.items() if k != "rows"}, indent=2))
        return
    db_manifest = load(here / "bird-db-manifest.json")
    dbs = db_catalog(args.sources, db_manifest)
    write(args.out / (args.stage + "-runtime.json"), {"created_utc": datetime.now(timezone.utc).isoformat(),
                                      "python": platform.python_version(), "sqlite": sqlite3.sqlite_version,
                                      "runtime_fingerprint": engine.runtime_fingerprint(),
                                      "platform": platform.platform(), "engine_sha256": engine.file_hash(engine.__file__),
                                      "study_sha256": engine.file_hash(__file__), "workers": args.workers,
                                      "query_timeout_seconds": QUERY_TIMEOUT, "comparator": engine.COMPARATOR,
                                      "clock": engine.CLOCK, "clock_adapter": engine.CLOCK_ADAPTER,
                                      "database_hashes": {key: item["sha256"] for key, item in dbs.items()}})
    if args.stage == "references":
        summary = references(args.sources, args.out, dbs, inv, args.workers)
    else:
        if not args.predictions or not args.generation:
            parser.error("evaluate requires --predictions and --generation")
        summary = evaluate(args.sources, args.out, dbs, args.predictions, args.generation, args.workers)
    # Detect any mutation during execution, even though connections are read-only.
    db_catalog(args.sources, db_manifest)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
