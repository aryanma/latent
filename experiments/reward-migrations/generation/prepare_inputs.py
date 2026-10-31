"""Select a public-input-identical cohort and freeze prompts without inference."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
from collections.abc import Mapping
from datetime import datetime, timezone

os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN"] = "1"
from transformers import AutoTokenizer
from protocol import messages_for, MAX_OUTPUT_TOKENS, MAX_CONTEXT_TOKENS

ROOT = Path(__file__).resolve().parent
SOURCE = Path("/tmp/latent-reward-migration-20261031")
MODEL_ROOT = Path("/tmp/latent-currentmoe-20261030")


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()


def put(name, value):
    (ROOT / name).write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def main():
    assert not (ROOT / "input-manifest.json").exists(), "Inputs already frozen"
    old_path = SOURCE / "bird-mini-dev-previous/mini_dev_sqlite.json"
    new_path = SOURCE / "arcwise-plat-hf/arcwise_plat_sql_only_with_diff.json"
    assert sha(old_path) == "88ceb0710163cae46a256ecea8f0a8c98286599530b60587fda5c3cfe57d45d2"
    assert sha(new_path) == "010c91bf9c06730769877df700c2ce79c88f242041f46f3089de49a3ed402a2c"
    old = json.loads(old_path.read_text())
    new = json.loads(new_path.read_text())
    old_map = {str(x["question_id"]): x for x in old}
    new_map = {str(x["question_id"]): x for x in new}
    assert len(old_map) == len(old) == 500
    assert len(new_map) == len(new) == 498
    cases = []
    for task_id in sorted(old_map.keys() & new_map.keys(), key=int):
        a, b = old_map[task_id], new_map[task_id]
        if all(a[k] == b[k] for k in ("db_id", "question", "evidence")):
            assert isinstance(a["question"], str) and isinstance(a["evidence"], str)
            cases.append({"question_id": task_id, **{k: a[k] for k in ("db_id", "question", "evidence")}})
    assert len(cases) == 357, len(cases)
    assert all(set(c) == {"question_id", "db_id", "question", "evidence"} for c in cases)
    db_manifest = json.loads((SOURCE / "bird-db-manifest.json").read_text())
    schemas = {}
    for item in db_manifest["databases"]:
        db = SOURCE / item["path"]
        assert sha(db) == item["sha256"], str(db)
        conn = sqlite3.connect(db.as_uri() + "?mode=ro&immutable=1", uri=True)
        conn.execute("PRAGMA query_only=ON")
        rows = conn.execute("SELECT name, sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND sql IS NOT NULL ORDER BY name COLLATE BINARY").fetchall()
        conn.close()
        assert rows
        ddl = "\n\n".join(sql.rstrip(";\n ") + ";" for _, sql in rows)
        schemas[db.stem] = {"ddl": ddl, "table_names": [name for name, _ in rows], "database_path": str(db), "database_sha256": item["sha256"], "ddl_sha256": hashlib.sha256(ddl.encode()).hexdigest()}
    assert set(c["db_id"] for c in cases) <= schemas.keys()
    tokenizer = AutoTokenizer.from_pretrained(str(MODEL_ROOT / "model"), local_files_only=True)
    prompts = []
    for case in cases:
        messages = messages_for(case, schemas[case["db_id"]]["ddl"])
        rendered = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True, enable_thinking=False, preserve_thinking=False)
        ids = tokenizer.encode(rendered, add_special_tokens=False)
        native_ids = tokenizer.apply_chat_template(messages, tokenize=True, add_generation_prompt=True, enable_thinking=False, preserve_thinking=False)
        if isinstance(native_ids, Mapping):
            native_ids = native_ids["input_ids"]
        assert ids == native_ids
        assert case["question"] in rendered and case["evidence"] in rendered
        prompts.append({"question_id": case["question_id"], "db_id": case["db_id"], "messages": messages, "prompt_text": rendered, "prompt_text_sha256": hashlib.sha256(rendered.encode()).hexdigest(), "input_token_ids": ids, "input_tokens": len(ids), "context_budget_exceeded": len(ids) + MAX_OUTPUT_TOKENS > MAX_CONTEXT_TOKENS})
    put("cohort.json", cases)
    put("schemas.json", schemas)
    put("prompts.json", prompts)
    put("input-manifest.json", {"created_utc": datetime.now(timezone.utc).isoformat(), "old_dataset": {"repository": "birdsql/bird_mini_dev", "revision": "f65faf4ae3b638c1fa6df1d3370c8d92c8366301", "path": str(old_path), "sha256": sha(old_path), "license": "CC-BY-SA-4.0"}, "new_dataset": {"repository": "uiuc-kang-lab/arcwise-plat", "revision": "8e6eb6e18487a9dabaf761bb9e62b1234e340301", "configuration": "sql_only", "path": str(new_path), "sha256": sha(new_path), "license": "CC-BY-SA-4.0"}, "cohort_rule": "Same stringified legacy question_id, db_id, and byte-identical question and evidence strings; null is not empty string. Ascending numeric legacy ID. No reference SQL used in selection.", "cases": len(cases), "files": {name: sha(ROOT / name) for name in ["cohort.json", "schemas.json", "prompts.json", "protocol.py", "prepare_inputs.py"]}, "max_input_tokens": max(x["input_tokens"] for x in prompts), "min_input_tokens": min(x["input_tokens"] for x in prompts), "total_input_tokens": sum(x["input_tokens"] for x in prompts), "context_budget_exceeded_cases": [x["question_id"] for x in prompts if x["context_budget_exceeded"]], "native_template_tokenization_verified_for_every_prompt": True, "template_sha256": sha(MODEL_ROOT / "model/chat_template.jinja"), "tokenizer_sha256": sha(MODEL_ROOT / "model/tokenizer.json"), "sqlite_version": sqlite3.sqlite_version, "python": sys.version})
    print(json.dumps({"cases": len(cases), "max_input_tokens": max(x["input_tokens"] for x in prompts), "total_input_tokens": sum(x["input_tokens"] for x in prompts), "over_context": sum(x["context_budget_exceeded"] for x in prompts)}))


if __name__ == "__main__":
    main()
