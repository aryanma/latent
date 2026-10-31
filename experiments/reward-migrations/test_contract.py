from dataclasses import replace
import unittest

from latent_migration.contract import Contract, digest, invalidated, plan


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.base = Contract("example:42", *[digest(x) for x in ("prompt", "world", "tools", "reward")], True, True,
                             policy=digest("weights, sampling, and harness"))

    def test_reward_only_is_regrade_but_feedback_requires_rerun(self):
        updated = replace(self.base, grader=digest("new reward"))
        self.assertEqual(plan(self.base, updated)["action"], "regrade")
        self.assertEqual(plan(replace(self.base, terminal_private_reward=False),
                              replace(updated, terminal_private_reward=False))["action"], "rerun")
        self.assertEqual(plan(self.base, replace(self.base, terminal_private_reward=False))["action"], "rerun")

    def test_same_task_name_cannot_hide_changed_context_or_world(self):
        for field in ("observation", "world", "interface", "policy"):
            with self.subTest(field=field):
                self.assertEqual(plan(self.base, replace(self.base, **{field: digest("changed")}))["action"], "rerun")

    def test_unobserved_world_change_can_reexecute_a_single_action(self):
        before = replace(self.base, world_visible_to_policy=False)
        after = replace(before, world=digest("new database rows"))
        self.assertEqual(plan(before, after)["action"], "reexecute")
        self.assertEqual(plan(before, replace(after, observation=digest("tool result from new rows")))["action"], "rerun")

    def test_unknown_provenance_never_certifies_reuse(self):
        for modified in (replace(self.base, world=""), replace(self.base, lineage_verified=False),
                         replace(self.base, task="other:42")):
            self.assertEqual(plan(self.base, modified)["action"], "review")
        self.assertEqual(plan(self.base, self.base)["action"], "reuse")

    def test_strict_json_types(self):
        obj = self.base.to_dict()
        obj["lineage_verified"] = "false"
        with self.assertRaises(ValueError):
            Contract.from_dict(obj)
        with self.assertRaises(ValueError):
            replace(self.base, lineage_verified="false")

    def test_reward_change_reaches_unchanged_members_advantages(self):
        graph = {"r0": [], "r1": [], "r2": [], "group": ["r0", "r1", "r2"],
                 "a0": ["group"], "a1": ["group"], "a2": ["group"],
                 "selected": ["r0", "r1", "r2"], "independent": []}
        self.assertEqual(invalidated(graph, ["r0"]), ["a0", "a1", "a2", "group", "r0", "selected"])
        with self.assertRaises(ValueError):
            invalidated({"a": ["b"], "b": ["a"]}, ["a"])
        with self.assertRaises(ValueError):
            invalidated({"a": ["missing"]}, ["a"])


if __name__ == "__main__":
    unittest.main()
