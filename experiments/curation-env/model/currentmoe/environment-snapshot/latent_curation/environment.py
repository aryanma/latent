"""A small data-curation world with separate observations, actions, and grading.

No model, network, pandas, database, or third-party package is needed to run the env.
Task records are synthetic. A reference solver operates only on visible evidence.
The private answer key is independently derived while constructing the latent world.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import random
from typing import Any

VERSION = '0.1.0'
LABELS = ['billing', 'access', 'usage', 'cancellation']
ALIASES = {'payment': 'billing', 'invoice': 'billing', 'login': 'access', 'sign-in': 'access',
           'quota': 'usage', 'limits': 'usage', 'closure': 'cancellation', 'cancel': 'cancellation'}
FAMILIES = {
    'clean': [],
    'labels': ['labels'], 'duplicates': ['duplicates'], 'permissions': ['permissions'],
    'leakage': ['leakage'], 'versions': ['versions'],
    'pair': ['labels', 'duplicates'],
    'composition': ['labels', 'duplicates', 'permissions', 'leakage', 'versions'],
    'policy_shift': ['labels', 'duplicates', 'permissions', 'leakage', 'versions'],
}

def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

def generate_task(seed: int, family: str = 'composition', groups: int = 6) -> dict:
    """Create a latent truth, then project candidate rows and imperfect source events.

    At least three groups are eligible; equivalent copies are interchangeable.
    Equivalent copies in a lineage are interchangeable: any one may be retained.
    Task policies choose the source authority and time cutoff, rather than assuming
    that the most recent event or an input label is always correct.
    """
    if family not in FAMILIES: raise ValueError(f'Unknown family: {family}')
    if not 5 <= groups <= 12: raise ValueError('groups must be between 5 and 12')
    if family == 'policy_shift':
        # A paired counterfactual: identical records and source events, a different
        # authority contract, and the corresponding independently stored world truth.
        task = generate_task(seed, 'composition', groups)
        task['public']['id'] = f'policy_shift-{seed}'
        task['public']['family'] = family
        task['public']['contract']['authority'] = 'human_review'
        task['public']['contract']['rules'] = [r.replace('case_resolution', 'human_review') for r in task['public']['contract']['rules']]
        for row in task['private']['rows'].values():
            policy = task['private']['policy_truth'][row['lineage_id']]['human_review']
            row['label'], row['event_id'] = policy['label'], policy['event_id']
        for lineage, group in task['private']['eligible_groups'].items():
            policy = task['private']['policy_truth'][lineage]['human_review']
            group['label'], group['event_id'] = policy['label'], policy['event_id']
        task['fingerprint'] = digest(task['public'])
        return task
    rng = random.Random(f'latent-curation-v1:{seed}:{family}:{groups}')
    defects = FAMILIES[family]
    cutoff = rng.randint(50, 80)
    authority, other_authority = 'case_resolution', 'human_review'
    allocated = set()
    def opaque(prefix):
        value = f'{prefix}-{rng.getrandbits(40):010x}'
        while value in allocated: value = f'{prefix}-{rng.getrandbits(40):010x}'
        allocated.add(value)
        return value
    permission_group, evaluation_group = rng.sample(range(groups), 2)
    duplicate_groups = set(rng.sample(range(groups), 3))
    eligible_indices = [g for g in range(groups)
        if not ('permissions' in defects and g == permission_group)
        and not ('leakage' in defects and g == evaluation_group)]
    shuffled_labels = LABELS[:]; rng.shuffle(shuffled_labels)
    label_by_group = {g: rng.choice(LABELS) for g in range(groups)}
    for index, g in enumerate(eligible_indices): label_by_group[g] = shuffled_labels[index % len(LABELS)]
    candidates, registry, events, evaluation = [], [], [], []
    truth = {'eligible_groups': {}, 'rows': {}, 'policy_truth': {}}
    aliases_for = {label: [k for k, v in ALIASES.items() if v == label] for label in LABELS}
    def render_label(label): return rng.choice([label] + aliases_for[label])
    for g in range(groups):
        lineage = opaque('lineage')
        canonical = opaque('case')
        label = label_by_group[g]
        permitted = not ('permissions' in defects and g == permission_group)
        leaked = 'leakage' in defects and g == evaluation_group
        old_label = rng.choice([l for l in LABELS if l != label])
        chosen_event_id = opaque('event')
        chosen_time = cutoff - rng.randint(2, 8)
        chosen = dict(id=chosen_event_id, case_id=canonical, authority=authority,
                      revision=chosen_time, status='approved', category=render_label(label))
        events.append(chosen)
        # Always include a competing authority. It can be newer and disagree.
        alternate_event_id = opaque('event')
        events.append(dict(id=alternate_event_id, case_id=canonical, authority=other_authority,
                           revision=cutoff - rng.randint(1, 9), status='approved', category=render_label(old_label)))
        truth['policy_truth'][lineage] = {
            authority: {'label': label, 'event_id': chosen_event_id},
            other_authority: {'label': old_label, 'event_id': alternate_event_id},
        }
        if 'versions' in defects:
            events.extend([
                dict(id=opaque('event'), case_id=canonical, authority=authority,
                     revision=chosen_time - rng.randint(5, 20), status='approved', category=render_label(old_label)),
                dict(id=opaque('event'), case_id=canonical, authority=authority,
                     revision=cutoff + rng.randint(1, 10), status='approved', category=render_label(rng.choice(LABELS))),
                dict(id=opaque('event'), case_id=canonical, authority=authority,
                     revision=cutoff - rng.randint(1, 9), status='draft', category=render_label(rng.choice(LABELS))),
            ])
        if leaked:
            evaluation.append(dict(id=opaque('eval'), lineage_id=lineage,
                                   note='An evaluation example from this document family is reserved.'))
        copies = 2 if 'duplicates' in defects and g in duplicate_groups else 1
        if permitted and not leaked:
            truth['eligible_groups'][lineage] = {'label': label, 'event_id': chosen_event_id, 'row_ids': []}
        for c in range(copies):
            row_id = opaque('row')
            alias = opaque('ticket')
            registry_id = opaque('registry')
            registry.append(dict(id=registry_id, ticket_id=alias, case_id=canonical,
                                 lineage_id=lineage, training_allowed=permitted))
            # Contents are deliberately not a label oracle. Routing comes from the resolution record.
            texts = ['Please review my account request.', 'Following up on the issue in my previous message.',
                     'Can you help resolve this account issue?', 'I need assistance with the request I opened.']
            text = texts[g % len(texts)]
            if c: text = text.replace(' ', '  ').lower() + '  '
            initial_label = old_label if ('labels' in defects or 'versions' in defects) and g % 2 == 0 else label
            if g % 2 and 'labels' in defects: initial_label = rng.choice(aliases_for[label])
            candidates.append(dict(id=row_id, ticket_id=alias, text=text, label=initial_label))
            truth['rows'][row_id] = dict(lineage_id=lineage, label=label,
                permitted=permitted, leaked=leaked, eligible=permitted and not leaked,
                event_id=chosen_event_id, registry_id=registry_id)
            if permitted and not leaked: truth['eligible_groups'][lineage]['row_ids'].append(row_id)
    rng.shuffle(candidates); rng.shuffle(registry); rng.shuffle(events); rng.shuffle(evaluation)
    public = {
        'id': f'{family}-{seed}', 'family': family, 'seed': seed,
        'contract': {
            'goal': 'Prepare a training dataset for a customer-request routing model.',
            'authority': authority, 'cutoff_revision': cutoff,
            'labels': LABELS, 'aliases': ALIASES,
            'rules': [
                'Only keep rows whose registry entry permits training.',
                'Exclude every row whose lineage appears in the evaluation index, even when its text differs.',
                'Keep exactly one row for EVERY eligible lineage. Equivalent copies are interchangeable.',
                f'Use the latest approved {authority} event at or before revision {cutoff}. Ignore other authorities, drafts, and later revisions.',
                'Normalize categories using the label aliases. Do not infer labels from the text.',
                'Every changed label must cite the selected source event, which you must have inspected.',
                'Do not change original text, IDs, or the source tables.',
            ],
        },
        'candidates': candidates,
        'tables': {'registry': registry, 'events': events, 'evaluation': evaluation},
    }
    return {'public': public, 'private': truth, 'fingerprint': digest(public)}

def solve_visible(public: dict) -> dict:
    """Reference join policy. Reads no private key; accepts any equivalent representative."""
    contract = public['contract']
    registry = {r['ticket_id']: r for r in public['tables']['registry']}
    eval_groups = {r['lineage_id'] for r in public['tables']['evaluation']}
    answer, seen = {}, set()
    for row in public['candidates']:
        reg = registry[row['ticket_id']]
        if not reg['training_allowed']: answer[row['id']] = {'keep': False, 'reason': 'permission'}; continue
        if reg['lineage_id'] in eval_groups: answer[row['id']] = {'keep': False, 'reason': 'evaluation_overlap'}; continue
        if reg['lineage_id'] in seen: answer[row['id']] = {'keep': False, 'reason': 'duplicate'}; continue
        choices = [e for e in public['tables']['events'] if e['case_id'] == reg['case_id']
                   and e['authority'] == contract['authority'] and e['status'] == 'approved'
                   and e['revision'] <= contract['cutoff_revision']]
        selected = max(choices, key=lambda e: e['revision'])
        label = contract['aliases'].get(selected['category'], selected['category'])
        answer[row['id']] = {'keep': True, 'label': label, 'evidence_id': selected['id']}
        seen.add(reg['lineage_id'])
    return answer

def grade(task: dict, rows: list[dict], inspected: set[str]) -> dict:
    """Independent outcome grader over immutable row identity and latent truth.

    A policy can choose any representative of an eligible lineage. Only label edits
    require citations. Cleanliness cannot be improved by deleting all useful data.
    """
    truth = task['private']; original = {r['id']: r for r in task['public']['candidates']}
    kept = [r for r in rows if r['keep']]
    counts, violations, correct = {}, [], 0
    unsupported = []
    for r in kept:
        t = truth['rows'][r['id']]
        counts[t['lineage_id']] = counts.get(t['lineage_id'], 0) + 1
        if not t['permitted']: violations.append({'id': r['id'], 'type': 'permission'})
        if t['leaked']: violations.append({'id': r['id'], 'type': 'evaluation_overlap'})
        if r['label'] == t['label']: correct += 1
        if r['label'] != original[r['id']]['label']:
            if r.get('evidence_id') != t['event_id'] or t['event_id'] not in inspected:
                unsupported.append(r['id'])
    required = set(truth['eligible_groups'])
    covered = required.intersection(counts)
    coverage = len(covered) / len(required)
    accuracy = correct / len(kept) if kept else 0.0
    duplicates = [g for g, n in counts.items() if n > 1]
    safe = not violations
    unique = not duplicates
    provenance = not unsupported
    reward = coverage * accuracy * int(safe) * int(unique) * int(provenance)
    exact = bool(kept) and reward == 1.0
    return {'reward': reward, 'success': exact, 'coverage': coverage, 'label_accuracy': accuracy,
            'safe': safe, 'unique': unique, 'provenance': provenance,
            'kept_rows': len(kept), 'required_lineages': len(required), 'covered_lineages': len(covered),
            'violations': violations, 'duplicate_lineages': duplicates, 'unsupported_edits': unsupported}

def _schema(properties, required=()):
    return {'type': 'object', 'properties': properties, 'required': list(required), 'additionalProperties': False}

def _strings(description):
    return {'type': 'array', 'items': {'type': 'string'}, 'minItems': 1, 'maxItems': 20, 'description': description}

TOOLS = [
    {'name': 'inspect', 'description': 'Read candidate rows. Empty args uses offset 0 and limit 20.',
     'input_schema': _schema({'offset': {'type': 'integer', 'minimum': 0, 'default': 0},
                             'limit': {'type': 'integer', 'minimum': 1, 'maximum': 20, 'default': 20}})},
    {'name': 'lookup', 'description': 'Read registry by ticket_id, events by case_id, or evaluation by lineage_id. Empty matches mean no entry.',
     'input_schema': _schema({'table': {'type': 'string', 'enum': ['registry', 'events', 'evaluation']},
                             'keys': _strings('Copy exact ticket IDs, case IDs, or lineage IDs from observations.')}, ['table', 'keys'])},
    {'name': 'repair', 'description': 'Change labels. Cite an inspected source event. A citation alone does not guarantee correctness.',
     'input_schema': _schema({'updates': {'type': 'array', 'minItems': 1, 'maxItems': 20,
          'items': {'type': 'object', 'properties': {'id': {'type': 'string'},
                    'label': {'type': 'string', 'enum': LABELS}, 'evidence_id': {'type': 'string'}},
                    'required': ['id', 'label', 'evidence_id']}}}, ['updates'])},
    {'name': 'exclude', 'description': 'Remove rows. Preserve one representative of every eligible lineage.',
     'input_schema': _schema({'ids': _strings('Row IDs to exclude.'),
                             'reason': {'type': 'string', 'enum': ['permission', 'evaluation_overlap', 'duplicate', 'other']}}, ['ids', 'reason'])},
    {'name': 'restore', 'description': 'Undo exclusions. Labels remain as last edited.',
     'input_schema': _schema({'ids': _strings('Row IDs to restore.')}, ['ids'])},
    {'name': 'check', 'description': 'Check public output shape and counts. Does not reveal private expected labels or grade.',
     'input_schema': _schema({})},
    {'name': 'submit', 'description': 'Freeze the dataset, end the episode, and receive the final outcome grade.',
     'input_schema': _schema({})},
]

class CurationEnv:
    def __init__(self, task: dict | None = None, max_steps: int = 18):
        if max_steps < 1: raise ValueError('max_steps must be positive')
        self.task = deepcopy(task) if task is not None else generate_task(0)
        self.max_steps = max_steps
        self.reset()

    def reset(self) -> dict:
        self.rows = [dict(r, keep=True, evidence_id=None, exclusion_reason=None) for r in self.task['public']['candidates']]
        self.inspected = set(); self.history = []; self.steps = 0; self.done = False; self.result = None
        self._fingerprint = digest(self.task['public'])
        return {'task_id': self.task['public']['id'], 'contract': deepcopy(self.task['public']['contract']),
                'candidate_count': len(self.rows), 'tools': deepcopy(TOOLS), 'max_steps': self.max_steps,
                'observation': 'Use inspect to read candidate rows, then lookup to inspect their sources.', 'reward': 0.0, 'done': False}

    def step(self, action: dict) -> dict:
        if self.done: raise RuntimeError('Episode ended. Call reset() before taking another action.')
        if digest(self.task['public']) != self._fingerprint: raise RuntimeError('Source fixture was mutated')
        self.steps += 1
        before = digest(self.rows)
        try:
            if not isinstance(action, dict): raise ValueError('Action must be a JSON object')
            name = action.get('tool'); args = action.get('args', {})
            if not isinstance(args, dict): raise ValueError('args must be an object')
            observation = self._act(name, args)
            error = None
        except (ValueError, KeyError, TypeError) as exc:
            observation = {'error': str(exc)}; error = type(exc).__name__
        if self.steps >= self.max_steps and not self.done:
            self.done = True
            self.result = {'reward': 0.0, 'success': False, 'termination': 'budget_exhausted'}
        out = {'observation': observation, 'reward': self.result['reward'] if self.done else 0.0,
               'done': self.done, 'steps': self.steps, 'remaining_steps': max(0, self.max_steps - self.steps)}
        if self.done: out['result'] = deepcopy(self.result)
        self.history.append({'step': self.steps, 'action': deepcopy(action), 'response': deepcopy(out),
                             'state_before': before, 'state_after': digest(self.rows), 'error': error})
        return out

    def _ids(self, ids):
        if not isinstance(ids, list) or not ids or len(ids) > 20 or any(not isinstance(i, str) for i in ids):
            raise ValueError('ids must contain 1–20 row IDs')
        rows = {r['id']: r for r in self.rows}
        if any(i not in rows for i in ids): raise ValueError('Unknown row ID; no changes applied')
        return [rows[i] for i in ids]

    def _act(self, name, args):
        definition = next((t for t in TOOLS if t['name'] == name), None)
        if definition is None: raise ValueError('Unknown tool. Read the available tool definitions.')
        if set(args) - set(definition['input_schema']['properties']): raise ValueError('Unknown argument for this tool')
        if name == 'inspect':
            offset, limit = args.get('offset', 0), args.get('limit', 20)
            if type(offset) is not int or type(limit) is not int or offset < 0 or not 1 <= limit <= 20:
                raise ValueError('offset must be nonnegative; limit must be 1–20')
            return {'rows': deepcopy(self.rows[offset:offset + limit]), 'total': len(self.rows)}
        if name == 'lookup':
            table, keys = args.get('table'), args.get('keys')
            if table not in self.task['public']['tables']: raise ValueError('Unknown source table')
            if not isinstance(keys, list) or not keys or len(keys) > 20 or any(not isinstance(k, str) for k in keys):
                raise ValueError('keys must contain 1–20 strings')
            key_field = {'registry': 'ticket_id', 'events': 'case_id', 'evaluation': 'lineage_id'}[table]
            found = [r for r in self.task['public']['tables'][table] if r[key_field] in keys]
            self.inspected.update(r['id'] for r in found)
            return {'table': table, 'records': deepcopy(found), 'keys_without_matches': [k for k in keys if not any(r[key_field] == k for r in found)]}
        if name == 'repair':
            updates = args.get('updates')
            if not isinstance(updates, list) or not updates or len(updates) > 20: raise ValueError('updates must contain 1–20 edits')
            if any(not isinstance(u, dict) for u in updates): raise ValueError('Each edit must be an object')
            rows = self._ids([u.get('id') for u in updates])
            if len({u['id'] for u in updates}) != len(updates): raise ValueError('Duplicate row IDs in updates')
            for u in updates:
                if u.get('label') not in LABELS: raise ValueError('Use a canonical label from the contract')
                if not isinstance(u.get('evidence_id'), str) or u['evidence_id'] not in self.inspected:
                    raise ValueError('Inspect the cited source event before using it; no changes applied')
            for row, u in zip(rows, updates): row['label'] = u['label']; row['evidence_id'] = u['evidence_id']
            return {'edited': [u['id'] for u in updates]}
        if name in ['exclude', 'restore']:
            rows = self._ids(args.get('ids'))
            reason = args.get('reason')
            if name == 'exclude' and reason not in ['permission', 'evaluation_overlap', 'duplicate', 'other']:
                raise ValueError('Unknown exclusion reason')
            for row in rows: row['keep'] = name == 'restore'; row['exclusion_reason'] = reason if name == 'exclude' else None
            return {'updated': [r['id'] for r in rows]}
        if name == 'check':
            kept = [r for r in self.rows if r['keep']]
            return {'kept_rows': len(kept), 'excluded_rows': len(self.rows) - len(kept),
                    'noncanonical_labels': [r['id'] for r in kept if r['label'] not in LABELS],
                    'note': 'Only public structural checks. Correct labels, eligible lineage coverage, and source validity are graded on submit.'}
        if name == 'submit':
            self.done = True
            self.result = dict(grade(self.task, self.rows, self.inspected), termination='submitted')
            return {'dataset': self.export_dataset(), 'manifest': self.export_manifest()}
        raise ValueError('Unknown tool. Read the available tool definitions.')

    def export_dataset(self):
        return [{'id': r['id'], 'text': r['text'], 'label': r['label'], 'evidence_id': r['evidence_id']}
                for r in self.rows if r['keep']]

    def export_manifest(self):
        return {'environment_version': VERSION, 'task_id': self.task['public']['id'],
                'source_sha256': self._fingerprint, 'dataset_sha256': digest(self.export_dataset()),
                'rows': len(self.export_dataset()), 'steps': self.steps, 'done': self.done}

    def export_trajectory(self):
        return {'task_id': self.task['public']['id'], 'source_sha256': self._fingerprint,
                'max_steps': self.max_steps, 'steps': deepcopy(self.history), 'result': deepcopy(self.result),
                'dataset': self.export_dataset(), 'manifest': self.export_manifest()}

def run_reference(env: CurationEnv):
    """Execute the visible-data solver through the same permitted tools as a model."""
    env.reset(); public = env.task['public']
    rows = env.step({'tool': 'inspect'})['observation']['rows']
    regs = env.step({'tool': 'lookup', 'args': {'table': 'registry', 'keys': [r['ticket_id'] for r in rows]}})['observation']['records']
    env.step({'tool': 'lookup', 'args': {'table': 'evaluation', 'keys': list(dict.fromkeys(r['lineage_id'] for r in regs))}})
    env.step({'tool': 'lookup', 'args': {'table': 'events', 'keys': list(dict.fromkeys(r['case_id'] for r in regs))}})
    answer = solve_visible(public)
    for reason in ['permission', 'evaluation_overlap', 'duplicate']:
        ids = [i for i, a in answer.items() if not a['keep'] and a['reason'] == reason]
        if ids: env.step({'tool': 'exclude', 'args': {'ids': ids, 'reason': reason}})
    originals = {r['id']: r for r in public['candidates']}
    updates = [dict(id=i, label=a['label'], evidence_id=a['evidence_id']) for i, a in answer.items()
               if a['keep'] and a['label'] != originals[i]['label']]
    if updates: env.step({'tool': 'repair', 'args': {'updates': updates}})
    env.step({'tool': 'submit'})
    return env.export_trajectory()
