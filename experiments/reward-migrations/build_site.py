"""Render the article's examples from released evidence, not hand-entered scores."""
import argparse
from html import escape
import json
from pathlib import Path
import re

from study import load, keyed, OLD, NEW


HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent.parent
CASES = [
    {"id": "1322", "label": "Counting events", "paraphrase": "Count meetings attended by more than ten club members.",
     "old_explanation": "The archived query returns four rows containing 1, one per qualifying event. Under result-set comparison, those rows collapse to {1}. The model’s answer, {4}, is rejected.",
     "new_explanation": "The revised query counts the qualifying events and returns {4}. The exact same model answer is now accepted."},
    {"id": "115", "label": "Sorting numbers", "paraphrase": "For the most populous district in south Bohemia, what percentage of clients are male?",
     "old_explanation": "Population is stored as text. The model and archived reference both select 93,931 ahead of 177,686. Their matching result, 44.262295%, is accepted.",
     "new_explanation": "The revised reference sorts population numerically. It selects the district with 177,686 inhabitants and returns 40%. The unchanged model answer is now rejected."},
]


def element_text(value):
    return escape(str(value), quote=True)


def build(sources):
    before, after = keyed(load(sources / OLD)), keyed(load(sources / NEW))
    candidates = keyed(load(HERE / "generation/candidates.jsonl"))
    results = {row["question_id"]: row for row in load(HERE / "evaluation/results.json")["rows"]}
    cases = []
    for spec in CASES:
        key, row = spec["id"], results[spec["id"]]
        case = dict(spec, candidate_sql=candidates[key]["sql"], old_sql=before[key]["SQL"], new_sql=after[key]["SQL"],
                    old_reward=row["old_reward"], new_reward=row["new_reward"])
        for dest, field in (("old_execution", "old_reference"), ("new_execution", "new_reference"), ("candidate_execution", "candidate")):
            case[dest] = load(HERE / "evaluation/query-cache" / (row[field] + ".json"))["execution"]
        cases.append(case)
    current = cases[0]
    h = element_text

    def preview(execution):
        n = execution["distinct_rows"]
        return f"{n} distinct result row{'s' if n != 1 else ''}; preview: {json.dumps(execution['preview'], ensure_ascii=False)}"

    buttons = "".join(f'<button type="button" data-case="{case["id"]}" aria-pressed="{str(case == current).lower()}" disabled>{h(case["label"])}</button>' for case in cases)
    witness = f'''<figure class="witness" id="recorded-witness" aria-labelledby="witness-title">
<p class="figure-title" id="witness-title">01 / Regrade the same answer</p>
<div class="case-switch" role="group" aria-label="Recorded examples">{buttons}</div>
<p class="question-label"><span id="case-id">BIRD {current['id']}</span> · question paraphrased</p>
<p class="case-question" id="case-question">{h(current['paraphrase'])}</p>
<div class="code-label"><span>Recorded model output · unchanged</span><a id="case-record" href="./experiments/reward-migrations/generation/full/{current['id']}.json">Exact trace</a></div>
<div class="code-block"><pre id="case-sql">{h(current['candidate_sql'])}</pre></div>
<div class="version-control"><span>Grade against</span><div class="version-buttons" role="group" aria-label="Reference version"><button type="button" data-version="old" aria-pressed="true" disabled>Archived reference</button><button type="button" data-version="new" aria-pressed="false" disabled>Expert revision</button></div></div>
<div class="reward-line" aria-live="polite" aria-atomic="true"><strong id="case-reward">{current['old_reward']}</strong><span id="case-verdict">{'Accepted' if current['old_reward'] else 'Rejected'} by this reference</span></div>
<p class="case-explanation" id="case-explanation">{h(current['old_explanation'])}</p>
<details><summary>Inspect the reference queries and results</summary><div class="reference-pair"><div><h3>Archived reference</h3><div class="code-block"><pre id="case-old-sql">{h(current['old_sql'])}</pre></div><p class="result-preview" id="case-old-result">{h(preview(current['old_execution']))}</p></div><div><h3>Expert revision</h3><div class="code-block"><pre id="case-new-sql">{h(current['new_sql'])}</pre></div><p class="result-preview" id="case-new-result">{h(preview(current['new_execution']))}</p></div></div><h3>Model’s executed result</h3><p class="result-preview" id="case-model-result">{h(preview(current['candidate_execution']))}</p></details>
<figcaption><span id="case-summary">Recorded transition: {current['old_reward']} → {current['new_reward']}. The model output is identical in both passes.</span> This figure displays measured results; it does not make a model call.</figcaption>
</figure>'''

    browser = load(HERE / "browser-fixture/browser-fixture.manifest.json")
    live = f'''<figure class="counterexample" aria-labelledby="live-title">
<p class="figure-title" id="live-title">02 / Change the world, keep the answer</p>
<p class="fine">One existing EUR customer makes one additional transaction. The queries stay fixed.</p>
<table class="data-table">
<thead><tr><th scope="col">Measure</th><th scope="col" class="number">Original data</th><th scope="col" class="number" id="live-world">Original data</th></tr></thead>
<tbody>
<tr><th scope="row">Distinct customers</th><td class="number">259</td><td class="number" id="live-customers">259</td></tr>
<tr><th scope="row">EUR transactions</th><td class="number">7</td><td class="number" id="live-eur-transactions">7</td></tr>
<tr><th scope="row">Distinct EUR customers</th><td class="number">7</td><td class="number" id="live-eur-customers">7</td></tr>
<tr><th scope="row">Model query</th><td class="number">2.702703%</td><td class="number changed-value" id="live-candidate">2.702703%</td></tr>
<tr><th scope="row">Revised reference</th><td class="number">2.702703%</td><td class="number" id="live-reference">2.702703%</td></tr>
<tr><th scope="row">Reward</th><td class="number">1</td><td class="number changed-value" id="live-reward">1</td></tr>
</tbody>
</table>
<div class="live-controls"><button class="run" id="add-transaction" type="button" disabled>Add one transaction</button><button class="reset" id="reset-transaction" type="button" disabled>Reset</button></div>
<p class="fine live-status" id="live-status" role="status">Baseline from the released run. The button executes the queries in your browser using a local SQLite copy.</p>
<details><summary>Inspect the SQL, mutation, and fixture</summary>
<h3>The model query</h3><div class="code-block"><pre>{h(browser['queries']['candidate'])}</pre></div>
<h3>The revised reference</h3><div class="code-block"><pre>{h(browser['queries']['new_reference'])}</pre></div>
<p class="fine">The mutation copies transaction 579 as primary key 1001. It preserves the original customer, date, and other fields. The date slice currently contains <span id="live-transactions">425</span> transactions.</p>
<p class="fine">The 88 KiB fixture keeps all 1,000 original transactions and their 517 referenced customers. These two queries have the same results as on the full database. Other tables and unreferenced customers are omitted; this projection is not a replacement for arbitrary queries over the full database.</p>
<p class="fine"><a href="./data/reward-migrations/browser-fixture.sqlite" download>SQLite fixture</a> · <a href="./data/reward-migrations/browser-fixture.manifest.json">Queries, mutation, and provenance</a> · <a href="./experiments/reward-migrations/counterexample/run1/results.json">Full-database witness</a></p>
</details>
<figcaption>One constructed counterexample from task 1525. No inference is involved. After the insertion, the model query returns 3.088803%; the revised reference remains at 2.702703%.</figcaption>
</figure>'''

    payload = {"cases": cases, "browser": browser}
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    page = PROJECT / "blog.html"
    html = page.read_text()
    for name, value in (("WITNESS", witness), ("COUNTEREXAMPLE", live), ("STUDY_DATA", '<script type="application/json" id="study-data">' + encoded + '</script>')):
        pattern = rf"<!-- {name}_START -->.*?<!-- {name}_END -->"
        html, count = re.subn(pattern, lambda match: f"<!-- {name}_START -->\n{value}\n<!-- {name}_END -->", html, flags=re.S)
        if count != 1:
            raise ValueError("Missing or duplicate site marker: " + name)
    page.write_text(html)
    (PROJECT / "data/reward-migrations/site-data.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    print("Rendered two recorded cases and one live SQLite counterexample.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sources", type=Path, required=True)
    build(parser.parse_args().sources)
