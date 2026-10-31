# Exploratory 8B scale baseline

This experiment was specified after observing difficulty in the1.7B model. It is an exploratory larger-model baseline, not part of the original preregistered base-versus-adapter comparison. No8B outcomes were available when `frozen-scale-plan.json` was written. Four development episodes are a smoke test only; no prompt selection, training, checkpoint selection or per-task change follows them.

Official model: https://huggingface.co/Qwen/Qwen3-8B-MLX-4bit . Apache-2.0. Revision `383413e909f3bc5303ce195ebbdf0339c5a1a2a3`. Weight SHA256 `fcc83d7537bee76cc143be3e25f8954b816798f93528103db1cddb02977c5617`. Downloaded4,367,856,304 bytes, including4,351,884,216 weight bytes. Upstream LFS hashes were verified. No credentials or remote inference APIs were used.

The driver is byte-identical to the original1.7B driver. The runtime differs only in model repository, revision, and expected weight hash constants. Dependencies are the identical34-package lock in a separate Python3.12.11 virtual environment. The frozen public task/contract/tool snapshots are copied unchanged into `environment-snapshot`.

Protocol: the original v2 prompt, exact untruncated history, verbatim ChatML, explicit nonthinking prefill, greedy decoding, seed42,512 generated tokens per turn,4096 per episode,18 environment steps,32768-token context cap with explicit rejection. Strict JSON output; malformed actions are neither repaired nor coerced. No paid inference. The model process blocks socket connect, DNS and sendto. This model's own weights were downloaded before its inference. A separate later model's public weight download overlapped part of this run on the same host; timings are observational, not a controlled performance comparison.

On Apple silicon, create a Python3.12 virtual environment, install `requirements.lock.txt`, and run `download_pinned_model.py`. The model weights are intentionally omitted from portable result bundles.

```sh
python curation_driver.py --env-root environment-snapshot --out reproduced-development --variant v2 --split development --expected-manifest 6893521e0391e831b45a414390246e0fb0a06d1c203892b66082a91f8ae22730
python curation_driver.py --env-root environment-snapshot --out reproduced-evaluation --variant v2 --split evaluation --expected-manifest 6893521e0391e831b45a414390246e0fb0a06d1c203892b66082a91f8ae22730
```

Use fresh output paths; the driver refuses overwrite. Each episode records raw model output, token IDs/counts, full prompts and responses, latency, invalid actions and the final exported trajectory. All48 evaluation episodes are reported. These cover36 new worlds:12 composition/policy-shift pairs share records and are correlated.

This comparison changes model weights and architecture, not only a numerical parameter-count setting; it is not a controlled scaling-law experiment. It does not measure downstream training-data utility, transfer to real organizational data, or production reliability. Latencies are local observations, not a standardized hardware benchmark.

The portable public bundle omits base weights and the virtual environment. It includes the pinned downloader, exact dependency lock, frozen task snapshot, driver/runtime, model license/metadata and full result artifacts. Recreate dependencies and download the pinned public weights before running the commands above.

Development smoke result (no changes afterward): clean1.0, labels0, versions1/6, composition0;1/4 exact success,44 actions,0 invalid JSON and0 invalid environment actions. The full48-episode evaluation follows this smoke using the frozen protocol, irrespective of these results.

## Completed held-out result

0/48 exact successes; mean reward0.0239583. Single/pair0/24 (mean0.0375), composition0/12 (mean0.0208333), policy shift0/12 (mean0). Joint paired successes0/12. The model submitted44 episodes, exhausted18 steps on3 and exhausted4096 generated tokens on1. There was1 malformed JSON output and53 invalid environment actions among570 actions.47,992 tokens were generated; summed episode walltime was1338.905 seconds. There were0 inference errors and0 model-process network attempts.

Conditional on44 submitted/graded episodes, overlapping failure counts were coverage37, label accuracy31, safety13, uniqueness8 and provenance13. Four unfinished episodes have no private component grade. `scale-summary.json` and all48 raw episodes document the full outcome. This is a negative result for this fixed nonthinking protocol, not a claim about every possible use of the8B model.
