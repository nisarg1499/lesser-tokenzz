"""Test the news adapter mapping with synthetic rows and reviewed-source fixtures."""

import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from lesser_tokenzz.metric_contract import fingerprint, news_contracts


class NewsContractTests(unittest.TestCase):
    def test_uer_fraction_and_zero_duration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "news.sqlite"
            knowledge = root / "knowledge.jsonl"
            # Synthetic records exercise revision enforcement without shipping a KB.
            records = [
                {"id": key, "definition": "synthetic fixture"}
                for key in (0, 3, 52, 53, 54)
            ]
            revisions = {row["id"]: fingerprint(row) for row in records}
            knowledge.write_text("\n".join(json.dumps(row) for row in records))
            with sqlite3.connect(database) as conn:
                conn.execute(
                    "CREATE TABLE sessions (seshkey, bncrate, ctrval, seshviews, engscore, seshdur)"
                )
                conn.executemany(
                    "INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?)",
                    [(1, 10, 2, 3, 5, 2), (2, 10, 2, 3, 5, 0)],
                )
            with patch("lesser_tokenzz.metric_contract._NEWS_REVISIONS", revisions):
                contracts = news_contracts(database, knowledge)
                self.assertEqual(
                    contracts.metrics["user_engagement_rate"]["source_ids"], [0]
                )
                query = contracts.build_metric_query(
                    ["user_engagement_rate"], order_by=[{"column": "seshkey"}]
                )["sql"]
                with sqlite3.connect(database) as conn:
                    self.assertEqual(
                        conn.execute(query).fetchall(), [(1, 7.5), (2, None)]
                    )
                records[0]["definition"] = "changed without review"
                knowledge.write_text("\n".join(json.dumps(row) for row in records))
                with self.assertRaisesRegex(ValueError, "review required"):
                    contracts.get_metric_contracts()
