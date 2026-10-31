"""Development-only model/environment interaction. No evaluation or training here."""
import argparse
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import time

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
from local_runtime import LocalQwen, MODEL_REPOSITORY, MODEL_REVISION, network_attempts

PROMPTS = {
    "v1": """You are an agent operating a data-curation environment. Your goal is to prepare the training dataset according to the supplied contract. You can only act using the listed tools.
Return exactly ONE JSON object per turn with keys "tool" and "args", for example {"tool":"inspect","args":{"offset":0,"limit":20}}. Do not use markdown, explanations, reasoning, or an array of calls. After each action you will receive the exact tool response.
Read the contract and tool definitions carefully. Obtain necessary evidence with inspect and lookup, preserve every eligible lineage, and cite inspected source events for label edits. Never invent IDs or infer correct labels from candidate text. Use batch lookups/edits where appropriate. Call submit when the output is ready. You have at most 18 tool calls and 4096 generated tokens for the entire episode. Invalid actions consume a step. The grader is only revealed after termination.""",
    "v2": """You control the listed tools of a data-curation environment. Follow its contract and finish by calling submit. You have 18 tool calls and 4096 generated tokens total.
CRITICAL OUTPUT FORMAT: Produce exactly one JSON action and STOP immediately after its closing brace. Do not produce a second action, markdown, reasoning, or a simulated observation. The environment, not you, supplies the next observation. Schema example only: {"tool":"lookup","args":{"table":"registry","keys":["TICKET_ID_FROM_OBSERVATION"]}}. The example ID is a placeholder; never send it literally. Invalid JSON is rejected, costs one step, and is not repaired.
Useful procedure using only visible information:
1. inspect all candidate rows. Read each row's exact ticket_id and id.
2. lookup registry using ticket_id keys. Registry records supply case_id, lineage_id, and training_allowed.
3. lookup evaluation using lineage_id keys. lookup events using case_id keys. These are different key types; copy their exact values from observations. Batch keys when possible.
4. Exclude disallowed rows, evaluation-overlap lineages, and extra copies of the same lineage. Preserve exactly one representative of every eligible lineage; different lineages may share text.
5. For each kept row, select the latest APPROVED event from the contract's authority at or before its cutoff. Ignore other authorities, drafts, and later events. Normalize its category through the supplied aliases. Repair only labels needing changes, citing that inspected event's id, never a registry or lineage id. Use only canonical labels.
6. When all contract conditions are satisfied, submit. check only reports structural information, not the private correct answer.
Return only the NEXT single action object now, then stop and wait for the real result.""",
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--variant", choices=sorted(PROMPTS), default="v1")
    parser.add_argument("--task-ids", nargs="+", default=["clean-0", "labels-1", "versions-5", "composition-7"])
    parser.add_argument("--expected-manifest", required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(Path(__file__), args.out / "driver-used.py")
    shutil.copyfile(ROOT / "local_runtime.py", args.out / "runtime-used.py")
    snapshot = args.out / "environment-snapshot"
    snapshot.mkdir()
    source_paths = ["latent_curation/environment.py", "latent_curation/__init__.py", "tasks/development.json", "tasks/manifest.json"]
    manifest = json.loads((args.env_root / "tasks/manifest.json").read_text())
    manifest_digest = hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    assert manifest_digest == args.expected_manifest, "Unexpected environment manifest"
    before = {name: sha(args.env_root / name) for name in source_paths}
    for name in source_paths:
        dest = snapshot / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(args.env_root / name, dest)
    assert before == {name: sha(args.env_root / name) for name in source_paths}, "Source changed during snapshot"
    assert sha(snapshot / "latent_curation/environment.py") == manifest["source_sha256"], "Source differs from suite manifest byte SHA"
    spec = importlib.util.spec_from_file_location("frozen_curation_environment", snapshot / "latent_curation/environment.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    tasks = json.loads((snapshot / "tasks/development.json").read_text())
    by_id = {t["public"]["id"]: t for t in tasks}
    assert set(args.task_ids) <= set(by_id), "Only development tasks allowed"
    runtime = LocalQwen()
    summaries = []
    dump(args.out / "run-manifest.json", {"model_repository": MODEL_REPOSITORY,
        "model_revision": MODEL_REVISION, "environment_manifest_digest": manifest_digest,
        "source_files": before, "task_ids": args.task_ids, "variant": args.variant,
        "system_prompt": PROMPTS[args.variant], "per_turn_generation_limit": 512,
        "episode_generation_limit": 4096, "max_steps": 18, "seed": 42,
        "temperature": 0.0, "source_split": "development", "no_output_repair": True,
        "no_context_truncation": True, "runtime_sha256": sha(ROOT / "local_runtime.py"),
        "driver_sha256": sha(Path(__file__)), "load_seconds": runtime.load_seconds})
    for task_id in args.task_ids:
        env = module.CurationEnv(by_id[task_id], max_steps=18)
        reset = env.reset()
        assert module.digest(env.task["public"]) == by_id[task_id]["fingerprint"]
        messages = [{"role": "system", "content": PROMPTS[args.variant]},
                    {"role": "user", "content": json.dumps(reset, ensure_ascii=False, separators=(',', ':'))}]
        used = 0
        turns = []
        driver_termination = None
        begin = time.perf_counter()
        while not env.done:
            remaining = 4096 - used
            if remaining <= 0:
                driver_termination = "generation_budget_exhausted"
                break
            try:
                prediction = runtime.complete(messages, max_tokens=min(512, remaining),
                                              seed=42, temperature=0.0)
            except Exception as exc:
                driver_termination = "inference_error"
                turns.append({"inference_error": {"type": type(exc).__name__, "message": str(exc)}})
                break
            used += prediction["generation_tokens"]
            assert used <= 4096
            # A malformed response becomes an invalid action, not a repaired tool call.
            action = prediction["parsed"] if prediction["parse_error"] is None else None
            response = env.step(action)
            turns.append({"turn": env.steps, "prediction": prediction,
                          "action_passed_to_environment": action,
                          "environment_response": deepcopy(response),
                          "cumulative_generation_tokens": used})
            messages.append({"role": "assistant", "content": prediction["raw"]})
            messages.append({"role": "user", "content": json.dumps(response, ensure_ascii=False, separators=(',', ':'))})
            print(json.dumps({"task_id": task_id, "step": env.steps,
                  "tool": action.get("tool") if isinstance(action, dict) else None,
                  "error": response["observation"].get("error") if isinstance(response["observation"], dict) else None,
                  "generation_tokens": used, "done": env.done}), flush=True)
        elapsed = time.perf_counter() - begin
        assert not network_attempts
        outcome = env.result if env.result is not None else {"reward": 0.0, "success": False, "termination": driver_termination}
        summary = {"task_id": task_id, "success": outcome.get("success", False),
                   "reward": outcome.get("reward", 0.0), "termination": outcome.get("termination"),
                   "steps": env.steps, "generation_tokens": used,
                   "prompt_tokens_total": sum(t.get("prediction", {}).get("prompt_tokens", 0) for t in turns),
                   "max_prompt_tokens": max((t.get("prediction", {}).get("prompt_tokens", 0) for t in turns), default=0),
                   "invalid_json_count": sum(t.get("prediction", {}).get("parse_error") is not None for t in turns),
                   "invalid_action_count": sum(t["error"] is not None for t in env.history),
                   "elapsed_seconds": elapsed, "outcome": outcome,
                   "driver_termination": driver_termination}
        dump(args.out / f"episode-{task_id}.json", {"summary": summary, "reset": reset,
             "messages": messages, "turns": turns, "environment_trajectory": env.export_trajectory()})
        summaries.append(summary)
        dump(args.out / "summary.json", {"variant": args.variant, "split": "development",
             "episodes": summaries, "successes": sum(s["success"] for s in summaries),
             "episodes_completed": len(summaries), "remote_inference_calls": 0,
             "network_attempts": network_attempts})
        print(json.dumps({"episode_complete": summary}), flush=True)
    assert before == {name: sha(snapshot / name) for name in source_paths}, "Frozen snapshot changed"


if __name__ == "__main__":
    main()
