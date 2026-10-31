"""Verify completed frozen inference and export raw SQL without modification."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from datetime import datetime, timezone

os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN"] = "1"
from transformers import AutoTokenizer
from protocol import messages_for

ROOT = Path(__file__).resolve().parent
MODEL_ROOT = Path("/tmp/latent-currentmoe-20261030")


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def objsha(obj):
    return hashlib.sha256(json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def put(name, value):
    (ROOT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def main():
    summary = json.loads((ROOT / "full/summary.json").read_text())
    assert summary["completed"] == 357
    registered = json.loads((ROOT / "preregistration.json").read_text())
    for filename, expected in registered["frozen_files"].items():
        assert sha(ROOT / filename) == expected
    runtime = json.loads((ROOT / "full/runtime-manifest.json").read_text())
    assert runtime["all_model_files_hash_verified"]
    assert runtime["preregistration_sha256"] == sha(ROOT / "preregistration.json")
    for filename, expected in runtime["runtime_source_hashes"].items():
        assert sha(Path(filename)) == expected
    cohort = json.loads((ROOT / "cohort.json").read_text())
    prompts = json.loads((ROOT / "prompts.json").read_text())
    schemas = json.loads((ROOT / "schemas.json").read_text())
    assert len(cohort) == len(prompts) == 357
    for db_id, schema in schemas.items():
        path = Path(schema["database_path"])
        assert sha(path) == schema["database_sha256"]
        conn = sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)
        conn.execute("PRAGMA query_only=ON")
        rows = conn.execute("SELECT name, sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND sql IS NOT NULL ORDER BY name COLLATE BINARY").fetchall()
        conn.close()
        ddl = "\n\n".join(sql.rstrip(";\n ") + ";" for _, sql in rows)
        assert ddl == schema["ddl"]
    tokenizer = AutoTokenizer.from_pretrained(str(MODEL_ROOT / "model"), local_files_only=True)
    entries, text_mismatches = [], []
    for index, (case, prompt) in enumerate(zip(cohort, prompts, strict=True)):
        task_id = case["question_id"]
        path = ROOT / "full" / (task_id + ".json")
        assert sha(path) == summary["case_files"][task_id]
        actual = json.loads(path.read_text())
        assert actual["index"] == index
        assert actual["question_id"] == prompt["question_id"] == task_id
        assert actual["db_id"] == prompt["db_id"] == case["db_id"]
        assert actual["prompt_text"] == prompt["prompt_text"]
        assert actual["input_token_ids"] == prompt["input_token_ids"]
        messages = messages_for(case, schemas[case["db_id"]]["ddl"])
        assert messages == prompt["messages"]
        rendered = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True, enable_thinking=False, preserve_thinking=False)
        assert rendered == prompt["prompt_text"]
        assert tokenizer.encode(rendered, add_special_tokens=False) == actual["input_token_ids"]
        generated = actual["output_token_ids"]
        assert len(generated) == actual["output_tokens"]
        assert len(generated) <= 1024
        if actual["status"] == "generated":
            assert actual["finish_reason"] in {"stop", "length"}
            if actual["finish_reason"] == "stop":
                assert generated[-1] in runtime["eos_token_ids"]
                text_ids = generated[:-1]
            else:
                assert len(generated) == 1024
                text_ids = generated
            decoded = tokenizer.decode(text_ids, skip_special_tokens=False, clean_up_tokenization_spaces=False)
            if decoded != actual["raw_output"]:
                text_mismatches.append({"question_id": task_id, "decoded_sha256": hashlib.sha256(decoded.encode()).hexdigest(), "raw_sha256": hashlib.sha256(actual["raw_output"].encode()).hexdigest()})
        else:
            assert actual["status"] == "error"
        assert not actual["network_attempts"]
        entries.append({"question_id": task_id, "db_id": case["db_id"], "sql": actual["raw_output"] if actual["status"] == "generated" else None, "status": actual["status"], "error_type": actual.get("error_type"), "error": actual.get("error"), "partial_raw_output_on_error": actual["raw_output"] if actual["status"] == "error" else None, "finish_reason": actual.get("finish_reason"), "input_tokens": actual["input_tokens"], "output_tokens": actual["output_tokens"], "elapsed_seconds": actual["elapsed_seconds"], "prompt_text_sha256": actual["prompt_text_sha256"], "actual_input_token_ids_sha256": objsha(actual["input_token_ids"]), "actual_output_token_ids_sha256": objsha(generated), "raw_output_sha256": hashlib.sha256(actual["raw_output"].encode()).hexdigest(), "database_sha256": schemas[case["db_id"]]["database_sha256"], "model_repository": runtime["model_repository"], "model_revision": runtime["model_revision"], "preregistration_sha256": sha(ROOT / "preregistration.json"), "runtime_manifest_sha256": sha(ROOT / "full/runtime-manifest.json"), "raw_record": "full/" + task_id + ".json", "raw_record_sha256": sha(path), "sql_extraction": "Identity: generated raw_output unchanged; explicit inference error -> null. No trimming, fence stripping, normalization, execution, or repair."})
    assert not text_mismatches, text_mismatches
    assert len({x["question_id"] for x in entries}) == 357
    (ROOT / "candidates.jsonl").write_text("".join(json.dumps(x, ensure_ascii=False, sort_keys=True) + "\n" for x in entries))
    smoke_checks = []
    for task_id in [x["question_id"] for x in cohort[:2]]:
        smoke = json.loads((ROOT / "smoke" / (task_id + ".json")).read_text())
        full = json.loads((ROOT / "full" / (task_id + ".json")).read_text())
        smoke_checks.append({"question_id": task_id, "identical_input_tokens": smoke["input_token_ids"] == full["input_token_ids"], "identical_output_tokens": smoke["output_token_ids"] == full["output_token_ids"], "identical_raw_output": smoke["raw_output"] == full["raw_output"]})
    put("final-validation.json", {"verified_utc": datetime.now(timezone.utc).isoformat(), "cases": len(entries), "full_cohort_all_cases_included": True, "frozen_code_and_inputs_unchanged": True, "runtime_sources_unchanged": True, "database_bytes_and_ddl_revalidated": True, "all_rendered_prompts_reconstructed_identically": True, "all_actual_input_tokens_match_frozen_tokens": True, "all_output_token_counts_match": True, "all_output_tokens_decode_to_raw_text": True, "terminal_eos_excluded_from_raw_text_but_retained_in_output_ids": True, "network_attempts": [], "candidate_extraction": entries[0]["sql_extraction"], "smoke_full_comparison": smoke_checks, "summary": {k: v for k, v in summary.items() if k != "case_files"}, "candidates_sha256": sha(ROOT / "candidates.jsonl"), "exporter_sha256": sha(Path(__file__)), "preregistration_sha256": sha(ROOT / "preregistration.json")})
    files = [p for p in ROOT.rglob("*") if p.is_file() and "__pycache__" not in p.parts and p.name != "artifact-freeze.json"]
    put("artifact-freeze.json", {"created_utc": datetime.now(timezone.utc).isoformat(), "files": {str(p.relative_to(ROOT)): {"sha256": sha(p), "bytes": p.stat().st_size} for p in sorted(files)}})
    print(json.dumps({"cases": len(entries), "all_checks_passed": True, "candidates_sha256": sha(ROOT / "candidates.jsonl"), "validation_sha256": sha(ROOT / "final-validation.json"), "artifact_freeze_sha256": sha(ROOT / "artifact-freeze.json"), "summary": {k: v for k, v in summary.items() if k != "case_files"}}))


if __name__ == "__main__":
    main()
