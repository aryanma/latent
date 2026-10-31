# Actual SQLite fixture for the case 1525 browser witness

`browser-fixture.sqlite` is an 88 KiB projection of the original public BIRD database. It contains **all 1,000 original `transactions_1k` rows**, plus **the 517 actual customers referenced by those transactions**. Cell values are copied unchanged. The original `CREATE TABLE` declarations, primary keys, and unique index are preserved. SQLite also creates the internal `sqlite_sequence` table required by the unchanged `AUTOINCREMENT` declaration. No other user tables are included.

This fixture supports real SQLite execution in SQL.js. It is not a table of precomputed answers. The manifest's recorded numbers are independent verification targets, not a substitute for executing the queries.

| Query | Original fixture | After insertion |
| --- | ---: | ---: |
| Recorded model candidate | 2.7027027027027026 | 3.088803088803089 |
| Expert-corrected reference | 2.7027027027027026 | 2.7027027027027026 |
| Original reference | 1.6470588235294117 | 1.8779342723004695 |

The insertion clones transaction 579 with fresh primary key 1001. The exact SQL and bound values, three full query strings, before/after results, source hashes, original schemas, row selection queries, and constraint checks are in `browser-fixture.manifest.json`. The fixture and its mutated copy both pass `integrity_check` and `foreign_key_check`. The three original-fixture outputs equal direct execution on the full source database; mutated outputs equal the independently recorded full-database witness.

For browser reset, construct a new SQL.js database from the original downloaded fixture bytes. Apply the insertion once per reset; a second insertion with the same primary key should fail normally. Reset restores the actual database state.

## Scope

The omitted data are 31,944 customers with no row in `transactions_1k`, and the `gasstations`, `products`, and `yearmonth` tables. This projection preserves the three provided queries and the documented insertion. It does **not** preserve arbitrary queries counting all original customers or using omitted tables. This is one constructed, post-hoc counterexample, not a model failure-frequency estimate.

## Reproduce

```bash
python3 create_fixture.py \
  --source-db /path/to/debit_card_specializing.sqlite \
  --out /tmp/browser-fixture.sqlite
```

Python 3.9+ standard library only; keep `fixture-inputs.json` adjacent to the creator script. The original database must match the pinned hash. It is opened read-only and checked again after construction. The destination must not exist. The script verifies the insertion on a temporary copy, leaving the deliverable fixture in its original state. No model, network call, or modification of the earlier witness artifacts is involved.

Fixture SHA-256: `dff0b68502a0af068bfe6d980b84631a7f364f4504170f8d99a8d16a6fddbdff`.

## Data license and attribution

The fixture is adapted from the [BIRD benchmark](https://bird-bench.github.io/) database, by Jinyang Li, Binyuan Hui, Ge Qu and collaborators. Original data are available in the [official BIRD dev archive](https://bird-bench.oss-cn-beijing.aliyuncs.com/dev.zip), release `dev_20240627`; source database SHA-256 is `b3d149ad05746dbbe5116e229e17e18f09c39db43cf117d9ef3441753608b691`.

Original task annotations come from [BIRD Mini-Dev](https://huggingface.co/datasets/birdsql/bird_mini_dev/tree/f65faf4ae3b638c1fa6df1d3370c8d92c8366301). The expert-corrected reference comes from [UIUC Kang Lab Arcwise-Plat](https://huggingface.co/datasets/uiuc-kang-lab/arcwise-plat/tree/8e6eb6e18487a9dabaf761bb9e62b1234e340301), SQL-only configuration, associated with the work of Yuxuan Zhu, Tengjun Jin, Yoojin Choi, Daniel Kang and collaborators.

These source datasets declare [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/). This derived fixture and included annotation excerpts are distributed under the same license. Changes by Latent: retain two original tables, omit unreferenced customer rows and other tables, and specify a separate optional counterfactual insertion. Retained data values and relevant schema declarations are unchanged.
