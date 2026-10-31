#!/usr/bin/env python3
"""Deterministic counterfactual re-grading of pinned, unmodified tau2.

No model is run. These are constructed evaluator probes, not agent rollouts.
Only tasks whose default communication judge has no facts to score are eligible.
"""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import sys
import time
import subprocess

ROOT = Path(__file__).resolve().parent
UPSTREAM = ROOT / "upstream"
PIN = "da0835f6c67baef58bdda18f2a3b037dfb3a1754"
FIXED_TIME = "2026-10-30T00:00:00"
NEUTRAL = "The tool execution sequence has finished."
IRRELEVANT = "Blue ceramic teapots are an interesting subject for a history essay."
NO_TOOL = "No tool actions were performed."

os.environ["PYTHON_DOTENV_DISABLED"] = "1"
os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
os.environ["TAU2_DATA_DIR"] = str(UPSTREAM / "data")

external_attempts = []
model_attempts = []
phase = "imports"


class ExternalCallBlocked(BaseException):
    pass


def audit_hook(event, args):
    if event in {"socket.connect", "socket.getaddrinfo", "socket.sendto"}:
        external_attempts.append({"phase": phase, "event": event})
        raise ExternalCallBlocked("Network access prohibited during this experiment")
    if phase == "scoring" and event == "subprocess.Popen":
        external_attempts.append({"phase": phase, "event": event})
        raise ExternalCallBlocked("Child processes prohibited during scoring")


sys.addaudithook(audit_hook)

def git_output(*arguments):
    return subprocess.run(["git", "-C", str(UPSTREAM), *arguments],
                          check=True, capture_output=True, text=True).stdout.strip()

assert git_output("rev-parse", "HEAD") == PIN, "Wrong upstream revision"
assert git_output("status", "--porcelain", "--untracked-files=no") == "", "Tracked upstream files modified"

import tau2 as upstream_tau2
from tau2.data_model.message import AssistantMessage, ToolCall
from tau2.data_model.tasks import Action
from tau2.data_model.semantic_communication import CommunicateScoring
from tau2.data_model.simulation import SimulationRun, TerminationReason
from tau2.domains.airline.environment import get_environment, get_tasks
from tau2.evaluator.evaluator import EvaluationType, evaluate_simulation
import tau2.evaluator.evaluator_communicate as communicate_module
import tau2.evaluator.evaluator_nl_assertions as nl_module
import tau2.utils.llm_utils as llm_module
import litellm
from loguru import logger

assert Path(upstream_tau2.__file__).resolve() == (UPSTREAM / "src/tau2/__init__.py").resolve(), "Wrong tau2 import origin"
assert Path(communicate_module.__file__).resolve() == (UPSTREAM / "src/tau2/evaluator/evaluator_communicate.py").resolve()

logger.remove()


def model_tripwire(*args, **kwargs):
    model_attempts.append({"phase": phase})
    raise ExternalCallBlocked("Model calls prohibited during this experiment")


# Guard both the utility and imported-by-value references used by evaluators.
llm_module.generate = model_tripwire
communicate_module.generate = model_tripwire
nl_module.generate = model_tripwire
litellm.completion = model_tripwire
litellm.acompletion = model_tripwire


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


SOURCE_PATHS = [
    "LICENSE", "pyproject.toml",
    "data/tau2/domains/airline/tasks.json",
    "data/tau2/domains/airline/db.json",
    "data/tau2/domains/airline/split_tasks.json",
    "src/tau2/evaluator/evaluator.py",
    "src/tau2/evaluator/evaluator_env.py",
    "src/tau2/evaluator/evaluator_action.py",
    "src/tau2/evaluator/evaluator_communicate.py",
    "src/tau2/data_model/tasks.py",
    "src/tau2/data_model/semantic_communication.py",
    "src/tau2/environment/environment.py",
    "src/tau2/environment/toolkit.py",
    "src/tau2/domains/airline/tools.py",
    "src/tau2/domains/airline/environment.py",
]


def stable_dump(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


def main():
    global phase
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    manifest = {p: sha(UPSTREAM / p) for p in SOURCE_PATHS}
    assert manifest["data/tau2/domains/airline/tasks.json"] == "ccd8ba737b4cc371415af70151187788f728d6108d0916e73bb4317b40542052"
    tasks = sorted(get_tasks("base"), key=lambda task: int(task.id))
    assert len(tasks) == 50
    eligible = [t for t in tasks if not t.evaluation_criteria.communicate_info]
    assert len(eligible) == 44
    assert all(t.initial_state is None for t in tasks)
    assert all([b.value for b in t.evaluation_criteria.reward_basis] == ["DB", "COMMUNICATE"] for t in tasks)
    assert not external_attempts and not model_attempts
    phase = "scoring"
    fixture = get_environment()
    initial_hash = fixture.get_db_hash()
    initial_user_hash = fixture.get_user_db_hash()
    assert initial_hash == "124e39a664b56402bcd09cb8a6a9cece6acb8462337c969799d5658e3250f263"
    del fixture
    scoring = CommunicateScoring()
    results = []
    evidence = []
    failures = []

    def run_probe(task, probe, actions, final_text, termination=TerminationReason.AGENT_STOP):
        env = get_environment()
        assert env.get_db_hash() == initial_hash
        assert env.get_user_db_hash() == initial_user_hash
        trajectory = []
        tool_errors = []
        for index, action in enumerate(actions):
            tc = ToolCall(id=f"audit-{task.id}-{index}", name=action.name,
                          arguments=action.arguments, requestor=action.requestor)
            assert action.requestor == "assistant", "Unexpected user-side action"
            message = AssistantMessage.text("", tool_calls=[tc])
            message.timestamp = FIXED_TIME
            trajectory.append(message)
            response = env.get_response(tc)
            response.timestamp = FIXED_TIME
            trajectory.append(response)
            if response.error:
                tool_errors.append({"action_id": action.action_id, "tool": action.name,
                                    "output": response.content})
        final_message = AssistantMessage.text(final_text)
        final_message.timestamp = FIXED_TIME
        trajectory.append(final_message)
        final_hash = env.get_db_hash()
        final_user_hash = env.get_user_db_hash()
        sim = SimulationRun(id=f"audit-{task.id}-{probe}", task_id=task.id,
            timestamp=FIXED_TIME, start_time=FIXED_TIME, end_time=FIXED_TIME, duration=0,
            termination_reason=termination, messages=trajectory)
        reward = evaluate_simulation(sim, task, EvaluationType.ALL, False, "airline",
                                     communicate_scoring=scoring)
        # Fresh construction after scoring verifies that the next trial starts clean.
        fresh = get_environment()
        reset_ok = fresh.get_db_hash() == initial_hash and fresh.get_user_db_hash() == initial_user_hash
        assert reset_ok
        del fresh
        result = {
            "probe": probe, "reward": reward.reward,
            "final_text": final_text,
            "action_names": [a.name for a in actions],
            "reward_breakdown": reward.model_dump(mode="json")["reward_breakdown"],
            "db_check": reward.model_dump(mode="json")["db_check"],
            "termination": termination.value,
            "initial_db_hash": initial_hash, "final_db_hash": final_hash,
            "initial_user_db_hash": initial_user_hash, "final_user_db_hash": final_user_hash,
            "fresh_environment_reset_verified": reset_ok,
            "tool_count": len(actions), "tool_errors": tool_errors,
        }
        evidence.append({"task_id": task.id, "probe": probe,
                         "simulation": sim.model_dump(mode="json"),
                         "reward_info": reward.model_dump(mode="json")})
        return result

    for task in eligible:
        criteria = task.evaluation_criteria
        actions = criteria.actions or []
        env = get_environment()
        writes = [i for i, a in enumerate(actions) if env.tools.tool_mutates_state(a.name)]
        del env
        task_result = {
            "task_id": task.id,
            "description": task.description.model_dump(mode="json") if task.description else None,
            "reward_basis": [b.value for b in criteria.reward_basis],
            "nl_assertions": criteria.nl_assertions,
            "nl_assertions_gate_reward": False,
            "communicate_info": criteria.communicate_info,
            "reference_actions": [a.model_dump(mode="json") for a in actions],
            "reference_mutating_action_count": len(writes),
            "probes": {},
        }
        specifications = [
            ("no_tool", [], NO_TOOL, TerminationReason.AGENT_STOP),
            ("no_tool_irrelevant", [], IRRELEVANT, TerminationReason.AGENT_STOP),
            ("reference_neutral", actions, NEUTRAL, TerminationReason.AGENT_STOP),
            ("reference_irrelevant", actions, IRRELEVANT, TerminationReason.AGENT_STOP),
            ("reference_max_steps", actions, NEUTRAL, TerminationReason.MAX_STEPS),
        ]
        if writes:
            omitted = actions[writes[0]]
            task_result["omitted_action"] = omitted.model_dump(mode="json")
            specifications.append(("omit_first_mutating_action", [a for i, a in enumerate(actions) if i != writes[0]], NEUTRAL, TerminationReason.AGENT_STOP))
        if task.id == "1":
            task_result["hand_reviewed_pair"] = {
                "source_assertion": "Agent should not approve the cancellation.",
                "scope": "Text-only approval vs refusal, with identical reference read calls; neither changes the reservation.",
            }
            specifications.extend([
                ("explicit_refusal", actions, "I cannot approve this cancellation.", TerminationReason.AGENT_STOP),
                ("paraphrased_refusal", actions, "This cancellation is not permitted, so I must decline your request.", TerminationReason.AGENT_STOP),
                ("contradictory_approval", actions, "I approve this cancellation.", TerminationReason.AGENT_STOP),
            ])
        if task.id == "19":
            extra_read = Action(action_id="latent-extra-read-control", name="get_reservation_details",
                                arguments={"reservation_id": "Z7GOZK"})
            specifications.append(("reference_plus_harmless_read", [*actions, extra_read], NEUTRAL, TerminationReason.AGENT_STOP))
        if task.id == "26":
            task_result["hand_reviewed_pair"] = {
                "source_assertion": "Agent does not offer the refund because reservation doesn't meet policy criteria.",
                "scope": "Text-only refund offer vs refusal; no tool calls and no refund is actually issued.",
            }
            specifications.extend([
                ("explicit_refusal", actions, "I cannot offer you a refund because this reservation does not meet the policy criteria.", TerminationReason.AGENT_STOP),
                ("contradictory_refund_offer", actions, "I offer you a refund for this reservation.", TerminationReason.AGENT_STOP),
            ])
        for name, action_list, text, termination in specifications:
            try:
                task_result["probes"][name] = run_probe(task, name, action_list, text, termination)
            except Exception as exc:
                failure = {"task_id": task.id, "probe": name, "type": type(exc).__name__, "message": str(exc)}
                failures.append(failure)
                task_result["probes"][name] = {"error": failure}
        reference = task_result["probes"].get("reference_neutral", {})
        if "final_db_hash" in reference:
            for probe in task_result["probes"].values():
                probe["target_db_hash"] = reference["final_db_hash"]
                probe["target_user_db_hash"] = reference["final_user_db_hash"]
                probe["target_hash_source"] = "Fresh environment executing all reference actions, independently of predicted replay."
        results.append(task_result)
        print(json.dumps({"task": task.id, "completed": len(results), "eligible": len(eligible),
                          "rewards": {k: v.get("reward") for k, v in task_result["probes"].items()}}), flush=True)

    assert not external_attempts and not model_attempts
    assert manifest == {p: sha(UPSTREAM / p) for p in SOURCE_PATHS}, "Upstream artifact changed"
    def probe_values(name):
        return [(r["task_id"], r["probes"][name]) for r in results if name in r["probes"]]
    counts = {}
    for name in ["no_tool", "no_tool_irrelevant", "reference_neutral", "reference_irrelevant", "reference_max_steps", "omit_first_mutating_action", "explicit_refusal", "paraphrased_refusal", "reference_plus_harmless_read", "contradictory_approval", "contradictory_refund_offer"]:
        values = probe_values(name)
        counts[name] = {"attempted": len(values), "reward_1": sum(v.get("reward") == 1 for _, v in values),
                        "reward_0": sum(v.get("reward") == 0 for _, v in values),
                        "errors": sum("error" in v for _, v in values),
                        "reward_1_task_ids": [i for i, v in values if v.get("reward") == 1]}
    summary = {
        "schema_version": "latent-tau-observability-v1",
        "upstream_repository": "https://github.com/sierra-research/tau2-bench",
        "upstream_commit": PIN, "license": "MIT; Copyright (c) 2025 Sierra Research",
        "domain": "airline", "split": "base", "tasks_total": len(tasks),
        "eligible_tasks": len(eligible), "excluded_task_ids": [t.id for t in tasks if t not in eligible],
        "total_scored_probes": sum(len(t["probes"]) for t in results),
        "exclusion_reason": "Nonempty communicate_info requires default semantic model judging; no model calls allowed.",
        "task_assertions_total": sum(len(t.evaluation_criteria.nl_assertions or []) for t in tasks),
        "nl_assertions_gate_reward": 0, "probe_counts": counts,
        "initial_db_hash": initial_hash, "initial_user_db_hash": initial_user_hash,
        "evaluation_type": "ALL", "communication_scoring": scoring.model_dump(mode="json"),
        "semantic_judge_calls": len(model_attempts), "network_attempts": len(external_attempts),
        "fresh_state_reset_verified_every_probe": all(p.get("fresh_environment_reset_verified", False) for r in results for p in r["probes"].values()),
        "upstream_files_unchanged": True, "failures": failures,
        "provenance_checks": {"head_matches_pin": True, "tracked_worktree_clean_before_run": True,
                              "tau2_imported_from_pinned_checkout": True},
        "interpretation": "Constructed evaluator probes, not agent rollouts or model success rates. Text-only reward invariance measures channels not observed by the active reward contract; no semantic incorrectness labels are inferred.",
        "probe_texts": {"no_tool": NO_TOOL, "neutral": NEUTRAL, "irrelevant": IRRELEVANT},
        "python_version": sys.version.split()[0],
        "dependency_versions": dict(sorted((d.metadata["Name"], d.version) for d in importlib.metadata.distributions())),
    }
    stable_dump(args.out / "summary.json", summary)
    stable_dump(args.out / "results.json", results)
    stable_dump(args.out / "trajectory-evidence.json", evidence)
    stable_dump(args.out / "source-manifest.json", manifest)
    stable_dump(args.out / "eligible-tasks.json", [t.model_dump(mode="json") for t in eligible])
    print(json.dumps({"finished": True, "output": str(args.out), "counts": counts, "failures": failures}), flush=True)


if __name__ == "__main__":
    main()
