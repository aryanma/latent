"""Bind the study's fresh predictions to their frozen observations and lineage.

This validates the recorded artifacts without loading any model. Tokenizer-level
render/decode validation is also recorded by the separately frozen inference
validator. Hashes detect changes; they are not a claim of cryptographic
attestation of a remote inference service.
"""

from hashlib import sha256
import json
from pathlib import Path

from latent_migration.sql import file_hash


FROZEN_GENERATION = "0818a16cf6538b0d72a0c6d5bbf4c90592a1546c91e2abfdb1838fedc0c6074e"
SYSTEM = ("You translate a question into one read-only SQLite query. "
          "Use only the supplied database schema and the question's evidence. "
          "Return SQL only: no Markdown fences, explanation, or additional statements. "
          "Do not modify the database.")


def token_digest(ids):
    return sha256(json.dumps(ids, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def require(condition, reason):
    if not condition:
        raise ValueError("Generation admission failed: " + reason)


def admit(root, predictions_path, before, after, dbs, cohort_ids):
    root = Path(root).resolve()
    freeze_path = root / "artifact-freeze.json"
    require(file_hash(freeze_path) == FROZEN_GENERATION, "unexpected artifact freeze")
    freeze = read(freeze_path)
    for relative, item in freeze["files"].items():
        path = (root / relative).resolve()
        require(root in path.parents, "artifact path escapes its root")
        require(path.stat().st_size == item["bytes"] and file_hash(path) == item["sha256"], "changed artifact: " + relative)
    require(file_hash(predictions_path) == freeze["files"]["candidates.jsonl"]["sha256"], "candidate interchange changed")
    candidates = [json.loads(line) for line in Path(predictions_path).read_text().splitlines() if line.strip()]
    require([x["question_id"] for x in candidates] == list(cohort_ids), "cohort or order changed")
    prompts = {x["question_id"]: x for x in read(root / "prompts.json")}
    schemas = read(root / "schemas.json")
    runtime = read(root / "full/runtime-manifest.json")
    registration_hash = file_hash(root / "preregistration.json")
    for candidate in candidates:
        key, db_id = candidate["question_id"], candidate["db_id"]
        prompt = prompts[key]
        require(db_id == before[key]["db_id"] == after[key]["db_id"], "database identity differs")
        require(candidate["database_sha256"] == schemas[db_id]["database_sha256"] == dbs[db_id]["sha256"], "database bytes differ")
        messages = []
        for source in (before[key], after[key]):
            user = ("Database schema (SQLite DDL):\n" + schemas[db_id]["ddl"]
                    + "\n\nQuestion:\n" + source["question"]
                    + "\n\nEvidence:\n" + source["evidence"]
                    + "\n\nReturn exactly one read-only SQLite query answering the question.")
            messages.append([{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}])
        require(messages[0] == messages[1] == prompt["messages"], "model-visible messages differ")
        require(candidate["raw_record"] == "full/" + key + ".json", "unexpected record path")
        raw_path = root / candidate["raw_record"]
        require(file_hash(raw_path) == candidate["raw_record_sha256"], "raw record changed")
        raw = read(raw_path)
        require(raw["question_id"] == key and raw["db_id"] == db_id, "raw identity mismatch")
        require(raw["prompt_text"] == prompt["prompt_text"], "rendered context differs")
        require(sha256(raw["prompt_text"].encode()).hexdigest() == candidate["prompt_text_sha256"], "rendered context hash differs")
        require(raw["input_token_ids"] == prompt["input_token_ids"], "actual input tokens differ")
        require(token_digest(raw["input_token_ids"]) == candidate["actual_input_token_ids_sha256"], "input token digest differs")
        require(token_digest(raw["output_token_ids"]) == candidate["actual_output_token_ids_sha256"], "output token digest differs")
        require(sha256(raw["raw_output"].encode()).hexdigest() == candidate["raw_output_sha256"], "raw output digest differs")
        require(candidate["sql"] == (raw["raw_output"] if raw["status"] == "generated" else None), "SQL differs from generated output")
        require(candidate["model_revision"] == runtime["model_revision"], "model revision differs")
        require(candidate["preregistration_sha256"] == registration_hash, "generation protocol differs")
        require(candidate["runtime_manifest_sha256"] == file_hash(root / "full/runtime-manifest.json"), "runtime differs")
    return {"cases": len(candidates), "artifact_files_checked": len(freeze["files"]),
            "artifact_freeze_sha256": FROZEN_GENERATION, "predictions_sha256": file_hash(predictions_path),
            "same_messages_under_both_task_versions": True,
            "all_raw_outputs_preserved": True, "all_database_hashes_match": True,
            "prompt_and_token_artifacts_bound_to_candidates": True}
