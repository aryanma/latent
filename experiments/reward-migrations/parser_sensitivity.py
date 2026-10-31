"""Post-hoc sensitivity: interpret one outer SQL fence without repairing SQL.

The primary analysis always uses unchanged generated text. This secondary pass
keeps every generation and both references fixed, changes only this declared
output parser, and releases every transformed query and result.
"""
import argparse
from collections import Counter
from pathlib import Path
import re

from admission import admit
from latent_migration import sql as engine
from study import (OLD, NEW, load, write, keyed, inventory, verify_sources,
                   db_catalog, job, run_jobs)


def extract_fence(text):
    match = re.fullmatch(r"\s*```(?:sql|sqlite)?[ \t]*\r?\n(.*?)\r?\n```[ \t]*\s*", text, re.S | re.I)
    if match and "```" not in match.group(1):
        return match.group(1)
    return text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True, help="Existing verified primary evaluation directory")
    parser.add_argument("--generation", type=Path, required=True)
    args = parser.parse_args()
    here = Path(__file__).parent
    verify_sources(args.sources, load(here / "download-manifest.json"))
    dbs = db_catalog(args.sources, load(here / "bird-db-manifest.json"))
    old, new = keyed(load(args.sources / OLD)), keyed(load(args.sources / NEW))
    expected = [row for row in inventory(args.sources)["rows"] if row["classification"] in ("reference_edit", "unchanged")]
    predictions = args.generation / "candidates.jsonl"
    admitted = admit(args.generation, predictions, old, new, dbs, [r["question_id"] for r in expected])
    refs = load(args.out / "references.json")["rows"]
    if [r["question_id"] for r in refs] != [r["question_id"] for r in expected]:
        raise ValueError("Reference cohort changed")
    candidates = keyed(load(predictions))
    jobs, changed = [], []
    for row in refs:
        key = row["question_id"]
        for side, data in (("old", old), ("new", new)):
            expected_job = job(dbs[data[key]["db_id"]], data[key]["SQL"], args.out / "query-cache")
            if row[side + "_reference"] != expected_job["key"]:
                raise ValueError("Reference dependencies changed")
            if load(expected_job["cache_path"])["provenance"] != expected_job["provenance"]:
                raise ValueError("Reference cache provenance mismatch")
        raw = candidates[key]["sql"] or ""
        parsed = extract_fence(raw)
        if parsed != raw:
            changed.append(key)
        item = job(dbs[row["db_id"]], parsed, args.out / "query-cache")
        jobs.append(item)
    records, cached = run_jobs(jobs, 2)
    rows, matrix = [], Counter()
    for row, item in zip(refs, jobs):
        execution = records[item["key"]]["execution"]
        a = load(args.out / "query-cache" / (row["old_reference"] + ".json"))["execution"]
        b = load(args.out / "query-cache" / (row["new_reference"] + ".json"))["execution"]
        r0, r1 = engine.reward(execution, a), engine.reward(execution, b)
        transition = "unresolved" if r0 is None or r1 is None else f"{r0}->{r1}"
        matrix[transition] += 1
        rows.append({"question_id": row["question_id"], "sql": item["query"], "candidate": item["key"],
                     "transformed": row["question_id"] in changed, "old_reward": r0, "new_reward": r1,
                     "transition": transition, "execution_status": execution["status"]})
    result = {"kind": "post-hoc parser sensitivity, not the primary extraction policy",
              "parser_sha256": engine.file_hash(__file__), "admission": admitted,
              "summary": {"cases": len(rows), "outer_fences_extracted": len(changed),
                          "matrix": dict(matrix), "cache_hits": cached,
                          "old_accepted": sum(r["old_reward"] == 1 for r in rows),
                          "new_accepted": sum(r["new_reward"] == 1 for r in rows)}, "rows": rows}
    db_catalog(args.sources, load(here / "bird-db-manifest.json"))
    write(args.out / "parser-sensitivity.json", result)
    print(result["summary"])


if __name__ == "__main__":
    main()
