import copy
import unittest
from latent_curation.environment import CurationEnv, FAMILIES, generate_task, grade, run_reference, solve_visible

class EnvironmentTests(unittest.TestCase):
    def test_visible_reference_matches_independent_truth_across_worlds(self):
        for family in FAMILIES:
            for seed in range(40):
                env = CurationEnv(generate_task(seed, family, groups=5 + seed % 8))
                trace = run_reference(env)
                self.assertTrue(trace['result']['success'], (family, seed, trace['result']))
                self.assertEqual(trace['result']['reward'], 1)

    def test_delete_everything_never_wins(self):
        env = CurationEnv()
        env.step({'tool':'exclude','args':{'ids':[r['id'] for r in env.rows],'reason':'other'}})
        result = env.step({'tool':'submit'})['result']
        self.assertEqual(result['coverage'], 0)
        self.assertEqual(result['reward'], 0)

    def test_keep_all_fails_composed_task_but_passes_clean_task(self):
        self.assertEqual(CurationEnv().step({'tool':'submit'})['reward'], 0)
        self.assertEqual(CurationEnv(generate_task(42, 'clean')).step({'tool':'submit'})['reward'], 1)

    def test_equivalent_duplicate_representatives_are_accepted(self):
        task = generate_task(3)
        reference = run_reference(CurationEnv(task))
        env = CurationEnv(task)
        run_reference(env)
        for group in task['private']['eligible_groups'].values():
            if len(group['row_ids']) > 1:
                first, second = [r for r in env.rows if r['id'] in group['row_ids']]
                first['keep'], second['keep'] = second['keep'], first['keep']
                first['label'] = second['label'] = group['label']
                first['evidence_id'] = second['evidence_id'] = group['event_id']
        self.assertEqual(grade(task, env.rows, env.inspected)['reward'], reference['result']['reward'])

    def test_existing_but_irrelevant_citation_does_not_pass(self):
        env = CurationEnv(generate_task(2, 'labels'))
        run_reference(env)
        row = next(r for r in env.rows if r['keep'] and r['evidence_id'])
        row['evidence_id'] = next(i for i in env.inspected if i != row['evidence_id'])
        self.assertFalse(grade(env.task, env.rows, env.inspected)['provenance'])
        self.assertEqual(grade(env.task, env.rows, env.inspected)['reward'], 0)

    def test_source_authority_time_and_draft_status_are_distinct(self):
        task = generate_task(12, 'policy_shift')
        answer = solve_visible(task['public'])
        events = {e['id']:e for e in task['public']['tables']['events']}
        for a in answer.values():
            if a['keep']:
                e = events[a['evidence_id']]
                self.assertEqual(e['authority'], 'human_review')
                self.assertEqual(e['status'], 'approved')
                self.assertLessEqual(e['revision'], task['public']['contract']['cutoff_revision'])

    def test_paired_policy_changes_answer_but_not_sources(self):
        a, b = generate_task(500, 'composition'), generate_task(500, 'policy_shift')
        self.assertEqual(a['public']['candidates'], b['public']['candidates'])
        self.assertEqual(a['public']['tables'], b['public']['tables'])
        for key, row in a['private']['rows'].items():
            self.assertNotEqual(row['label'], b['private']['rows'][key]['label'])

    def test_versions_family_requires_repairs(self):
        for seed in range(10):
            self.assertLess(CurationEnv(generate_task(seed,'versions')).step({'tool':'submit'})['reward'], 1)

    def test_bad_batch_is_atomic_and_consumes_step(self):
        env = CurationEnv(); before = copy.deepcopy(env.rows)
        out = env.step({'tool':'exclude','args':{'ids':[env.rows[0]['id'],'not-a-row'],'reason':'other'}})
        self.assertIn('error', out['observation'])
        self.assertEqual(env.rows, before)
        self.assertEqual(env.steps, 1)

    def test_public_check_does_not_expose_oracle(self):
        env = CurationEnv()
        obs = env.step({'tool':'check'})['observation']
        self.assertEqual(set(obs), {'kept_rows','excluded_rows','noncanonical_labels','note'})
        self.assertIsNone(env.result)

    def test_reset_and_terminal_freeze(self):
        env = CurationEnv(); initial = env.reset()
        env.step({'tool':'exclude','args':{'ids':[env.rows[0]['id']],'reason':'other'}})
        env.step({'tool':'submit'})
        with self.assertRaises(RuntimeError): env.step({'tool':'restore','args':{'ids':[env.rows[0]['id']]}})
        self.assertEqual(initial, env.reset())
        self.assertTrue(all(r['keep'] for r in env.rows))
        self.assertEqual(env.history, [])

    def test_budget_and_fixture_guard(self):
        env = CurationEnv(max_steps=1)
        out = env.step({'tool':'inspect'})
        self.assertTrue(out['done']); self.assertEqual(out['reward'], 0)
        self.assertEqual(out['result']['termination'], 'budget_exhausted')
        env.reset(); env.task['public']['candidates'][0]['text'] = 'tampered'
        with self.assertRaises(RuntimeError): env.step({'tool':'submit'})

if __name__ == '__main__': unittest.main()
