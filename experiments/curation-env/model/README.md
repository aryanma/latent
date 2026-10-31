# Local Qwen curation comparison — 2026-10-30

This directory contains actual local executions, not simulated model outputs.
The production environment was read and snapshotted. It was never modified here.

## Fixed model and software

- Official model: https://huggingface.co/Qwen/Qwen3-1.7B-MLX-4bit
- Revision: `21457c6f51ed54a7c16e988c0844db973815c137`; model license Apache-2.0.
- Weight SHA256: `42e688d626b3e144bf721af7517a82f3ea7e97bb5764fef1c89942bf9165072a`.
- Python3.12.11, MLX-LM0.32.2, MLX0.32.4; every resolved package is pinned in requirements.lock.txt.
- Execution machine: Apple M5 Max, arm64 macOS, 68,719,476,736 bytes physical memory.
- No cloud inference, credential use, or paid API. Runtime blocks Python socket connect/DNS/sendto before importing model libraries. Weights are downloaded publicly once; actual model execution is offline.

## Frozen harness

`frozen-comparison-plan.json` predates held-out evaluation. The existing v2 prompt was chosen on four development tasks: both prompts had0/4 exact successes; v2 earned mean partial reward0.25 versus0.0. Final development artifacts are curation-dev-final-v1 and curation-dev-final-v2. Earlier untyped interface runs are retained as superseded diagnostics.

Each episode receives the full public reset, contract, typed tool schemas, and all exact preceding tool responses. One strict JSON action is requested per turn; malformed output is rejected, never repaired. Limits:18 environment steps,512 generated tokens per turn,4096 cumulative generated tokens,32768 context tokens with explicit rejection instead of truncation. Greedy decoding, seed42. No private answer key enters a model prompt.

The pinned MLX tokenizer contains a legacy template that strips earlier text before a closing think tag. `local_runtime.py` therefore renders plain ChatML preserving every history byte, and explicitly prefills the empty nonthinking tags as in Qwen's official current template. This is the same rendering in baseline inference, SFT examples, and adapter inference.

## Training

Supervised behavior cloning with QLoRA, **not reinforcement learning**. The environment can support RL, but no policy-gradient or reward-optimization algorithm was run.

96 fresh worlds, seeds10000–10095, evenly distributed across labels, duplicates, permissions, leakage, versions and pair, yielded592 expert-action prefixes. Separate12 worlds, seeds20000–20011, yielded74 validation prefixes. Experts use the visible-data solver and execute actual tools. Every action is replayed from a reset and checked against the reference response. Inputs contain only the exact observations before that action; terminal grading is never in any next-action input.

Only next-action JSON and EOS tokens receive loss; prompt and padding tokens are masked. All full prefixes fit4096 tokens (train maximum4015; validation4036), with explicit no-truncation checks. Fixed120 updates, batch1, Adam1e-4, rank8, scale20, dropout0, LoRA on all linear projections in the last8 blocks, gradient checkpointing. 2,490,368 adapter parameters.120 sampled action minibatches do not constitute120 complete training episodes or one pass over all592 examples.

A fixed independently sampled decision prefix per validation world gives12 monitoring examples. The unchanged upstream trainer validates before completed updates0,19,39,59,79,99,119; we add a final measurement after120. No validation or evaluation result selects a checkpoint. Only the final120 checkpoint is evaluated interactively.

Training took87.464 seconds including validation and recorded4.705GB peak MLX allocation. It trained7,775 supervised target tokens. Fixed-monitor loss fell0.3933→0.0710. These are teacher-forced action losses, not interactive task-success rates. The fixed monitor contains6 lookup,2 inspect,2 submit and2 exclude prefixes, and no repair target; it is a narrow monitor rather than comprehensive policy evaluation.

## Reproduce

Use a fresh copy of this directory so output paths do not already exist. The scripts deliberately refuse to overwrite runs. Install exact dependencies with a Python3.12 environment, then run `download_pinned_model.py`. The baseline snapshot contains all environment source and frozen task files; point `--env-root` to `curation-eval-base/environment-snapshot` when reproducing elsewhere.

Baseline command (choose a fresh output path):

```sh
python curation_driver.py --env-root curation-eval-base/environment-snapshot --out reproduced-base --variant v2 --split evaluation --expected-manifest 6893521e0391e831b45a414390246e0fb0a06d1c203892b66082a91f8ae22730
```

`prepare_sft.py` regenerates the expert corpus from the snapshot. `train_sft.py` creates the fixed adapter using the saved corpus, config and software. For a fresh training run, move the archived `curation-sft` output aside before preparing it again. The scripts never read held-out task values to create training data.

Adapter command (choose a fresh output path):

```sh
python curation_driver.py --env-root curation-eval-base/environment-snapshot --out reproduced-sft --variant v2 --split evaluation --adapter-path curation-sft/adapter --expected-manifest 6893521e0391e831b45a414390246e0fb0a06d1c203892b66082a91f8ae22730
```

Every episode file contains sampled prompt text, raw model output, actual generated token IDs/counts, latency, exact tool responses, and exported environment trajectory. The two held-out runs use byte-identical driver/runtime source and the same prompt. Intermediate adapters and final optimizer tensors are retained. Model/base weights and virtual environments can be omitted from an archive and retrieved using the pinned downloader.

## Interpretation limits

48 held-out episodes cover36 new worlds.12 composition/policy-shift pairs share records and are correlated. One model, one seed, one predetermined adapter; this is a small controlled experiment, not a statistical estimate of general reliability. Development includes a composed example, so the composed split is a complexity test rather than a claim of unseen mechanisms. Curation scores on synthetic records do not measure the utility of a downstream trained model, production safety, or transfer to real organizational data.

Primary training API: https://github.com/ml-explore/mlx-lm/blob/v0.32.2/mlx_lm/LORA.md . The research script uses the pinned upstream trainer unchanged, with an explicit next-action-only loss callback and pretokenized full prefixes.

## Integrity and deterministic controls

`integrity-checks.json` verifies byte-identical baseline/adapter driver and runtime, identical prompts/tasks/budgets, and absence of terminal result information from all592 training and74 validation prefixes. `deterministic-controls.json` contains actual reference and no-op trajectories on all48 held-out episodes: reference48/48 exact successes, no-op0/48 (mean partial reward0.04167). The reference requires6–9 tool actions. These controls demonstrate that the frozen worlds are solvable within the18-step budget.

## Portable public bundle contents

The original research workspace retains intermediate40/80/120 adapters and final optimizer tensors. The public reproduction bundle intentionally includes only the final adapter, exact data/config/scripts and full rollouts; it omits base-model weights, intermediate adapters, optimizer tensors and the virtual environment. Base weights are retrieved by `download_pinned_model.py`; dependencies are installed from `requirements.lock.txt`. Retraining from scratch uses the provided fixed plan and full corpus. No claim of optimizer-state resume support is made for the slim public bundle.

## Completed base-versus-adapter result

Both models solved0/48 episodes. Mean reward regressed from0.0625 to0.03125. Base submitted37 episodes and exhausted the18-step budget on11. The adapter submitted7, exhausted18 steps on11, and exhausted4096 generated tokens on30. Malformed JSON rose from6/587 actions to248/598; total invalid environment actions rose46→249. Neither run had an inference or model-process network error.

All three split exact-success counts were zero: single/pair0/24, composition0/12, policy shift0/12. The12 paired worlds had0/12 joint successes. Full metrics and conditional grader-component counts are in comparison-summary.json; unfinished rollouts have no private component grades.

A post-hoc descriptive diagnostic found that the adapter matched the reference first four information-gathering actions in11 episodes versus0 for base, ignoring lookup-key ordering. This is neither necessary nor sufficient for task completion. The adapter made no valid write action in any episode. Teacher-forced monitor loss improvement did not translate into closed-loop task reliability. The full raw trajectories support inspecting this regression rather than inferring success from training loss.

The recorded episode times are observational:234.704 seconds for base and1065.903 for the adapter, which generated30,612 and149,972 tokens respectively. Public8B weight downloading overlapped part of the adapter run on the same host. These are not controlled performance-benchmark timings.
