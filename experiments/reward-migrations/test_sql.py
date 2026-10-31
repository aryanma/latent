import sqlite3
import tempfile
from pathlib import Path
import unittest

from latent_migration.sql import execute, reward


class SQLTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.db = Path(self.directory.name) / "test.sqlite"
        with sqlite3.connect(self.db) as conn:
            conn.executescript("CREATE TABLE t (id INTEGER, value TEXT); INSERT INTO t VALUES (1, 'a'), (2, 'b'), (2, 'b');")

    def tearDown(self):
        self.directory.cleanup()

    def test_bird_set_semantics_ignore_duplicates_order_and_int_float_types(self):
        a = execute(self.db, "SELECT id FROM t ORDER BY id DESC")
        b = execute(self.db, "SELECT DISTINCT CAST(id AS REAL) FROM t ORDER BY id ASC")
        self.assertEqual(reward(a, b), 1)
        self.assertEqual((a["rows"], a["distinct_rows"]), (3, 2))

    def test_null_blob_and_empty_results_are_unambiguous(self):
        a = execute(self.db, "SELECT NULL, X'01' FROM t LIMIT 1")
        b = execute(self.db, "SELECT NULL, X'01' FROM t LIMIT 1")
        c = execute(self.db, "SELECT NULL, X'02' FROM t LIMIT 1")
        self.assertEqual(reward(a, b), 1)
        self.assertEqual(reward(a, c), 0)
        self.assertEqual(reward(execute(self.db, "SELECT id FROM t WHERE 0"),
                                execute(self.db, "SELECT value FROM t WHERE 0")), 1)
        self.assertEqual(reward(execute(self.db, "SELECT 1e999"), execute(self.db, "SELECT 1e1000")), 1)
        self.assertEqual(reward(execute(self.db, "SELECT 1e999"), execute(self.db, "SELECT -1e999")), 0)

    def test_writes_and_environment_access_are_refused(self):
        for sql in ("DELETE FROM t", "ATTACH ':memory:' AS another", "PRAGMA user_version=8",
                    "SELECT load_extension('absent')", "SELECT random()", "SELECT datetime('now', 'localtime')"):
            with self.subTest(sql=sql):
                result = execute(self.db, sql)
                self.assertEqual(result["status"], "unsupported")
        self.assertEqual(execute(self.db, "SELECT COUNT(*) FROM t")["preview"], [[3]])

    def test_clock_covers_keywords_implicit_now_and_runtime_constructed_now(self):
        cases = {"CURRENT_TIMESTAMP": "2026-10-31 00:00:00", "CURRENT_DATE": "2026-10-31",
                 "CURRENT_TIME": "00:00:00", "datetime()": "2026-10-31 00:00:00",
                 "date(char(110,111,119))": "2026-10-31", "strftime('%Y')": "2026",
                 "strftime('%Y', 'NOW')": "2026", "date(NULL)": None,
                 "strftime()": None, "date('2000-02-28', '+1 day')": "2000-02-29"}
        for expression, expected in cases.items():
            with self.subTest(expression=expression):
                self.assertEqual(execute(self.db, "SELECT " + expression)["preview"], [[expected]])
        self.assertEqual(execute(self.db, "SELECT CURRENT_DATE", clock="2001-02-03 04:05:06")["preview"], [["2001-02-03"]])
        self.assertEqual(execute(self.db, "SELECT date('now', 'local'||'time')")["status"], "unsupported")

    def test_limits_are_unknown_not_negative_labels(self):
        limited = execute(self.db, "SELECT * FROM t", max_rows=1)
        ref = execute(self.db, "SELECT * FROM t")
        self.assertEqual(limited["status"], "limit")
        self.assertIsNone(reward(limited, ref))
        slow = execute(self.db, "WITH RECURSIVE seq(x) AS (SELECT 0 UNION ALL SELECT x+1 FROM seq) SELECT sum(x) FROM seq", timeout=.01)
        self.assertEqual(slow["status"], "timeout")
        self.assertIsNone(reward(ref, slow))
        invalid = execute(self.db, "SELECT absent_column FROM t")
        self.assertEqual(reward(invalid, ref), 0)


if __name__ == "__main__":
    unittest.main()
