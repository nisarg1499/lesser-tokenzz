import sqlite3
import tempfile
from pathlib import Path
import unittest
from lesser_tokenzz.sql import run_sql


class SQLTests(unittest.TestCase):
    def test_read_only_and_truncation(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "demo.sqlite"
            with sqlite3.connect(db) as conn:
                conn.execute("CREATE TABLE items (value INTEGER)")
                conn.executemany("INSERT INTO items VALUES (?)", [(1,), (2,)])
            self.assertTrue(run_sql(db, "SELECT * FROM items", 1)["truncated"])
            for sql in [
                "DELETE FROM items",
                "ATTACH DATABASE ':memory:' AS other",
                "PRAGMA user_version=2",
            ]:
                with self.assertRaises(sqlite3.DatabaseError):
                    run_sql(db, sql)
