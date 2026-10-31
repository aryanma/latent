# One transaction separates execution agreement from query correctness

This is one **constructed, post-hoc counterexample** for legacy BIRD task 1525. It is not a failure-frequency estimate, an independently sampled test distribution, or new model inference. The SQL candidate is an unedited output from the already completed 357-task local Qwen3.6-35B-A3B evaluation.

The question asks: “What is the percentage of the customers who used EUR in 2012/8/25?” The candidate divides the number of EUR **transaction rows** by the number of distinct customers. The expert-corrected reference counts distinct EUR customers in its numerator.

On the original public database, the selected date has 425 transactions from 259 distinct customers. Its 7 EUR transactions happen to come from 7 distinct EUR customers. Both queries therefore return `2.7027027027027026`, so the execution comparator accepts the candidate.

We copy the pinned database and clone transaction 579 as transaction 1001. All other values remain identical:

```sql
INSERT INTO transactions_1k
  (TransactionID, Date, Time, CustomerID, CardID,
   GasStationID, ProductID, Amount, Price)
VALUES
  (1001, '2012-08-25', '09:05:00', 679, 752560,
   267, 2, 107, 92.26);
```

The candidate now returns `3.088803088803089` (8 / 259 × 100). The corrected reference remains `2.7027027027027026` (7 / 259 × 100). Acceptance against the corrected reference changes from 1 to 0. The original reference returns `1.6470588235294117` before and `1.8779342723004695` after; those values are included for provenance, not used to define the counterexample.

## What was checked

- Original database SHA-256 is unchanged before and after the experiment.
- The copy starts byte-identical to the original.
- `PRAGMA integrity_check` returns `ok` and `PRAGMA foreign_key_check` returns no violations before and after mutation.
- Foreign-key enforcement is enabled during insertion. `transactions_1k` declares an autoincrement primary key and no foreign keys; we additionally check that the copied customer, gas-station, and product identifiers each point to an existing row. This extra check is distinct from enforcement of declared constraints.
- Exact transaction set differences contain only the specified added row, with no removed rows. Transaction count changes from 1,000 to 1,001. All other user-table content hashes remain identical. SQLite's internal autoincrement sequence advances from 1,000 to 1,001.
- Schema definitions and constraints are identical. The DDL renderer and frozen inference prompt protocol reconstruct the actual recorded model messages both before and after mutation.
- The fixed-clock root executor is copied unchanged as `executor_snapshot.py`, pinned by SHA-256. Both worlds use UTC `2026-10-31 00:00:00` and the same exact BIRD row-set comparator.
- Two runs starting from independent source copies produced byte-identical counterfactual databases and identical proof fingerprints after excluding execution latency. The runs took 2.96 and 2.83 seconds.

The final generated prompt included schema, question, and evidence. It exposed no database rows or query tools. Changing rows therefore leaves this policy's actual input unchanged, so reexecuting the recorded fixed SQL is appropriate. This conclusion does not extend automatically to an interactive agent that previously observed rows or execution feedback.

Declared database constraints are not a complete statement of real business rules. This experiment establishes a concrete difference between the two SQL queries on a database satisfying the declared constraints; it does not prove that every conceivable real-world business invariant is preserved.

## Reproduce without models or APIs

Use the source downloader from the reward-migration experiment to obtain the original BIRD SQLite database, then run:

```bash
python3 reproduce_witness.py \
  --source-db /path/to/debit_card_specializing.sqlite \
  --out /tmp/independent-witness-run
```

Python 3.9+ standard library only. The input database must match the pinned SHA-256. The output directory must not exist; the script refuses to overwrite one. The original database is opened read-only, and mutation occurs only after making a separate byte-verified copy. Every integrity, identity, and result assertion is checked by the script. No model is loaded and no network request is made.

Required adjacent files: `inputs.json`, `executor_snapshot.py`, and `prompt_protocol.py`. The script writes `results.json` and a 35 MB counterfactual database. Published packages can omit both database copies; the script recreates the mutation from the original source.

## Artifact and source identity

- Original database SHA-256: `b3d149ad05746dbbe5116e229e17e18f09c39db43cf117d9ef3441753608b691`.
- Executor SHA-256: `2d3733f209125643b2d76282385360dcad0ac927385db512ea6e0d6fd317f8b2`.
- Recorded model prompt SHA-256: `53479cfee0dacf0c1ac84f62c653000c0ee8b87940b60079bea55958209a54b8`.
- Exact mutation, full constraints, per-table hashes, source metadata, query text, and execution outputs are in `inputs.json` and `run1/results.json`; independent replication is in `run2/results.json`.
- Compact repeatability checks are in `verification-summary.json`.

Original annotations and database: [BIRD Mini-Dev](https://huggingface.co/datasets/birdsql/bird_mini_dev/tree/f65faf4ae3b638c1fa6df1d3370c8d92c8366301). Corrected annotations: [UIUC Kang Lab Arcwise-Plat](https://huggingface.co/datasets/uiuc-kang-lab/arcwise-plat/tree/8e6eb6e18487a9dabaf761bb9e62b1234e340301), SQL-only configuration. These datasets declare CC BY-SA 4.0. The included task excerpts and the constructed database modification retain that attribution and license; the change is explicitly described above. Expert corrections are the upstream authors' work. The demonstration does not claim to discover the general problem of execution matching versus semantic equivalence, already discussed in [Thinking Machines/UIUC's August 2026 research](https://thinkingmachines.ai/news/putting-task-expertise-into-rl/).
