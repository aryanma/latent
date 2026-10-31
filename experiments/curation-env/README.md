# Curation-0

A small stateful environment for training and evaluating agents that prepare training data. It turns a declared data contract into tool interactions and executable terminal feedback.

The agent must join candidate records to source evidence, repair incorrect labels, remove disallowed or evaluation-overlapping lineages, choose one representative per eligible lineage, and preserve coverage. Source authority and revision cutoffs are part of the task. All fixtures are synthetic.

## Run the environment

Python 3.9+; the core environment has no third-party dependencies and makes no network calls.

```sh
python3 -m unittest -v test_environment.py
python3 verify_release.py
python3 run_controls.py
python3 cli.py --family composition --seed 7
```

The CLI prints a reset observation, then accepts one JSON action per line:

```json
{"tool":"inspect","args":{}}
```

Use `lookup` with the IDs returned by the environment. `repair`, `exclude`, and `restore` mutate the candidate dataset; `submit` terminates and grades it. `{"op":"reset"}` starts again and `{"op":"export"}` returns a replayable trajectory. The export contains the result and final dataset; do not feed it into the agent's decision context.

`verify_release.py` checks the unpacked artifact hashes and replays every recorded control/model trajectory through the Python environment. It requires no model or GPU. `analyze_results.py` recomputes the aggregate and split metrics from the complete archived episode files.

```python
from latent_curation.environment import CurationEnv, generate_task, run_reference

env = CurationEnv(generate_task(seed=7, family="composition"))
observation = env.reset()
response = env.step({"tool": "inspect", "args": {}})
print(response)

# A deterministic, schema-aware policy using the public sources:
trace = run_reference(CurationEnv(generate_task(7, "composition")))
assert trace["result"]["success"]
```

`generate_task` returns public observations and a private answer key. An agent must receive only `reset()` and `step()` responses. This is an in-process research environment, not a sandbox against hostile Python code. The browser playground includes synthetic answer keys to grade locally and is not a secure evaluation server.

## What is graded

Terminal reward is:

```
coverage × label_accuracy × permission_and_split_gate × uniqueness_gate × evidence_gate
```

- Coverage uses the original number of eligible lineages, so deleting everything earns zero.
- Label accuracy is measured over retained records; an empty output has accuracy zero.
- The permission/split gate fails if any retained lineage is forbidden or belongs to evaluation.
- The uniqueness gate fails if a retained lineage occurs more than once.
- The evidence gate requires every changed, retained label to cite the correct source event, previously inspected through the tools.

The grader accepts either valid representative of a duplicate lineage. It checks the output and relevant evidence, not similarity to an expert action sequence. Provenance is checked for final retained-label changes, not every historical edit; exclusion-reason strings are not semantically graded. `check` exposes structural counts, not the private answer or intermediate correctness. Invalid actions consume steps. Exhausting 18 steps without submission earns zero. Submission freezes the environment.

## Frozen evaluation

`tasks/manifest.json` pins the source file and every task. Task hashes use UTF-8 JSON with sorted keys and compact separators; `source_sha256` hashes the exact Python file bytes. The canonical manifest digest is:

```
6893521e0391e831b45a414390246e0fb0a06d1c203892b66082a91f8ae22730
```

The 48 evaluation episodes comprise 36 worlds:

- 24 single/pair corruption worlds, seeds 1000–1023.
- 12 composed worlds, seeds 2000–2011.
- Those same 12 composed worlds under an alternate source-authority contract. Records and source tables are identical; correct labels change.

Paired episodes are correlated. Development includes one composed example, so this is a test of greater task complexity and policy change, not a claim that every mechanism combination was unseen during development. The development and evaluation files are public for reproducibility; none of the evaluation answers enters model training or the decision context in our experiment.

Task IDs expose the episode family, including `policy_shift`. The paired diagnostic rejects a policy that keeps the same authority across both episodes; it does not prove that a successful model used the authority field rather than the task-name cue. Candidate records and source tables are identical within each pair, but the task identifier and contract differ.

`make_suite.py` regenerates the fixtures deterministically. Do not regenerate or edit them between model comparisons. `run_controls.py` executes all six diagnostic policies through the environment and writes full trajectories to `control-results.json`. The schema-aware reference is perfect on this suite: a deterministic program is sufficient for this fixed schema. Weak heuristic controls are diagnostics, not competitive baselines.

## Scope

This is a training and evaluation substrate for a bounded data workflow. A passing output meets the synthetic contract. It does not establish that the dataset improves a downstream model, that the system generalizes to real enterprise data, or that RL is necessary to solve this schema. The accompanying model experiment is supervised fine-tuning on expert actions, not reinforcement learning. The environment's terminal rewards are available for future RL experiments.

Read the [experiment](https://aryanma.github.io/latent/curation-environment.html), try the [interactive environment](https://aryanma.github.io/latent/curation.html), or inspect the model protocol and reproduction instructions in `model/README.md`.
