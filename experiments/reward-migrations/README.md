# RL environments need migrations

The reproducible experiment behind [Latent's engineering post](https://aryanma.github.io/latent/blog.html).

We generated one local-model answer for each of 357 tasks with unchanged inputs, froze those answers, and evaluated them against two reference editions on identical databases. **30 of 355 resolved reward pairs changed label, while the accepted count fell from 210 to 206.** Two tasks timed out and remain unresolved. This is a measurement of reference migration, not a model-training result.

The release includes a compatibility planner, transitive artifact invalidation, a bounded read-only SQL evaluator, every rendered prompt and actual token sequence, and a constraint-preserving counterexample on a real database. No paid service, model call, or GPU is needed to reproduce the grading result.

## Verify the downloaded release

Python 3.9+; standard library only:

```sh
python3 verify_release.py
python3 -m unittest test_contract test_sql
python3 -m latent_migration plan examples/old.json examples/new.json
python3 -m latent_migration invalidate examples/dependencies.json reward:0
```

The verifier checks every packaged file, original generation/witness freezes, candidate identity, execution-cache provenance, and derives the transition matrix again from the recorded execution fingerprints. It does **not** execute SQL against the original databases. That separate check follows below. Hashes detect changed files; they are not third-party attestation that an experiment occurred.

## Reexecute the primary experiment

```sh
python3 download_sources.py --output ./sources
python3 study.py references --sources ./sources --out ./recomputed
python3 study.py evaluate --sources ./sources --out ./recomputed \
  --generation ./generation --predictions ./generation/candidates.jsonl
python3 verify_release.py --sources ./sources
```

The download fetches about 347 MB and extracts approximately 1.5 GB of databases. Sources are public and SHA-256 pinned. Existing matching files are reused. `--verify-only` verifies an existing download without accessing the network. The default `core` group is sufficient; optional `legacy` and `candidates` groups were exploratory inputs and do not enter this experiment.

Published grading used Python 3.9.6, SQLite 3.51.0, macOS 26.6 arm64, two workers, a 60-second per-query timeout, a 100,000-row cap, a 200,000-byte SQL cap, and a 256 MiB SQLite heap limit. Use a Python build with recent SQLite (at least 3.46; references use functions such as `IIF`). The complete runtime fingerprint is in `evaluation/*-runtime.json`. Another SQLite build may change query behavior; another machine may change timeouts. The evaluator records those differences and refuses stale reference caches. Keep reproduction output separate from the released `evaluation/` directory.

The fixed UTC clock is `2026-10-31 00:00:00`. The clock adapter covers `CURRENT_TIMESTAMP`, `CURRENT_DATE`, `CURRENT_TIME`, and SQLite date/time functions, including implicit `now`; it rejects local-time modifiers. Calendar arithmetic is delegated to SQLite. No original database is writable, and database hashes are checked before and after execution.

### Published transition matrix

| Archived → revised reward | Count |
| --- | ---: |
| 1 → 1 | 193 |
| 1 → 0 | 17 |
| 0 → 1 | 13 |
| 0 → 0 | 132 |
| Unresolved | 2 |

The candidate for task 483 timed out. The identical old/new reference for task 701 timed out. SQL syntax errors receive zero when the reference executes successfully; timeouts, resource-limit failures, and invalid references remain unknown. The same rule applies before and after the migration.

Reward is exact equality of sets of tuples, following BIRD execution matching: duplicates and row order are ignored. Numeric equality follows Python's integer/float equality, including exact integral floats. This comparator is not general SQL equivalence and can miss errors on one finite database.

### Parser sensitivity

The primary parser is identity: the exact raw model output is executed as SQL. The instruction requested SQL without fences; 50 outputs nevertheless have a complete outer Markdown fence. No answer was silently cleaned before the primary analysis.

```sh
python3 parser_sensitivity.py --sources ./sources --out ./recomputed \
  --generation ./generation
```

This separately labeled post-hoc check removes only one complete `sql`, `sqlite`, or unlabeled outer fence. It does not repair queries or generate new answers. Accepted counts become 236 → 227, with 24 positive-to-negative and 15 negative-to-positive changes (39 total), and the same two unresolved tasks. The primary claim remains 30 flips under identity extraction. Results are written to `recomputed/parser-sensitivity.json`.

## Source editions and admission

| Input | Pinned revision |
| --- | --- |
| Archived BIRD Mini-Dev | `birdsql/bird_mini_dev` at `f65faf4ae3b638c1fa6df1d3370c8d92c8366301` |
| Arcwise-Plat **SQL-only** corrections | `uiuc-kang-lab/arcwise-plat` at `8e6eb6e18487a9dabaf761bb9e62b1234e340301`, file `arcwise_plat_sql_only_with_diff.json` |
| October 28 BIRD Mini-Dev, inventory only | `birdsql/bird_mini_dev` at `5b256b5a9c17478f06ed6912612e9a14d17065c8` |
| Databases | BIRD `dev_20240627`, from `https://bird-bench.oss-cn-beijing.aliyuncs.com/dev.zip` |

Among 500 archived tasks, 258 retain identical question, evidence, database identity, and SQL; 99 retain identical inputs but change SQL; 141 change question or evidence; two are absent. The first two groups form the complete 357-task cohort. Equality is exact: null and empty strings are not conflated. All database bytes and rendered schema/context bytes are identical across the two grading passes. The 99 SQL edits change 70 executed reference results, of which 30 change this candidate set's reward.

The October release uses new 0–499 IDs and has zero exact question/evidence/database matches to the archive. It is a separate inventory, **not** the revised side of the controlled experiment. A reused numeric ID does not establish lineage. Likewise, Arcwise-Plat's full variant is not the SQL-only variant used here, and its `original_*` fields need not point to the archived BIRD edition.

The expert corrections belong to the BIRD/Arcwise/UIUC contributors. Latent did not produce or independently certify every correction.

## Fresh generation and optional regeneration

`generation/` contains the original frozen run. One greedy answer per case, no execution tools, retries, answer selection, or reference answers in the prompt. Inputs are table DDL plus exact question/evidence. The model is `mlx-community/Qwen3.6-35B-A3B-4bit`, revision `38740b847e4cb78f352aba30aa41c76e08e6eb46`, using MLX-LM 0.32.2 / MLX 0.32.4 on Apple Silicon, native nonthinking template, seed 42 per case, and a 1,024-token output cap. All 357 completed with no inference error or token-limit termination. Actual input/output token IDs, including terminal EOS when generated, are retained.

The generation cohort and protocol were frozen before the full run; grading was a separate stage. The two loader-smoke cases were included again in the complete run without protocol changes. Generation involved 375,557 input tokens and 19,369 output tokens including EOS; peak MLX memory was approximately 21.45 GB. No model training was performed.

`admission.py` deliberately admits **only this published candidate set**: it verifies the 379-file generation freeze, raw-output identity, rendered observations, token digests, model/runtime identities, database hashes, and messages reconstructed from both editions. Altering a prediction is a new experiment, not a reproduction of the fixed-output migration.

For independent candidate regeneration, see [regenerate/README.md](regenerate/README.md). Its portable CLI reconstructs the native prompts exactly and creates a new run. CPU-only preparation was verified byte for byte; the portable CLI was not used for a second full inference run. Different hardware can produce different outputs even with greedy decoding. The optional weights occupy approximately 20.4 GB; none are included in this package.

Some original frozen scripts record absolute paths from the measurement machine. They are historical provenance, not portable entry points. Use `study.py`, `download_sources.py`, and the `regenerate/` CLI instead.

## Reproduce the counterexample

See [counterexample/README.md](counterexample/README.md) for the full-database command. It copies the pinned database, inserts one transaction with a fresh primary key, runs the unchanged candidate and references, checks declared constraints and row differences, and verifies the original database and model-visible schema remain unchanged.

For task 1525, the candidate counts EUR transaction rows instead of distinct EUR customers. On the original date slice, both counts are seven and the candidate matches the revised reference at 2.7027027027027026%. One additional transaction for the same EUR customer changes the candidate to 3.088803088803089%; the reference stays unchanged. The revised reward changes from one to zero.

Two independent full-database reproductions produced the same mutated database hash. The 88 KiB browser fixture retains all 1,000 transactions and their 517 referenced customers. It preserves the supplied queries and insertion, not arbitrary queries over omitted tables or customers. [browser-fixture/README.md](browser-fixture/README.md) documents rebuilding it. The website executes the SQL locally with vendored sql.js; its earlier reference-switch figure displays recorded measurements.

This is one post-hoc counterexample, not an estimated failure rate or a proof of every unwritten business constraint.

## Compatibility API

```python
from latent_migration.contract import Contract, plan, invalidated

decision = plan(Contract.from_dict(old_json), Contract.from_dict(new_json))
dirty = invalidated(artifact_graph, changed=["reward:0"])
```

Complete examples are in `examples/`. They are illustrative contract hashes, not real-task attestations. Callers must construct fingerprints over the **complete** relevant dependencies, including model weights, sampling/selection settings, prompt rendering, tool interfaces, world state, and grader code/configuration. A hash identifies bytes; it does not prove semantic equivalence or completeness. The caller must establish lineage explicitly.

`plan_study.py` applies the same API to the actual frozen study: `evaluation/migration-plans.json` contains all 357 old/new contracts and decisions (258 reuse, 99 regrade). This post-run export binds the actual prompt hash, policy protocol/runtime, database bytes, interface, and reference execution provenance. It is not an additional preregistered experiment. The release verifier independently regenerates these decisions.

- `reuse`: all declared dependencies match.
- `regrade`: only an agent-hidden terminal grader changed.
- `reexecute`: unobserved world state changed; execute the fixed action again.
- `rerun`: policy, observations, interface, or feedback that could affect the rollout changed.
- `review`: lineage or a required fingerprint is missing.

A reward that affects retries, critiques, selection, or stopping is not private terminal feedback. An interactive agent observing changed rows needs a fresh rollout, even if executing its old actions remains useful as a counterfactual diagnostic. Regrading old data does not make it on-policy for a new model. The dependency graph invalidates all downstream declared artifacts, including group-normalized advantages of outputs whose own reward stayed the same.

This is a supported single-action study and a conservative planner, not a production training orchestrator or a proof of causal equivalence for arbitrary agents. Harbor's job diff/reuse planning and LangSmith's evaluation of existing traces are relevant prior infrastructure; ReViSQL supplies stronger SQL-equivalence work and expert corrections.

## License and contents

Read [LICENSE](LICENSE) and [DATA-LICENSE.md](DATA-LICENSE.md). Independent Latent code is MIT; dataset-derived prompts, task records, reference annotations, results, and database projections retain CC BY-SA 4.0 attribution and share-alike conditions. Model and third-party runtime licenses remain their own. Original databases and model weights are downloaded separately.

`ARTIFACTS.json` inventories the package. `evaluation/query-cache/` holds per-query fingerprints and bounded result previews. `generation/` holds complete model traces. No unlicensed exploratory third-party model predictions are bundled or used in the primary result.
