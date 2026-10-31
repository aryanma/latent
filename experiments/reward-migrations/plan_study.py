"""Apply the compatibility API to the admitted, single-action study records.

This is a post-run contract export, not an additional preregistered experiment.
The generation freeze and evaluated source identities are inputs. No model or
SQL execution occurs here. Source-level admission is independently reproducible
with verify_release.py --sources /path/to/downloaded/sources.
"""
from collections import Counter
from pathlib import Path
import json

from latent_migration.contract import Contract, digest, plan
from latent_migration.sql import file_hash


def build(root):
    def read(name):
        return json.loads((root / name).read_text())
    references = read("evaluation/references.json")
    runtime = read("evaluation/evaluate-runtime.json")
    candidates = {x["question_id"]: x for x in map(json.loads, (root / "generation/candidates.jsonl").read_text().splitlines())}
    policy = digest({"registration_sha256": file_hash(root / "generation/preregistration.json"),
                     "runtime_manifest_sha256": file_hash(root / "generation/full/runtime-manifest.json"),
                     "selection": "one greedy output; identity extraction; no retries or tools"})
    interface = digest({"action": "one read-only SQLite query", "observation": "schema, question, evidence only",
                        "executor_sha256": runtime["engine_sha256"], "sqlite_runtime": runtime["runtime_fingerprint"]})
    rows, counts = [], Counter()
    for row in references["rows"]:
        candidate = candidates[row["question_id"]]
        contracts = []
        for side in ("old", "new"):
            record = read("evaluation/query-cache/" + row[side + "_reference"] + ".json")
            grader = digest(record["provenance"])
            contracts.append(Contract(task="bird-legacy:" + row["db_id"] + ":" + row["question_id"],
                observation=candidate["prompt_text_sha256"], world=candidate["database_sha256"],
                interface=interface, grader=grader, terminal_private_reward=True,
                lineage_verified=True, policy=policy, world_visible_to_policy=False))
        decision = plan(*contracts)
        expected = "regrade" if row["reference_changed"] else "reuse"
        if decision["action"] != expected:
            raise ValueError("Unexpected contract decision for " + row["question_id"])
        counts[decision["action"]] += 1
        rows.append({"question_id": row["question_id"], "old": contracts[0].to_dict(),
                     "new": contracts[1].to_dict(), "decision": decision})
    return {"kind": "post-run compatibility export for the admitted single-action cohort",
            "lineage_basis": {"cohort_specification_sha256": file_hash(root / "cohort-357.json"),
                              "generation_admission_sha256": file_hash(root / "evaluation/generation-admission.json"),
                              "source_manifest_sha256": file_hash(root / "download-manifest.json")},
            "summary": dict(counts), "rows": rows}


if __name__ == "__main__":
    root = Path(__file__).resolve().parent
    result = build(root)
    (root / "evaluation/migration-plans.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result["summary"]))
