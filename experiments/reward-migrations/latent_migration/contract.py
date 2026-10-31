"""Conservative compatibility decisions, separate from reward computation.

Hashes identify bytes, not semantic equivalence. A caller must fingerprint all
model-visible inputs and all relevant world/interface dependencies. Unknown
provenance never certifies reuse. A regrade decision is NOT permission to use an
old sample as on-policy data for a different policy.
"""

from dataclasses import dataclass, asdict
from hashlib import sha256
import json
import re


def digest(value):
    payload = json.dumps(value, sort_keys=True, ensure_ascii=False,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    return sha256(payload).hexdigest()


@dataclass(frozen=True)
class Contract:
    task: str
    observation: str
    world: str
    interface: str
    grader: str
    terminal_private_reward: bool
    lineage_verified: bool = False
    policy: str = ""
    world_visible_to_policy: bool = True

    def __post_init__(self):
        if not isinstance(self.task, str) or not self.task:
            raise ValueError("task must be a nonempty, namespaced identity")
        for field in ("terminal_private_reward", "lineage_verified", "world_visible_to_policy"):
            if type(getattr(self, field)) is not bool:
                raise ValueError(field + " must be a boolean")
        for field in ("observation", "world", "interface", "grader", "policy"):
            if not isinstance(getattr(self, field), str):
                raise ValueError(field + " must be a SHA-256 string, or empty if unknown")

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict):
            raise ValueError("contract must be an object")
        required = set(cls.__dataclass_fields__)
        if set(value) != required:
            raise ValueError("contract fields must be exactly: " + ", ".join(sorted(required)))
        return cls(**value)

    def to_dict(self):
        return asdict(self)


def plan(old, new):
    """Plan what is necessary to measure the same policy under a new contract.

    fixed_action_diagnostic describes a separate, conditional experiment. It
    never upgrades an incompatible old response into a new-policy rollout.
    """
    fields = ("observation", "world", "interface", "grader", "policy")
    unknown = [field for field in fields if not all(
        re.fullmatch(r"[0-9a-f]{64}", getattr(c, field)) for c in (old, new))]
    if old.task != new.task or not old.lineage_verified or not new.lineage_verified:
        return {"action": "review", "reason": "Task lineage is not established.",
                "changed": [], "fixed_action_diagnostic": None}
    if unknown:
        return {"action": "review", "reason": "Missing or invalid fingerprints: " + ", ".join(unknown),
                "changed": [], "fixed_action_diagnostic": None}
    changed = [field for field in fields if getattr(old, field) != getattr(new, field)]
    feedback_changed = old.terminal_private_reward != new.terminal_private_reward
    if feedback_changed:
        changed.append("reward_visibility")
    if old.world_visible_to_policy != new.world_visible_to_policy:
        changed.append("world_visibility")
    if any(field in changed for field in ("observation", "interface", "policy", "reward_visibility", "world_visibility")):
        return {"action": "rerun", "reason": "The process that produced the action may have changed.",
                "changed": changed,
                "fixed_action_diagnostic": "reexecute" if "interface" not in changed else None}
    if "world" in changed:
        if old.world_visible_to_policy or new.world_visible_to_policy:
            return {"action": "rerun", "reason": "World state can affect the observations or transitions that produced the action.",
                    "changed": changed, "fixed_action_diagnostic": "reexecute"}
        # For a single-action setting with no world reads, the same observed
        # context and policy produce the same action distribution. SQL must be
        # executed again; a previous result cannot be reused on changed rows.
        if "grader" in changed and not (old.terminal_private_reward and new.terminal_private_reward):
            return {"action": "rerun", "reason": "Changed reward may have influenced the rollout.",
                    "changed": changed, "fixed_action_diagnostic": "reexecute"}
        return {"action": "reexecute", "reason": "The world changed, but it was not observed before this fixed action.",
                "changed": changed, "fixed_action_diagnostic": "reexecute"}
    if "grader" in changed:
        if not (old.terminal_private_reward and new.terminal_private_reward):
            return {"action": "rerun", "reason": "Reward may have affected a later observation or stopping decision.",
                    "changed": changed, "fixed_action_diagnostic": "regrade"}
        return {"action": "regrade", "reason": "Only a terminal, agent-hidden grading dependency changed.",
                "changed": changed, "fixed_action_diagnostic": "regrade"}
    return {"action": "reuse", "reason": "All declared dependencies are identical.",
            "changed": [], "fixed_action_diagnostic": "reuse"}


def invalidated(graph, changed):
    """Return the transitive dependent artifacts, rejecting ambiguous DAGs.

    graph maps artifact IDs to dependency IDs. Leaves must also occur as keys.
    A group's advantage vector is one artifact depending on every group reward.
    """
    if len(set(changed) - graph.keys()):
        raise ValueError("unknown changed artifact")
    visiting, visited = set(), set()

    def visit(node):
        if node in visiting:
            raise ValueError("artifact graph contains a cycle")
        if node in visited:
            return
        if node not in graph:
            raise ValueError("unknown dependency: " + node)
        visiting.add(node)
        for dep in graph[node]:
            visit(dep)
        visiting.remove(node)
        visited.add(node)

    for node in graph:
        visit(node)
    dirty = set(changed)
    while True:
        added = {node for node, deps in graph.items() if any(dep in dirty for dep in deps)} - dirty
        if not added:
            return sorted(dirty)
        dirty.update(added)
