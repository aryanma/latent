# Dataset attribution and license

The original BIRD tasks and databases are by Jinyang Li, Binyuan Hui, Ge Qu, and the BIRD collaborators. Arcwise-Plat expert-corrected annotations are by UIUC Kang Lab / Arcwise contributors, including Yuxuan Zhu, Tengjun Jin, Yoojin Choi, and Daniel Kang. Their work is credited separately from Latent's experiment.

Sources:

- https://bird-bench.github.io/
- https://huggingface.co/datasets/birdsql/bird_mini_dev/tree/f65faf4ae3b638c1fa6df1d3370c8d92c8366301
- https://huggingface.co/datasets/uiuc-kang-lab/arcwise-plat/tree/8e6eb6e18487a9dabaf761bb9e62b1234e340301
- https://bird-bench.oss-cn-beijing.aliyuncs.com/dev.zip

Dataset-derived material in this release is provided under **Creative Commons Attribution-ShareAlike 4.0 International (CC BY-SA 4.0)**:

- License overview: https://creativecommons.org/licenses/by-sa/4.0/
- Full legal terms: https://creativecommons.org/licenses/by-sa/4.0/legalcode

This includes copied task text, schemas and reference SQL; prompts and records incorporating them; derived model-output/evaluation artifacts; and the browser database projection. Preserve attribution, link the license, identify modifications, and apply the same license when sharing adapted material as required by its terms. No endorsement by the upstream authors is implied.

Latent's changes: selected all 357 exactly input-matched tasks from the pinned editions; assembled prompts; generated new candidate SQL locally; executed old and revised references; computed compatibility/reward changes; created a projection retaining two original database tables with all transactions and their referenced customers; and documented an optional one-row counterfactual insertion. Retained fixture cell values and CREATE TABLE declarations are unchanged. The full original databases are not bundled.

The download manifest also records exploratory legacy/candidate sources. Those optional groups are not inputs to the main result and are not included here. Their availability is not a grant to relicense them.

Independent checker and reproduction code is MIT licensed as specified in LICENSE. The optional Qwen model has its own Apache-2.0 license in regenerate/MODEL-LICENSE. The website's vendored sql.js has its MIT license in migration/vendor/LICENSE-sql.js.
