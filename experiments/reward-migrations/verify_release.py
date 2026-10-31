"""Verify packaged evidence and rederive labels; optionally admit downloaded inputs.

The default performs no network requests, model inference, or SQL execution.
It checks result fingerprints, not complete result rows. Use study.py to
independently reexecute queries against the pinned full databases.
"""
import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path

from admission import FROZEN_GENERATION, admit
from latent_migration import sql as engine
from latent_migration.contract import digest


ROOT = Path(__file__).resolve().parent
PINNED = {
    "generation/artifact-freeze.json": FROZEN_GENERATION,
    "counterexample/artifact-freeze.json": "87ed0c5064cdc39dd741d3a0684456a311cc2ac296be8fa7e7b77fc124ceb6ff",
    "browser-fixture/artifact-manifest.json": "a93cf6edf561efc9477cbbfed4658321b4217523d72536acb61bd72c17ee3249",
    "regenerate/package-manifest.json": "2e8a5602e515f0d8dc19bca474c22795182b9d213c6b1bca23067d6ed6fdee11",
}


def read(path):
    return json.loads(Path(path).read_text())


def require(condition, message):
    if not condition:
        raise ValueError(message)


def verify_manifest(path):
    root = path.parent
    entries = read(path)["files"]
    if isinstance(entries, dict):
        entries = [dict(item, path=name) for name, item in entries.items()]
    for item in entries:
        target = (root / item["path"]).resolve()
        require(root.resolve() in target.parents, "Artifact path escapes root")
        require(target.is_file() and target.stat().st_size == item["bytes"]
                and engine.file_hash(target) == item["sha256"],
                "Artifact mismatch: " + str(target))
    return len(entries)


def verify(root=ROOT, sources=None):
    root = Path(root).resolve()
    count = verify_manifest(root / "ARTIFACTS.json")
    for name, expected in PINNED.items():
        require(engine.file_hash(root / name) == expected, "Original freeze differs: " + name)
        verify_manifest(root / name)
    runtime = read(root / "evaluation/evaluate-runtime.json")
    require(runtime["engine_sha256"] == engine.file_hash(root / "latent_migration/sql.py"), "Executor changed")
    require(runtime["study_sha256"] == engine.file_hash(root / "study.py"), "Study code changed")
    cache = {}
    for path in (root / "evaluation/query-cache").glob("*.json"):
        obj = read(path)
        p = obj["provenance"]
        require(path.stem == digest(p), "Cache key differs: " + path.name)
        for key, expected in {
            "executor_sha256": runtime["engine_sha256"], "runtime": runtime["runtime_fingerprint"],
            "clock": runtime["clock"], "clock_adapter": runtime["clock_adapter"],
            "comparator": runtime["comparator"], "timeout_seconds": runtime["query_timeout_seconds"],
            "max_rows": engine.MAX_ROWS,
        }.items():
            require(p[key] == expected, "Cache dependency mismatch: " + key)
        require(p["database_sha256"] in runtime["database_hashes"].values(), "Unknown database")
        require(obj["execution"]["query_sha256"] == p["query_sha256"], "Executed query differs")
        cache[path.stem] = obj
    results = read(root / "evaluation/results.json")
    references = read(root / "evaluation/references.json")
    candidates = [json.loads(line) for line in (root / "generation/candidates.jsonl").read_text().splitlines()]
    require(engine.file_hash(root / "generation/candidates.jsonl") == results["predictions_sha256"], "Candidate set differs")
    ids = [x["question_id"] for x in candidates]
    require(len(set(ids)) == len(ids) == 357, "Invalid candidate cohort")
    require(ids == [x["question_id"] for x in results["rows"]]
            == [x["question_id"] for x in references["rows"]], "Cohort/order differs")
    require(ids == [x["question_id"] for x in read(root / "cohort-357.json")["rows"]], "Frozen cohort differs")
    matrix, statuses, reference_counts = Counter(), Counter(), Counter()
    old_accepted = new_accepted = 0
    for row, ref, candidate in zip(results["rows"], references["rows"], candidates):
        require(row["db_id"] == ref["db_id"] == candidate["db_id"], "Database identity differs")
        raw = read(root / "generation" / candidate["raw_record"])
        require(candidate["sql"] == raw["raw_output"], "Candidate is not raw model text")
        require(engine.file_hash(root / "generation" / candidate["raw_record"]) == candidate["raw_record_sha256"], "Raw trace differs")
        records = [cache[row[key]] for key in ("candidate", "old_reference", "new_reference")]
        require(all(x["provenance"]["database_sha256"] == runtime["database_hashes"][row["db_id"]] for x in records), "Wrong database in cache")
        require(records[0]["provenance"]["query_sha256"] == sha256(candidate["sql"].encode()).hexdigest(), "Candidate query hash differs")
        execution, before, after = [x["execution"] for x in records]
        r0, r1 = engine.reward(execution, before), engine.reward(execution, after)
        if not candidate["sql"].strip():
            r0 = 0 if before["status"] == "ok" else None
            r1 = 0 if after["status"] == "ok" else None
        transition = "unresolved" if r0 is None or r1 is None else f"{r0}->{r1}"
        require((r0, r1, transition) == (row["old_reward"], row["new_reward"], row["transition"]), "Stored reward differs")
        require(ref["old_reference"] == row["old_reference"] and ref["new_reference"] == row["new_reference"], "Reference linkage differs")
        same = None if before["status"] != "ok" or after["status"] != "ok" else bool(engine.reward(before, after))
        require(ref["same_result"] is same, "Reference comparison differs")
        reference_counts[same] += 1
        matrix[transition] += 1
        statuses[execution["status"]] += 1
        old_accepted += r0 == 1
        new_accepted += r1 == 1
    expected_matrix = {"1->1": 193, "1->0": 17, "0->1": 13, "0->0": 132, "unresolved": 2}
    require(matrix == results["summary"]["matrix"] == expected_matrix, "Primary matrix differs")
    require(statuses == results["summary"]["candidate_statuses"], "Candidate statuses differ")
    require((old_accepted, new_accepted) == (210, 206), "Accepted totals differ")
    require(reference_counts == {True: 286, False: 70, None: 1}, "Reference output changes differ")

    sensitivity = read(root / "evaluation/parser-sensitivity.json")
    require(sensitivity["parser_sha256"] == engine.file_hash(root / "parser_sensitivity.py"), "Sensitivity parser changed")
    from parser_sensitivity import extract_fence
    alternate, transformed = Counter(), 0
    require(ids == [x["question_id"] for x in sensitivity["rows"]], "Sensitivity cohort differs")
    for row, primary, candidate in zip(sensitivity["rows"], results["rows"], candidates):
        parsed = extract_fence(candidate["sql"])
        require(row["sql"] == parsed and row["transformed"] == (parsed != candidate["sql"]), "Parser transformation differs")
        transformed += row["transformed"]
        record = cache[row["candidate"]]
        require(record["provenance"]["query_sha256"] == sha256(parsed.encode()).hexdigest(), "Parsed query differs")
        a = engine.reward(record["execution"], cache[primary["old_reference"]]["execution"])
        b = engine.reward(record["execution"], cache[primary["new_reference"]]["execution"])
        label = "unresolved" if a is None or b is None else f"{a}->{b}"
        require((a, b, label) == (row["old_reward"], row["new_reward"], row["transition"]), "Sensitivity reward differs")
        alternate[label] += 1
    require(alternate == sensitivity["summary"]["matrix"] == {"1->1": 212, "0->0": 104, "1->0": 24, "0->1": 15, "unresolved": 2}, "Sensitivity matrix differs")
    require(transformed == sensitivity["summary"]["outer_fences_extracted"] == 50, "Fence count differs")

    from plan_study import build
    plans = build(root)
    require(plans == read(root / "evaluation/migration-plans.json"), "Compatibility decisions differ")
    require(plans["summary"] == {"reuse": 258, "regrade": 99}, "Compatibility totals differ")

    if sources:
        from study import OLD, NEW, load, keyed, verify_sources, db_catalog, inventory
        sources = Path(sources)
        verify_sources(sources, read(root / "download-manifest.json"))
        require(inventory(sources) == read(root / "evaluation/inventory.json"), "Source inventory differs")
        dbs = db_catalog(sources, read(root / "bird-db-manifest.json"))
        admit(root / "generation", root / "generation/candidates.jsonl", keyed(load(sources / OLD)), keyed(load(sources / NEW)), dbs, ids)
    return {"verified_files": count, "cached_executions": len(cache), "primary_matrix": dict(matrix),
            "old_accepted": old_accepted, "new_accepted": new_accepted,
            "parser_sensitivity_matrix": dict(alternate), "downloaded_sources_admitted": bool(sources),
            "compatibility_decisions": plans["summary"], "queries_reexecuted": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(sources=args.sources), indent=2))
