# Latent λ

The Latent research website. Live at https://aryanma.github.io/latent/

## Current research

**[RL environments need migrations](https://aryanma.github.io/latent/blog.html)** is the site's single research article. On 357 frozen model outputs, revised SQL references changed 30 of 355 resolved reward labels while the accepted count fell by four. The article includes recorded reference comparisons and a real SQLite counterexample executed in the browser.

- `experiments/reward-migrations/`: checker, evaluator, all fresh model traces, source pins, execution caches, full-database counterexample, portable regeneration CLI, and reproduction instructions.
- `data/reward-migrations/`: public result files, 88 KiB database fixture, and downloadable reproduction archive.
- `migration/`: article interface and vendored sql.js runtime. The browser example makes no model/API calls.
- `blog.html`: the complete article; `index.html` links to it directly. Previous article URLs redirect here.

Verify the release and test the SQL/compatibility logic:

```sh
cd experiments/reward-migrations
python3 verify_release.py
python3 -m unittest test_contract test_sql
```

The [experiment README](experiments/reward-migrations/README.md) documents reexecution against pinned original databases, methodology, parser sensitivity, and limitations. No model training or downstream improvement is claimed.

UI tests use Node.js 22.20+ and `jsdom@27.0.1` installed outside this static repository:

```sh
npm install --prefix /tmp/latent-dom-check jsdom@27.0.1 --ignore-scripts
LATENT_JSDOM_PATH=/tmp/latent-dom-check/node_modules/jsdom node --test migration/research.test.mjs
```

These tests execute the actual SQLite WASM runtime and exercise DOM controls. They do not launch a browser or verify visual rendering.

After editing research assets, `python3 scripts/build-migration.py` creates the release manifest and deterministic ZIP, verifies the evidence, and checks public copies. The article's measured figures can be rebuilt using `experiments/reward-migrations/build_site.py --sources /path/to/pinned/sources`.

## Website

Static HTML/CSS/JavaScript, no backend, analytics, or API keys. GitHub Pages publishes the root of `main`. All browser runtime assets are served from this repository. `reading.html` contains the reading list; `notes.html` contains the company thesis and source notes.

The bundled EB Garamond font is distributed under `fonts/OFL.txt`. sql.js is MIT licensed under `migration/vendor/LICENSE-sql.js`. Independent migration code is MIT; dataset-derived study artifacts retain the attribution and CC BY-SA 4.0 terms documented in `experiments/reward-migrations/DATA-LICENSE.md`.

Earlier experimental code and frozen evidence remain under `experiments/curation-env`, `experiments/reward-boundary`, `data/curation`, and `data/signal` for provenance. They are not additional current blog posts, and their metrics do not enter the migration study. Their own READMEs document separate reproduction paths.
