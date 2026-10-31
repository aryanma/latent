#!/usr/bin/env python3
"""Optionally regenerate all 357 SQL candidates using pinned local model files.

This script is offline. --prepare-only does not import MLX or load weights.
Every invocation requires a NEW output directory and writes its own provenance.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import sqlite3
import sys
import time
import traceback
from collections.abc import Mapping

HERE = Path(__file__).resolve().parent
MODEL_REPOSITORY = "mlx-community/Qwen3.6-35B-A3B-4bit"
MODEL_REVISION = "38740b847e4cb78f352aba30aa41c76e08e6eb46"
NETWORK_ATTEMPTS = []
for key in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_HUB_DISABLE_IMPLICIT_TOKEN", "HF_HUB_DISABLE_TELEMETRY"):
    os.environ[key] = "1"


class NetworkBlocked(BaseException):
    pass


def audit(event, args):
    if event in {"socket.connect", "socket.getaddrinfo", "socket.sendto"}:
        NETWORK_ATTEMPTS.append(event)
        raise NetworkBlocked("Network access is forbidden; download inputs explicitly before running")


sys.addaudithook(audit)
from protocol import messages_for, MAX_OUTPUT_TOKENS, MAX_CONTEXT_TOKENS, SEED, TEMPERATURE


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def objsha(value):
    return hashlib.sha256(json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def write(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def validate_file(path, expected):
    require(path.is_file(), "Missing pinned file: " + str(path))
    if "bytes" in expected:
        require(path.stat().st_size == expected["bytes"], "Size mismatch: " + str(path))
    require(sha(path) == expected["sha256"], "Hash mismatch: " + str(path))


def check_versions(prepare_only):
    versions = {}
    for line in (HERE / "requirements.lock.txt").read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        name, expected = line.split("==")
        if prepare_only and name not in {"transformers", "tokenizers", "jinja2"}:
            continue
        actual = importlib.metadata.version(name)
        require(actual == expected, f"Expected {name}=={expected}; installed {actual}")
        versions[name] = actual
    return versions


def prepare(sources, model_dir, output, prepare_only):
    """Read only public task fields and sqlite_master; no SQL candidates/rewards."""
    from transformers import AutoTokenizer
    pins = read(HERE / "source-pins.json")
    model_pin = read(HERE / "model-manifest.json")
    require(model_pin["repository"] == MODEL_REPOSITORY and model_pin["revision"] == MODEL_REVISION, "Unexpected model pin")
    # Preparation needs tokenizer/config files only, so it works on a CPU machine.
    tokenizer_files = {"chat_template.jinja", "tokenizer.json", "tokenizer_config.json", "config.json", "vocab.json"}
    checked_model_files = {}
    for filename, expected in model_pin["files"].items():
        if not prepare_only or filename in tokenizer_files:
            validate_file(model_dir / filename, expected)
            checked_model_files[filename] = expected["sha256"]
    for side in ("old", "new"):
        validate_file(sources / pins[side]["path"], pins[side])
    old = read(sources / pins["old"]["path"])
    new = read(sources / pins["new"]["path"])
    old_map = {str(x["question_id"]): x for x in old}
    new_map = {str(x["question_id"]): x for x in new}
    require(len(old_map) == len(old) == 500, "Unexpected old source or duplicate IDs")
    require(len(new_map) == len(new) == 498, "Unexpected new source or duplicate IDs")
    cases = []
    for task_id in sorted(old_map.keys() & new_map.keys(), key=int):
        a, b = old_map[task_id], new_map[task_id]
        if all(a[k] == b[k] for k in ("db_id", "question", "evidence")):
            require(isinstance(a["question"], str) and isinstance(a["evidence"], str), "Non-string admitted public input")
            cases.append({"question_id": task_id, **{k: a[k] for k in ("db_id", "question", "evidence")}})
    require(len(cases) == pins["expected_count"] == 357, "Cohort mismatch")
    schemas = {}
    for item in pins["databases"]:
        path = sources / item["path"]
        validate_file(path, item)
        conn = sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)
        conn.execute("PRAGMA query_only=ON")
        rows = conn.execute("SELECT name, sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND sql IS NOT NULL ORDER BY name COLLATE BINARY").fetchall()
        conn.close()
        require(bool(rows), "Empty schema: " + str(path))
        ddl = "\n\n".join(sql.rstrip(";\n ") + ";" for _, sql in rows)
        ddl_hash = hashlib.sha256(ddl.encode()).hexdigest()
        require(ddl_hash == pins["expected_ddl_sha256"][path.stem], "DDL rendering changed")
        schemas[path.stem] = {"ddl": ddl, "table_names": [name for name, _ in rows], "database_source_path": item["path"], "database_sha256": item["sha256"], "ddl_sha256": ddl_hash}
    tokenizer = AutoTokenizer.from_pretrained(str(model_dir), local_files_only=True)
    prompts = []
    for case in cases:
        messages = messages_for(case, schemas[case["db_id"]]["ddl"])
        rendered = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True, enable_thinking=False, preserve_thinking=False)
        ids = tokenizer.encode(rendered, add_special_tokens=False)
        native = tokenizer.apply_chat_template(messages, tokenize=True, add_generation_prompt=True, enable_thinking=False, preserve_thinking=False)
        if isinstance(native, Mapping):
            native = native["input_ids"]
        require(ids == native, "Native-template tokenization differs")
        require(case["question"] in rendered and case["evidence"] in rendered, "Public input was lost")
        prompts.append({"question_id": case["question_id"], "db_id": case["db_id"], "messages": messages, "prompt_text": rendered, "prompt_text_sha256": hashlib.sha256(rendered.encode()).hexdigest(), "input_token_ids": ids, "input_tokens": len(ids), "context_budget_exceeded": len(ids) + MAX_OUTPUT_TOKENS > MAX_CONTEXT_TOKENS})
    output.mkdir(parents=True, exist_ok=False)
    write(output / "cohort.json", cases)
    write(output / "schemas.json", schemas)
    write(output / "prompts.json", prompts)
    require(sha(output / "cohort.json") == pins["expected_cohort_file_sha256"], "Cohort bytes differ from original experiment")
    require(sha(output / "prompts.json") == pins["expected_prompt_file_sha256"], "Prompt bytes/tokens differ from original experiment")
    preparation = {"created_utc": datetime.now(timezone.utc).isoformat(), "sources_directory": str(sources), "model_directory": str(model_dir), "prepare_only": prepare_only, "source_pins_sha256": sha(HERE / "source-pins.json"), "model_manifest_sha256": sha(HERE / "model-manifest.json"), "checked_model_files": checked_model_files, "cases": len(cases), "total_input_tokens": sum(x["input_tokens"] for x in prompts), "max_input_tokens": max(x["input_tokens"] for x in prompts), "context_exclusions": [x["question_id"] for x in prompts if x["context_budget_exceeded"]], "exact_original_prompt_file_reproduced": True, "exact_original_cohort_file_reproduced": True, "sqlite_version": sqlite3.sqlite_version}
    write(output / "preparation.json", preparation)
    return cases, schemas, prompts


def generate(model_dir, output, prompts, schemas, registration):
    """Use the native text-only loader directly; no old experiment imports."""
    import mlx.core as mx
    import mlx_lm
    from mlx_lm import load, stream_generate
    from mlx_lm.sample_utils import make_sampler
    full = output / "full"
    full.mkdir(exist_ok=False)
    runtime = {"started_utc": datetime.now(timezone.utc).isoformat(), "model_repository": MODEL_REPOSITORY, "model_revision": MODEL_REVISION, "python": sys.version, "platform": platform.platform(), "machine": platform.machine(), "packages": {d.metadata["Name"]: d.version for d in importlib.metadata.distributions()}, "registration_sha256": sha(output / "registration.json"), "runtime_source_hashes": {}}
    package_root = Path(mlx_lm.__file__).parent
    runtime_pins = read(HERE / "runtime-source-pins.json")
    for relative in ("generate.py", "utils.py", "tokenizer_utils.py", "sample_utils.py", "models/qwen3_5_moe.py", "models/qwen3_5.py"):
        path = package_root / relative
        require(path.is_file(), "Missing pinned runtime source: " + relative)
        require(sha(path) == runtime_pins[relative], "Pinned runtime source changed: " + relative)
        runtime["runtime_source_hashes"][relative] = sha(path)
    started = time.perf_counter()
    model, tokenizer = load(str(model_dir))
    mx.eval(model.parameters())
    runtime["load_seconds"] = time.perf_counter() - started
    runtime["model_class"] = type(model).__module__ + "." + type(model).__name__
    require(type(model).__module__ == "mlx_lm.models.qwen3_5_moe", "Unexpected native model implementation")
    runtime["eos_token_ids"] = sorted(tokenizer.eos_token_ids)
    write(full / "runtime-manifest.json", runtime)
    results = []
    exported = []
    for index, prompt in enumerate(prompts):
        ids = prompt["input_token_ids"]
        require(tokenizer.encode(prompt["prompt_text"], add_special_tokens=False) == ids, "Loaded runtime tokenization differs")
        record = {"index": index, "question_id": prompt["question_id"], "db_id": prompt["db_id"], "prompt_text": prompt["prompt_text"], "prompt_text_sha256": prompt["prompt_text_sha256"], "input_token_ids": ids, "input_tokens": len(ids), "max_output_tokens": MAX_OUTPUT_TOKENS, "max_context_tokens": MAX_CONTEXT_TOKENS, "seed": SEED, "temperature": TEMPERATURE, "enable_thinking": False, "started_utc": datetime.now(timezone.utc).isoformat(), "raw_output": "", "output_token_ids": [], "status": "pending"}
        before = time.perf_counter()
        try:
            require(len(ids) + MAX_OUTPUT_TOKENS <= MAX_CONTEXT_TOKENS, "Context budget exceeded; no truncation or generation")
            mx.random.seed(SEED)
            pieces, tokens, final = [], [], None
            for response in stream_generate(model, tokenizer, prompt=ids, max_tokens=MAX_OUTPUT_TOKENS, sampler=make_sampler(temp=TEMPERATURE)):
                pieces.append(response.text)
                tokens.append(int(response.token))
                final = response
                record["raw_output"] = "".join(pieces)
                record["output_token_ids"] = tokens.copy()
            mx.synchronize()
            require(final is not None, "No model result")
            require(len(tokens) == final.generation_tokens and len(ids) == final.prompt_tokens, "Runtime token counts differ")
            require(len(tokens) <= MAX_OUTPUT_TOKENS, "Output exceeded fixed budget")
            record.update({"status": "generated", "finish_reason": final.finish_reason, "output_tokens": len(tokens), "generation_tokens_reported": final.generation_tokens, "prompt_tokens_reported": final.prompt_tokens, "prompt_tokens_per_second": final.prompt_tps, "generation_tokens_per_second": final.generation_tps, "terminal_token_is_eos": tokens[-1] in tokenizer.eos_token_ids, "peak_mlx_memory_bytes": mx.get_peak_memory()})
        except Exception as error:
            record.update({"status": "error", "error_type": type(error).__name__, "error": str(error), "traceback": traceback.format_exc(), "output_tokens": len(record["output_token_ids"])})
        record["elapsed_seconds"] = time.perf_counter() - before
        record["finished_utc"] = datetime.now(timezone.utc).isoformat()
        record["network_attempts"] = list(NETWORK_ATTEMPTS)
        path = full / (prompt["question_id"] + ".json")
        write(path, record)
        # Identity extraction. Malformed SQL is retained; no execution or repair.
        exported.append({"question_id": record["question_id"], "db_id": record["db_id"], "sql": record["raw_output"] if record["status"] == "generated" else None, "status": record["status"], "error_type": record.get("error_type"), "error": record.get("error"), "partial_raw_output_on_error": record["raw_output"] if record["status"] == "error" else None, "finish_reason": record.get("finish_reason"), "input_tokens": len(ids), "output_tokens": record["output_tokens"], "elapsed_seconds": record["elapsed_seconds"], "prompt_text_sha256": record["prompt_text_sha256"], "actual_input_token_ids_sha256": objsha(ids), "actual_output_token_ids_sha256": objsha(record["output_token_ids"]), "raw_output_sha256": hashlib.sha256(record["raw_output"].encode()).hexdigest(), "database_sha256": schemas[record["db_id"]]["database_sha256"], "model_repository": MODEL_REPOSITORY, "model_revision": MODEL_REVISION, "registration_sha256": sha(output / "registration.json"), "runtime_manifest_sha256": sha(full / "runtime-manifest.json"), "raw_record": "full/" + path.name, "raw_record_sha256": sha(path), "sql_extraction": "Identity: generated raw_output unchanged; explicit inference error -> null."})
        results.append({k: record.get(k) for k in ("question_id", "status", "finish_reason", "input_tokens", "output_tokens", "elapsed_seconds")})
        write(output / "progress.json", {"completed": len(results), "total": len(prompts), "results": results})
        print(json.dumps({"completed": len(results), "total": len(prompts), **results[-1]}), flush=True)
        mx.clear_cache()
    # Independent full-output decoding, performed only after all candidates exist.
    decode_mismatches = []
    for item in exported:
        record = read(output / item["raw_record"])
        if record["status"] == "generated":
            tokens = record["output_token_ids"]
            text_ids = tokens[:-1] if record["terminal_token_is_eos"] else tokens
            decoded = tokenizer.decode(text_ids, skip_special_tokens=False, clean_up_tokenization_spaces=False)
            if decoded != record["raw_output"]:
                decode_mismatches.append(record["question_id"])
    (output / "candidates.jsonl").write_text("".join(json.dumps(x, ensure_ascii=False, sort_keys=True) + "\n" for x in exported), encoding="utf-8")
    summary = {"completed": len(results), "generated": sum(x["status"] == "generated" for x in results), "errors": sum(x["status"] == "error" for x in results), "length_limited": sum(x["finish_reason"] == "length" for x in results), "total_input_tokens": sum(x["input_tokens"] for x in results), "total_output_tokens": sum(x["output_tokens"] for x in results), "total_generation_seconds": sum(x["elapsed_seconds"] for x in results), "total_wall_seconds_including_load": time.perf_counter() - started, "output_token_decode_mismatches": decode_mismatches, "candidates_sha256": sha(output / "candidates.jsonl"), "network_attempts": NETWORK_ATTEMPTS, "finished_utc": datetime.now(timezone.utc).isoformat()}
    write(output / "summary.json", summary)
    require(not decode_mismatches, "Raw-token decode validation failed; retain this run as failed, do not publish it as validated")
    print(json.dumps(summary), flush=True)


def freeze(output):
    files = [p for p in output.rglob("*") if p.is_file() and p.name != "artifact-freeze.json"]
    write(output / "artifact-freeze.json", {"created_utc": datetime.now(timezone.utc).isoformat(), "files": {str(p.relative_to(output)): {"sha256": sha(p), "bytes": p.stat().st_size} for p in sorted(files)}})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", required=True, type=Path, help="Directory produced by the study's core-source fetcher")
    parser.add_argument("--model-dir", required=True, type=Path, help="Local pinned model snapshot; no download is attempted")
    parser.add_argument("--out", required=True, type=Path, help="New output directory; existing directories are never overwritten")
    parser.add_argument("--prepare-only", action="store_true", help="CPU-only source/tokenizer validation and exact prompt preparation; no MLX import or model loading")
    args = parser.parse_args()
    sources, model_dir, output = (p.expanduser().resolve() for p in (args.sources, args.model_dir, args.out))
    require(not output.exists(), "Output directory already exists; use a new directory")
    versions = check_versions(args.prepare_only)
    cases, schemas, prompts = prepare(sources, model_dir, output, args.prepare_only)
    registration = {"created_utc": datetime.now(timezone.utc).isoformat(), "purpose": "Optional independent regeneration of a fixed 357-case candidate set; no scoring or training", "prepare_only": args.prepare_only, "cases": len(cases), "order": "ascending numeric legacy question_id", "model_repository": MODEL_REPOSITORY, "model_revision": MODEL_REVISION, "max_output_tokens": MAX_OUTPUT_TOKENS, "max_context_tokens": MAX_CONTEXT_TOKENS, "seed": SEED, "temperature": TEMPERATURE, "enable_thinking": False, "retries": 0, "repair": False, "tools": False, "row_samples": False, "reference_SQL_in_prompt": False, "sql_extraction": "Identity; no whitespace/fence removal. Explicit inference errors -> null.", "truncation": "None; over-context cases recorded as errors", "package_versions_checked": versions, "code_files": {name: sha(HERE / name) for name in ("rerun.py", "protocol.py", "requirements.lock.txt", "model-manifest.json", "source-pins.json", "runtime-source-pins.json")}, "prepared_files": {name: sha(output / name) for name in ("cohort.json", "schemas.json", "prompts.json", "preparation.json")}, "limitations": ["No guarantee of bit-identical model output across hardware, operating systems, or numerical backends.", "This creates a new run; it is not admitted by the original experiment's hard-coded artifact digest.", "No SQL accuracy, new-policy performance, or training gain is measured by this command."]}
    write(output / "registration.json", registration)
    if args.prepare_only:
        freeze(output)
        print(json.dumps({"prepared": len(cases), "inference_run": False, "exact_original_prompts": True, "output": str(output)}))
        return
    generate(model_dir, output, prompts, schemas, registration)
    for name, expected in registration["code_files"].items():
        require(sha(HERE / name) == expected, "Code changed during generation: " + name)
    for name, expected in registration["prepared_files"].items():
        require(sha(output / name) == expected, "Prepared input changed during generation: " + name)
    freeze(output)


if __name__ == "__main__":
    main()
