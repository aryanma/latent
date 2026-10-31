"""Render the article's result tables directly from the complete result artifact."""
import html
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parent
NAMES={
    'base':('Qwen3-1.7B','https://huggingface.co/Qwen/Qwen3-1.7B-MLX-4bit'),
    'adapted':('Qwen3-1.7B + 120-update LoRA',None),
    'scale8b':('Qwen3-8B','https://huggingface.co/Qwen/Qwen3-8B-MLX-4bit'),
    'currentmoe':('Qwen3.6-35B-A3B','https://huggingface.co/mlx-community/Qwen3.6-35B-A3B-4bit'),
}

def render(results):
    models=results['models']
    assert set(models)<=set(NAMES)
    parts=['<div class="research-table"><table><caption>Complete evaluation. Failed and unfinished runs are included.</caption>',
           '<thead><tr><th scope="col">Model / run</th><th scope="col">Solved</th><th scope="col">Mean reward</th><th scope="col">Invalid actions</th></tr></thead><tbody>']
    for key,(name,url) in NAMES.items():
        if key not in models: continue
        m=models[key];t=m['totals'];label=f'<a href="{url}">{html.escape(name)}</a>' if url else html.escape(name)
        parts.append(f'<tr><td>{label}</td><td>{m["successes"]} / {m["episodes"]}</td><td>{m["mean_reward"]:.4f}</td><td>{t["invalid_action_count"]} / {t["steps"]}</td></tr>')
    parts.append('</tbody></table></div>')
    base,adapted=models['base'],models['adapted']
    assert base['successes']==adapted['successes']==0, 'Revisit the interpretation if measurements change.'
    parts.append(f'<p>The short warm-start did not improve completion: both 1.7B variants solved 0 of 48 episodes. Mean reward fell from {base["mean_reward"]} to {adapted["mean_reward"]}. The adapted model submitted only {adapted["terminations"].get("submitted",0)} datasets, compared with {base["terminations"].get("submitted",0)} for its base. This run consumed fewer than one pass through the expert corpus; it is evidence about this particular training budget, not a general limit of supervised adaptation.</p>')
    if 'currentmoe' in models:
        current=models['currentmoe']
        parts.append(f'<p>The off-the-shelf Qwen3.6 checkpoint solved {current["successes"]} of {current["episodes"]} episodes, with {current["both_contracts_solved"]} of {current["policy_pairs"]} authority pairs fully solved. We did not adapt its weights. Its result measures the environment under another policy; it is not a training gain produced by Latent.</p>')
        parts.append('<p>The 8B and newer Qwen3.6 baselines were added as exploratory comparisons after observing the small model’s difficulty. Their protocols were fixed before their evaluations. Qwen3.6 uses a community four-bit conversion of a newer mixture-of-experts checkpoint: 35B total parameters, approximately 3B active. These are non-thinking, direct tool-use runs with no code-execution tool. Different architectures and tokenizers make this a comparison under common action/token caps, not a compute-matched scaling study.</p>')
        selected=json.loads((ROOT/models['currentmoe']['archive_directory']/'episode-policy_shift-2004.json').read_text())
        assert selected['summary']['success']
        parts.append('<p><a href="./curation.html?task=policy_shift-2004">Inspect one complete Qwen3.6 curation run.</a> The model corrects two labels, removes forbidden and evaluation-overlapping records, and deduplicates while preserving all four eligible lineages. This is a selected successful illustration; the table includes every run.</p>')
    else:
        parts.append('<p>The 8B baseline is an exploratory comparison added after observing the small model’s difficulty. Its protocol was fixed before its evaluation. These are non-thinking, direct tool-use runs with no code-execution tool.</p>')
    parts.append('<details><summary>Results by task split</summary><div class="research-table"><table><thead><tr><th scope="col">Run</th><th scope="col">Single/pair</th><th scope="col">Composed</th><th scope="col">Changed authority</th><th scope="col">Both contracts</th></tr></thead><tbody>')
    for key,(name,_) in NAMES.items():
        if key not in models: continue
        m=models[key]
        values=[f'{m["splits"][s]["successes"]} / {m["splits"][s]["episodes"]}' for s in ['single_or_pair','composition','policy_shift']]
        values.append(f'{m["both_contracts_solved"]} / {m["policy_pairs"]} pairs')
        parts.append('<tr><td>'+html.escape(name)+'</td>'+''.join(f'<td>{v}</td>' for v in values)+'</tr>')
    parts.append('</tbody></table></div></details>')
    return '\n'.join(parts)

if __name__=='__main__': print(render(json.loads((ROOT/'results.json').read_text())))
