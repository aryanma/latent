# Optional candidate regeneration

This is a portable implementation of the original experiment's inference protocol. It creates a **new run**. It does not modify, replace, or inherit the original run's artifact digest.

The primary reproduction of the published migration result is SQL regrading of the released fixed candidates. That path needs neither model weights nor model calls. Use this directory only to regenerate the model's SQL candidates independently.

## Fixed protocol

- All 357 tasks with identical database ID, question, and evidence strings in the pinned archived BIRD Mini-Dev and Arcwise-Plat `sql_only` releases; ascending numeric legacy question ID.
- Model: `mlx-community/Qwen3.6-35B-A3B-4bit`, revision `38740b847e4cb78f352aba30aa41c76e08e6eb46`.
- Native MLX-LM `qwen3_5_moe` text-only loader, without importing any prior experiment runtime.
- The original system prompt and read-only table DDL, followed by exact question/evidence strings. No reference SQL, row samples, execution tools, repair, or retries.
- Native pinned chat template, `enable_thinking=False`, `preserve_thinking=False`, greedy sampling, seed 42 per case, at most 1,024 output tokens, and 32,768 input-plus-output tokens. No context truncation.
- One output per case. SQL extraction is identity: no stripping whitespace or Markdown fences. Explicit inference errors produce `sql: null` and retain their error and any partial text.

The CLI verifies source, database, tokenizer, and model hashes. Before inference it verifies that the **entire prepared prompt file and cohort file are byte-identical to the original experiment**, including every input token ID. The regenerated SQL can still differ across hardware, operating-system versions, or numerical backends. Greedy decoding and a fixed seed do not guarantee bit-identical model outputs across machines.

## Obtain sources explicitly

Use the public study's existing source fetcher. This is an explicit network operation; the generation CLI itself cannot make network requests.

```sh
python /path/to/reward-migrations/download_sources.py --output ./sources
```

Its default `core` group supplies the two pinned datasets and the eleven BIRD SQLite databases expected by `source-pins.json`. The datasets are CC BY-SA 4.0; retain the study's source attributions and license notices when redistributing them or the prompt artifacts.

## Install the inference environment

The original run used Python 3.12, Apple Silicon, macOS 26.6, MLX 0.32.4, and MLX-LM 0.32.2. The regeneration backend is Apple Silicon MLX, not CUDA. The original run reached approximately 21.45 GB of MLX memory; model files occupy approximately 20.43 GB on disk.

From this directory:

```sh
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.lock.txt
```

The CLI checks the installed pinned package versions before a full run. It also verifies the relevant installed MLX-LM source files against `runtime-source-pins.json`.

Download the model explicitly if it is not already available locally:

```sh
hf download mlx-community/Qwen3.6-35B-A3B-4bit --revision 38740b847e4cb78f352aba30aa41c76e08e6eb46 --local-dir ./model
```

Keep the downloaded filenames unchanged. `model-manifest.json` supplies expected byte counts and SHA-256 hashes. The model is Apache-2.0 licensed; its license is included as `MODEL-LICENSE`.

## Prepare on CPU without loading a model

```sh
python rerun.py --sources ./sources --model-dir ./model --out ./prepared-check --prepare-only
```

This validates the databases, extracts DDL using read-only SQLite connections, and reproduces all 357 native prompts and token sequences. It does not import MLX or load the model weights. On a CPU-only machine, install `requirements-prepare.lock.txt` instead; the required local model files are `config.json`, `chat_template.jinja`, `tokenizer.json`, `tokenizer_config.json`, and `vocab.json`. They must still match the pinned hashes.

Preparation creates its own output directory. A later full run must use a different new directory; the CLI never overwrites an existing run.

## Generate a new run

This step performs local model inference for all 357 cases:

```sh
python rerun.py --sources ./sources --model-dir ./model --out ./regenerated-run
```

Each invocation writes:

- `registration.json` before inference, binding code and prepared inputs to the fixed settings;
- `cohort.json`, `schemas.json`, `prompts.json`, and source/model verification details;
- `full/<question_id>.json`, with exact rendered prompts, actual input/output token IDs, all raw output, token budgets, timings, and errors;
- `full/runtime-manifest.json`, with model identity, runtime source hashes, package versions, and machine details;
- `candidates.jsonl`, using unchanged generated text as SQL;
- `summary.json` and `artifact-freeze.json`.

Terminal EOS, when sampled, is preserved in `output_token_ids` and omitted from display text. After generation the script independently decodes the saved token IDs and checks that they reproduce the raw text. All cases remain in the output, including runtime errors and token-limit completions. No scoring is performed.

New runs are deliberately **not** accepted by the published study's `admission.py`, which validates one specifically frozen candidate set. Use a separate, explicitly labeled experiment when regrading regenerated candidates; do not replace the published results silently.

## Verification performed on this portable implementation

The CPU-only preparation command was run against the existing pinned local inputs. Its cohort file and complete prompt/token file matched the original frozen experiment byte for byte. No new inference was run to test this portable CLI. The original inference artifact remains unchanged.
