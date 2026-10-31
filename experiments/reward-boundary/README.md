# τ-bench reward-contract audit

This is a local research experiment by Latent, using unmodified upstream evaluator and environment code. It constructs counterfactual trajectories and re-grades them. It does not run a language model or user simulator, and its results are not model success rates.

## Reproduce

Requires `git`, `uv`, and Python 3.12. Tested with CPython 3.12.11 on macOS ARM64. Use this directory as the working directory.

```sh
git init upstream
git -C upstream remote add origin https://github.com/sierra-research/tau2-bench.git
git -C upstream sparse-checkout init --cone
git -C upstream sparse-checkout set src data/tau2/domains/airline data/tau2/domains/mock
git -C upstream fetch --depth 1 --filter=blob:none origin da0835f6c67baef58bdda18f2a3b037dfb3a1754
git -C upstream checkout --detach FETCH_HEAD
uv venv --python 3.12 .venv312
uv pip install --python .venv312/bin/python -r requirements.lock.txt
uv pip install --python .venv312/bin/python --no-deps -e ./upstream
.venv312/bin/python run_audit.py --out run1
.venv312/bin/python run_audit.py --out run2
.venv312/bin/python verify_repeats.py
.venv312/bin/python test_tripwires.py
```

Dependency installation requires network access. The experiment itself blocks outbound socket operations before upstream imports. During scoring it also blocks child processes and replaces model-call entry points with tripwires that raise before any call. These are protective hooks in the research harness; no upstream files or evaluator outcomes are changed. The evaluator's default semantic communication scorer is retained.

## Population and probes

The pinned airline base split contains 50 tasks. The 44 with empty `communicate_info` require no model calls for their active `DB,COMMUNICATE` reward basis. Tasks 3, 7, 11, 14, 18, and 23 are excluded because their nonempty communication requirements invoke a semantic model judge. The entire selected population is used; it is not a sample selected by outcome.

Every eligible task receives five probes:

- `no_tool`: no actions, neutral statement that no actions were performed.
- `no_tool_irrelevant`: no actions, an unrelated final statement.
- `reference_neutral`: all reference actions, with actual upstream tool responses, followed by a neutral final statement.
- `reference_irrelevant`: exactly the same reference actions followed by the unrelated statement.
- `reference_max_steps`: reference actions, but termination changed to `MAX_STEPS` to verify the top-level termination gate.

Tasks with mutating reference actions also receive `omit_first_mutating_action`, which removes that action and executes the remaining sequence afresh. Tasks 1 and 26 additionally receive explicit refusal versus approval/refund-offer text pairs tied to their written assertions. These text-only claims do not actually cancel a reservation or issue a refund.

Two intentional-invariance controls are also included: task 1 receives a paraphrased refusal, and task 19 receives the reference cancellation followed by a harmless reservation-details read. These distinguish legitimate variation from a simplistic exact-trajectory requirement. There are 247 probes per run.

Normal-termination probes explicitly set `AGENT_STOP`. They establish evaluator behavior conditional on that termination; they do not show that a live agent or user simulator would naturally produce or terminate on these transcripts. No semantic correctness judgment is inferred from the unrelated-response probes.

## Controls and state isolation

Each probe constructs a fresh upstream environment, checks its initial database and user-database hashes, executes its specified actions, then calls the unchanged upstream `evaluate_simulation` with `EvaluationType.ALL`. The evaluator independently constructs gold and predicted environments. Strict replay is retained. A second fresh environment after every probe verifies that the fixture remains unchanged. All source/data hashes are checked before and after each complete run.

Before scoring, the script verifies the git commit, a clean tracked worktree, and that imported `tau2` code comes from the pinned checkout. Synthetic record timestamps are fixed explicitly; these are fixture values, not claims about actual execution time. Progress logs retain actual process timing where emitted by upstream initialization.

The target hash shown in convenience rows is independently obtained from the full reference-action execution, not read by modifying the evaluator. The complete upstream `RewardInfo` and constructed `SimulationRun` are preserved in the evidence file. Tool execution errors and scoring exceptions are reported separately.

`EvaluationType.ALL` is deliberate: it preserves the task's active reward basis while avoiding the nongating natural-language diagnostic judge. The CLI's `ALL_WITH_NL_ASSERTIONS` default would invoke that model. This experiment does not claim that such optional diagnostics are absent or incapable of noticing text differences.

## Outputs

- `summary.json`: exact population, probe totals, tripwire counts, exclusions, package versions, and limitations.
- `results.json`: task-level convenience rows with text, actions, reward components, database hashes, controls, and errors.
- `trajectory-evidence.json`: exact constructed simulation records and complete upstream reward records.
- `source-manifest.json`: SHA-256 hashes of relevant upstream files.
- `eligible-tasks.json`: validated task subset.

Compare SHA-256 hashes of the five output files across the independent runs. Logs are progress records, not stable research outputs.

`verify_repeats.py` checks both complete 247-probe runs, verifies byte-identical outputs and no tool/scoring errors, and writes `reproducibility.json`. `test_tripwires.py` separately tests that network resolution and four model-call entry points are blocked before execution; its deliberately blocked self-test attempts are distinct from the zero-attempt scoring runs.

## Interpretation

Outcome-based reward is an intentional upstream design. A no-action pass can be correct for a refusal task. Identical rewards for materially different speech establish a limit of the active reward contract, not a model failure rate or a claim that every passing trajectory is incorrect. Natural-language assertions exist as optional diagnostics; none gate the pinned airline tasks' final reward. Other domains use different reward bases.

## License and attribution

Upstream code and task data: Sierra Research, MIT License, Copyright (c) 2025 Sierra Research. Preserve `UPSTREAM-LICENSE` with redistributed substantial portions. Upstream source: https://github.com/sierra-research/tau2-bench/tree/da0835f6c67baef58bdda18f2a3b037dfb3a1754

The standalone audit script is supplied under MIT terms in `AUDIT-LICENSE`.
