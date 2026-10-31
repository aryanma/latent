# Exploratory current-model baseline — Qwen3.6 (2026)

This is the final exploratory model extension, specified after Qwen3-1.7B failures and during the8B run. Its protocol was frozen before any Qwen3.6 inference. It is a newer-architecture comparison, not a parameter-only scaling experiment or a preregistered part of the original base-versus-adapter comparison. No model shopping follows this experiment.

## Sources and fixed artifacts

- Quantized checkpoint: https://huggingface.co/mlx-community/Qwen3.6-35B-A3B-4bit ; revision `38740b847e4cb78f352aba30aa41c76e08e6eb46`, created2026-04-16.
- Official source model: https://huggingface.co/Qwen/Qwen3.6-35B-A3B ; pinned metadata/template revision `995ad96eacd98c81ed38be0c5b274b04031597b0`.35B total parameters,3B active; different tokenizer and hybrid/MoE architecture from Qwen3.
- Both cards declare Apache-2.0. `LICENSE.txt` is the license from the pinned official model repository; the community quantization does not contain a separate license file.
- Four quantized weight shards total20,402,204,271 bytes. Each upstream LFS SHA256 is pinned in `frozen-current-plan.json` and verified after download in `model-manifest.json`.
- Same Python3.12.11 and34-package lock, MLX-LM0.32.2/MLX0.32.4. No backend upgrades or patches. The installed `qwen3_5_moe` implementation supports native text-only loading and strips vision weights through upstream sanitization. No images or vision processing are used.
- Backend source: https://github.com/ml-explore/mlx-lm/blob/v0.32.2/mlx_lm/models/qwen3_5_moe.py .

## Native template verification and exact history

`verify_native_template.py` compares the official and community chat-template files byte for byte and renders a multi-turn plain-JSON history with native `enable_thinking=False`. The result matches ChatML with the explicit empty-think assistant prefill. The native template trims outer whitespace and can split reasoning-like spans from old assistant text; the runtime preserves every raw history byte instead. `native-template-verification.json` records both the equivalence check and that deliberate preservation safeguard. It is not a blind reuse of an older tokenizer template. The actual model tokenizer is Qwen3_5Tokenizer; EOS is `<|im_end|>` (248046).

The task interface remains the same prompted JSON-action protocol. It does not use a different XML tool-call serialization through the template's `tools=` argument. No model output is repaired or coerced.

## Frozen experiment

Original v2 system prompt, identical public tasks/contracts/typed tool schemas, complete exact history, explicit nonthinking prefill, greedy decoding, seed42,18 steps,512 generated tokens per turn,4096 per episode,32768-token context cap with explicit rejection rather than truncation. Four development episodes are smoke tests only; no changes follow their results. All48 held-out episodes are run if native backend loading/inference works. Setup investigation is bounded; an unsupported backend is reported as unavailable rather than hidden by extensive patches.

48 episodes cover36 worlds, including12 composition/policy-shift pairs sharing records. These pairs are correlated. One deterministic run under this particular nonthinking JSON-action protocol is not a claim about the model's maximum capability or production reliability.

## Reproduce

Use Apple silicon and Python3.12. Create a virtual environment, install exact `requirements.lock.txt`, then run `download_pinned_model.py` and `verify_native_template.py`. The public bundle omits base weights and the virtual environment. It contains source/metadata/template verification, frozen task snapshots and complete measured result artifacts. Public anonymous weight downloads are separate from inference. Model inference blocks network connect/DNS/sendto and uses no credentials or remote inference service.

```sh
python curation_driver.py --env-root environment-snapshot --out reproduced-development --variant v2 --split development --expected-manifest 6893521e0391e831b45a414390246e0fb0a06d1c203892b66082a91f8ae22730
python curation_driver.py --env-root environment-snapshot --out reproduced-evaluation --variant v2 --split evaluation --expected-manifest 6893521e0391e831b45a414390246e0fb0a06d1c203892b66082a91f8ae22730
```

Fresh output paths are required. Full prompts, raw outputs, generated token IDs/counts, timing, exact tool observations and exported trajectories are saved for each episode. A bounded rollout ending before submit has no private grader-component result; do not treat its wrapper reward0 as a completed grading event. Local episode timings are observational, not standardized performance benchmarks.

## Completed result

The native backend worked without patches. Development smoke finished0/4 exact successes,31 actions,1 malformed/invalid action; these results caused no protocol change.

The final held-out run solved5/48 episodes (10.4167%), with mean reward0.1354167. Single/pair:4/24 successes, mean reward0.1666667. Composition:0/12, mean0.0625. Policy shift:1/12, mean0.1458333. No paired world was solved under both authority contracts (0/12); one pair had a success on one side.

The model submitted47 episodes and exhausted the18-step budget on1; none exhausted the generation budget. There were19 malformed JSON responses and38 invalid environment actions among453 actions. It generated38,580 tokens. Summed episode walltime was618.305 seconds; peak recorded MLX allocation was21,537,113,502 bytes. No inference error or model-process network attempt was recorded.

Among47 submitted/graded episodes, overlapping counts of episodes failing individual components were: coverage16, label accuracy36, safety16, uniqueness18 and provenance26. The unfinished episode has no private component grade. Exact successes were leakage-1003, permissions-1008, permissions-1014, leakage-1015 and policy_shift-2004. These are results of the off-the-shelf2026 checkpoint, not evidence that the earlier1.7B SFT run worked.

`current-summary.json` gives all split metrics and raw counts. `comparison-integrity.json` verifies the shared driver, task manifest, prompt, budgets and initial prompt bytes across all four runs. Reference actions also fit the limits under this model's tokenizer:217 maximum tokens per action and584 per complete episode (measured from reference JSON+EOS, not model generations). `measure_reference_tokens.py --controls PATH_TO_DETERMINISTIC_CONTROLS_JSON` reproduces that check.

The public bundle omits base weights and the virtual environment. The official and community template texts are also copied to top-level `official-chat-template.jinja` and `community-chat-template.jinja` for review without downloading weights. The downloader retrieves the small official template/license sources alongside the pinned community checkpoint when reproducing from scratch. No further model inference or tuning followed the final48 episodes.
