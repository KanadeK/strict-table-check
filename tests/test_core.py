import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from strict_table_check.core import audit


class StrictTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / (
            "source # 雪.sqlite" if os.name == "nt" else "source #? 雪.sqlite"
        )

    def make(self, schema="CREATE TABLE t(v)", rows=()):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.executescript(schema)
            if rows:
                db.executemany("INSERT INTO t VALUES (?)", [(v,) for v in rows])

    def test_rejection_and_conversion_are_distinct(self):
        self.make(rows=["005", "not-a-number", 8, None, b"8", 1.2, 2.0])
        result = audit(self.path, "t", {"v": "INTEGER"})
        self.assertTrue(result["complete"])
        self.assertFalse(result["ok"])
        self.assertEqual(result["rejected_cells"], 3)
        self.assertEqual(result["converted_cells"], 2)
        self.assertEqual(result["rows_scanned"], 7)

    def test_engine_differential_all_target_types(self):
        values = [None, 0, -(2**63), 2**63 - 1, 1.5, 2.0, "1e2", "1.2", " x", "", b"x"]
        self.make(rows=values)
        for target in ["INT", "INTEGER", "TEXT", "REAL", "BLOB", "ANY"]:
            with self.subTest(target=target), closing(sqlite3.connect(":memory:")) as ref:
                ref.execute(f"CREATE TABLE reference (v {target}) STRICT")
                rejected = 0
                for value in values:
                    try:
                        ref.execute("INSERT INTO reference VALUES (?)", (value,))
                    except sqlite3.IntegrityError:
                        rejected += 1
                self.assertEqual(audit(self.path, "t", {"v": target})["rejected_cells"], rejected)

    def test_any_preserves_values(self):
        self.make(rows=["0001", b"bytes", 1.5, 8, None])
        r = audit(self.path, "t", {"v": "ANY"})
        self.assertTrue(r["ok"])
        self.assertEqual(r["converted_cells"], 0)

    def test_values_redacted_by_default(self):
        self.make(rows=["PRIVATE_MARKER"])
        self.assertNotIn("PRIVATE_MARKER", json.dumps(audit(self.path, "t", {"v": "INTEGER"})))

    def test_explicit_values_are_typed(self):
        self.make(rows=[b"secret", "005"])
        r = audit(self.path, "t", {"v": "INTEGER"}, include_values=True)
        self.assertEqual(r["samples"][0]["source"], {"type": "blob", "base64": "c2VjcmV0"})
        self.assertEqual(r["samples"][1]["result"], {"type": "integer", "value": 5})

    def test_row_limit_never_passes_partial_scan(self):
        self.make(rows=[1, 2, 3])
        r = audit(self.path, "t", {"v": "ANY"}, max_rows=2)
        self.assertFalse(r["complete"])
        self.assertFalse(r["ok"])
        self.assertEqual(r["rows_scanned"], 2)
        self.assertTrue(audit(self.path, "t", {"v": "ANY"}, max_rows=3)["complete"])

    def test_sample_cap_does_not_cap_counts(self):
        self.make(rows=["bad"] * 40)
        r = audit(self.path, "t", {"v": "INT"}, max_samples=2)
        self.assertEqual(r["rejected_cells"], 40)
        self.assertEqual(len(r["samples"]), 2)
        self.assertEqual(audit(self.path, "t", {"v": "INT"}, max_samples=0)["samples"], [])

    def test_declared_types_and_empty_table(self):
        self.make("CREATE TABLE t(id INTEGER, v TEXT)")
        self.assertTrue(audit(self.path, "t")["ok"])

    def test_unsupported_declared_type_requires_mapping(self):
        self.make("CREATE TABLE t(v VARCHAR(10))")
        with self.assertRaises(ValueError):
            audit(self.path, "t")
        self.assertTrue(audit(self.path, "t", {"v": "TEXT"})["ok"])

    def test_bad_override_rejected(self):
        self.make()
        for mapping in [{"wrong": "INT"}, {"v": "NUMERIC"}, {"v": "INT);DROP TABLE t;--"}]:
            with self.subTest(mapping=mapping), self.assertRaises(ValueError):
                audit(self.path, "t", mapping)

    def test_quoted_identifiers(self):
        self.make('CREATE TABLE "t;--" ("v""q" TEXT); INSERT INTO "t;--" VALUES (\'9\')')
        self.assertEqual(audit(self.path, "t;--", {'v"q': "INT"})["converted_cells"], 1)

    def test_without_rowid(self):
        self.make("CREATE TABLE t(v TEXT PRIMARY KEY) WITHOUT ROWID", ["005", "bad"])
        self.assertEqual(audit(self.path, "t", {"v": "INT"})["rejected_cells"], 1)

    def test_generated_and_view_explicitly_unsupported(self):
        self.make("CREATE TABLE t(v INT, g INT AS (v+1)); CREATE VIEW x AS SELECT * FROM t")
        for table in ["t", "x", "missing", "sqlite_schema"]:
            with self.subTest(table=table), self.assertRaises(ValueError):
                audit(self.path, table)

    def test_source_unchanged_and_no_trigger_execution(self):
        self.make(
            "CREATE TABLE t(v INT); CREATE TABLE log(x); "
            "CREATE TRIGGER tr AFTER INSERT ON t BEGIN INSERT INTO log VALUES (1); END;",
            [8],
        )
        before = hashlib.sha256(self.path.read_bytes()).hexdigest()
        self.assertTrue(audit(self.path, "t")["ok"])
        self.assertEqual(before, hashlib.sha256(self.path.read_bytes()).hexdigest())
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM log").fetchone()[0], 1)

    def test_live_wal_reads_committed_rows(self):
        db = sqlite3.connect(self.path)
        self.addCleanup(db.close)
        db.executescript(
            "PRAGMA journal_mode=WAL; PRAGMA wal_autocheckpoint=0; CREATE TABLE t(v INT)"
        )
        db.execute("INSERT INTO t VALUES ('bad')")
        db.commit()
        self.assertTrue(Path(str(self.path) + "-wal").exists())
        self.assertEqual(audit(self.path, "t")["rejected_cells"], 1)

    def test_missing_is_not_created(self):
        with self.assertRaises(FileNotFoundError):
            audit(self.path, "t")
        self.assertFalse(self.path.exists())

    def test_corrupt_db_incomplete(self):
        self.path.write_bytes(b"not a database")
        self.assertFalse(audit(self.path, "t")["complete"])

    def test_limits_and_infinity(self):
        self.make()
        for kwargs in [
            {"max_rows": 0},
            {"max_samples": -1},
            {"max_seconds": 0},
            {"max_seconds": float("nan")},
            {"max_seconds": float("inf")},
            {"max_value_bytes": 10},
        ]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                audit(self.path, "t", {"v": "ANY"}, **kwargs)

    def test_large_value_incomplete(self):
        self.make(rows=["a" * 3000])
        self.assertFalse(audit(self.path, "t", {"v": "ANY"}, max_value_bytes=1024)["complete"])

    def test_time_budget_incomplete(self):
        self.make(rows=list(range(50)))
        with patch("strict_table_check.core.time.perf_counter", side_effect=[0] + [31] * 1000):
            self.assertFalse(audit(self.path, "t", {"v": "ANY"}, max_seconds=30)["complete"])

    def test_nonfinite_json_is_valid(self):
        self.make(rows=[float("inf")])
        r = audit(self.path, "t", {"v": "INT"}, include_values=True)
        self.assertIn('"inf"', json.dumps(r, allow_nan=False))

    def test_cli_complete_failure_conversion_and_usage(self):
        self.make("CREATE TABLE t(v TEXT)", ["005"])
        base = [sys.executable, "-m", "strict_table_check", str(self.path), "t", "--format", "json"]
        for extra, code in [
            ([], 0),
            (["--type", "v=INT"], 0),
            (["--type", "v=INT", "--fail-on-conversion"], 1),
            (["--type", "v=oops"], 2),
            (["--type", "v=INT", "--type", "v=TEXT"], 2),
        ]:
            with self.subTest(extra=extra):
                p = subprocess.run(base + extra, capture_output=True, text=True, check=False)
                self.assertEqual(p.returncode, code, p.stderr + p.stdout)
                self.assertIsInstance(json.loads(p.stdout), dict)


if __name__ == "__main__":
    unittest.main()
