"""Consume frozen prompts only; write every generation, never score or repair."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parent
MODEL_ROOT = Path("/tmp/latent-currentmoe-20261030")
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN"] = "1"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
NETWORK_ATTEMPTS = []


class NetworkBlocked(BaseException):
    pass


def audit(event, args):
    if event in {"socket.connect", "socket.getaddrinfo", "socket.sendto"}:
        NETWORK_ATTEMPTS.append(event)
        raise NetworkBlocked("Networking forbidden during inference")


sys.addaudithook(audit)
import mlx.core as mx
from mlx_lm import load, stream_generate
from mlx_lm.sample_utils import make_sampler
from protocol import MAX_OUTPUT_TOKENS, MAX_CONTEXT_TOKENS, SEED, TEMPERATURE


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write(path, obj):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n")
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["smoke", "full"])
    args = parser.parse_args()
    frozen = json.loads((ROOT / "preregistration.json").read_text())
    for filename, expected in frozen["frozen_files"].items():
        assert sha(ROOT / filename) == expected, "Frozen file changed: " + filename
    manifest = json.loads((ROOT / "input-manifest.json").read_text())
    for filename, expected in manifest["files"].items():
        assert sha(ROOT / filename) == expected
    model_manifest = json.loads((MODEL_ROOT / "model-manifest.json").read_text())
    for filename, item in model_manifest["files"].items():
        assert sha(MODEL_ROOT / "model" / filename) == item["sha256"], "Model file changed: " + filename
    prompts = json.loads((ROOT / "prompts.json").read_text())
    assert len(prompts) == 357
    if args.mode == "smoke":
        prompts = prompts[:2]
    output = ROOT / args.mode
    output.mkdir(exist_ok=False)
    environment = {"started_utc": datetime.now(timezone.utc).isoformat(), "mode": args.mode, "python": sys.version, "executable": sys.executable, "platform": platform.platform(), "machine": platform.machine(), "packages": {d.metadata["Name"]: d.version for d in importlib.metadata.distributions()}, "preregistration_sha256": sha(ROOT / "preregistration.json"), "model_manifest_sha256": sha(MODEL_ROOT / "model-manifest.json"), "model_repository": model_manifest["repository"], "model_revision": model_manifest["revision"], "all_model_files_hash_verified": True, "runtime_source_hashes": {}, "expected_cases": len(prompts)}
    package_root = Path(__import__("mlx_lm").__file__).parent
    for rel in ["generate.py", "utils.py", "tokenizer_utils.py", "sample_utils.py", "models/qwen3_5_moe.py", "models/qwen3_5.py"]:
        p = package_root / rel
        if p.exists():
            environment["runtime_source_hashes"][str(p)] = sha(p)
    write(output / "runtime-manifest.json", environment)
    started = time.perf_counter()
    model, tokenizer = load(str(MODEL_ROOT / "model"))
    mx.eval(model.parameters())
    environment["load_seconds"] = time.perf_counter() - started
    environment["model_class"] = type(model).__module__ + "." + type(model).__name__
    assert type(model).__module__ == "mlx_lm.models.qwen3_5_moe"
    environment["eos_token_ids"] = sorted(tokenizer.eos_token_ids)
    write(output / "runtime-manifest.json", environment)
    print(json.dumps({"event": "loaded", "seconds": environment["load_seconds"], "cases": len(prompts), "model_class": environment["model_class"]}), flush=True)
    all_results = []
    for index, prompt in enumerate(prompts):
        ids = prompt["input_token_ids"]
        assert tokenizer.encode(prompt["prompt_text"], add_special_tokens=False) == ids
        result = {"index": index, "question_id": prompt["question_id"], "db_id": prompt["db_id"], "prompt_text": prompt["prompt_text"], "prompt_text_sha256": prompt["prompt_text_sha256"], "input_token_ids": ids, "input_tokens": len(ids), "max_output_tokens": MAX_OUTPUT_TOKENS, "max_context_tokens": MAX_CONTEXT_TOKENS, "seed": SEED, "temperature": TEMPERATURE, "enable_thinking": False, "started_utc": datetime.now(timezone.utc).isoformat(), "raw_output": "", "output_token_ids": [], "status": "pending"}
        start = time.perf_counter()
        try:
            if len(ids) + MAX_OUTPUT_TOKENS > MAX_CONTEXT_TOKENS:
                raise ValueError("Context budget exceeded; no truncation or generation")
            mx.random.seed(SEED)
            pieces, generated = [], []
            final = None
            for response in stream_generate(model, tokenizer, prompt=ids, max_tokens=MAX_OUTPUT_TOKENS, sampler=make_sampler(temp=TEMPERATURE)):
                pieces.append(response.text)
                generated.append(int(response.token))
                final = response
                result["raw_output"] = "".join(pieces)
                result["output_token_ids"] = generated.copy()
            mx.synchronize()
            assert final is not None
            assert len(generated) == final.generation_tokens
            assert len(ids) == final.prompt_tokens
            assert len(generated) <= MAX_OUTPUT_TOKENS
            result.update({"status": "generated", "finish_reason": final.finish_reason, "output_tokens": len(generated), "prompt_tokens_reported": final.prompt_tokens, "generation_tokens_reported": final.generation_tokens, "prompt_tokens_per_second": final.prompt_tps, "generation_tokens_per_second": final.generation_tps, "terminal_token_is_eos": generated[-1] in tokenizer.eos_token_ids, "peak_mlx_memory_bytes": mx.get_peak_memory()})
        except Exception as exc:
            result.update({"status": "error", "error_type": type(exc).__name__, "error": str(exc), "traceback": traceback.format_exc(), "output_tokens": len(result["output_token_ids"])})
        result["elapsed_seconds"] = time.perf_counter() - start
        result["network_attempts"] = list(NETWORK_ATTEMPTS)
        result["finished_utc"] = datetime.now(timezone.utc).isoformat()
        write(output / (prompt["question_id"] + ".json"), result)
        all_results.append({k: v for k, v in result.items() if k not in {"input_token_ids", "output_token_ids", "prompt_text", "raw_output", "traceback"}})
        write(output / "progress.json", {"completed": len(all_results), "total": len(prompts), "results": all_results})
        print(json.dumps({"event": "case", "index": index, "question_id": prompt["question_id"], "status": result["status"], "input_tokens": len(ids), "output_tokens": result["output_tokens"], "finish_reason": result.get("finish_reason"), "seconds": result["elapsed_seconds"]}), flush=True)
        mx.clear_cache()
    write(output / "summary.json", {"mode": args.mode, "completed": len(all_results), "generated": sum(x["status"] == "generated" for x in all_results), "errors": sum(x["status"] == "error" for x in all_results), "length_limited": sum(x.get("finish_reason") == "length" for x in all_results), "total_input_tokens": sum(x["input_tokens"] for x in all_results), "total_output_tokens": sum(x["output_tokens"] for x in all_results), "total_generation_seconds": sum(x["elapsed_seconds"] for x in all_results), "total_wall_seconds_including_load": time.perf_counter() - started, "network_attempts": NETWORK_ATTEMPTS, "finished_utc": datetime.now(timezone.utc).isoformat(), "case_files": {x["question_id"]: sha(output / (x["question_id"] + ".json")) for x in all_results}})


if __name__ == "__main__":
    main()
