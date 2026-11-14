"""Synthetic execution tests; no benchmark fixtures or paid calls."""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from lesser_tokenzz.metric_contract import MetricContracts
from lesser_tokenzz.metric_executor import MetricExecutor
from test_metric_contract import fixture


class MetricExecutorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "fixture.sqlite"
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                "CREATE TABLE sessions(id INTEGER,country TEXT,bounce REAL,ctr REAL)"
            )
            conn.executemany(
                "INSERT INTO sessions VALUES(?,?,?,?)",
                [
                    (1, "US", 10, 0),
                    (2, "CA", 20, 0),
                    (3, "US", 30, 0),
                    (4, "US", 30, 0),
                    (5, "CA", 50, 0),
                ],
            )
        self.engine = MetricExecutor(MetricContracts(fixture()), self.path)

    def tearDown(self):
        self.temp.cleanup()

    def test_global_metrics_then_filters_then_summary(self):
        result = self.engine.execute(
            group_by=["country"],
            aggregates=[
                {"op": "avg", "column": "bounce_rank", "alias": "mean_rank"},
                {"op": "count", "alias": "n"},
            ],
            filters=[{"column": "country", "op": "eq", "value": "CA"}],
        )
        self.assertEqual(result["columns"], ["country", "mean_rank", "n"])
        self.assertEqual(result["rows"], [["CA", 0.625, 2]])
        self.assertFalse(result["row_cap_truncated"])

    def test_derived_filter_and_all_summary_ops(self):
        result = self.engine.execute(
            aggregates=[
                {"op": op, "column": "bounce", "alias": op}
                for op in ["count", "sum", "avg", "min", "max"]
            ],
            filters=[{"column": "bounce_rank", "op": "ge", "value": 0.5}],
        )
        self.assertEqual(result["rows"], [[3, 110.0, 110.0 / 3, 30.0, 50.0]])

    def test_group_by_derived_metric(self):
        result = self.engine.execute(
            group_by=["segment"],
            aggregates=[{"op": "count", "alias": "n"}],
            order_by=[{"column": "segment"}],
        )
        self.assertEqual(result["rows"], [["low", 1], ["other", 4]])

    def test_row_caps_and_order(self):
        result = self.engine.execute(
            columns=["id"], max_rows=2, order_by=[{"column": "id", "descending": True}]
        )
        self.assertEqual(result["rows"], [[5], [4]])
        self.assertTrue(result["row_cap_truncated"])
        self.assertEqual(result["source"], {"fixture": True})

    def test_cell_cap(self):
        result = self.engine.execute(columns=["id", "country"], max_cells=5)
        self.assertEqual(len(result["rows"]), 2)
        self.assertTrue(result["row_cap_truncated"])
        with self.assertRaises(ValueError):
            self.engine.execute(columns=["id", "country"], max_cells=1)

    def test_requested_limit_reported_separately(self):
        result = self.engine.execute(columns=["id"], limit=1, max_rows=3)
        self.assertEqual(len(result["rows"]), 1)
        self.assertFalse(result["row_cap_truncated"])
        self.assertTrue(result["requested_limit_may_omit_rows"])

    def test_string_truncation_is_explicit(self):
        result = self.engine.execute(columns=["country"], limit=1, max_cell_chars=1)
        self.assertEqual(result["truncated_cells"], [[0, 0]])
        self.assertEqual(len(result["rows"][0][0]), 1)

    def test_null_and_empty_aggregate(self):
        with sqlite3.connect(self.path) as conn:
            conn.execute("INSERT INTO sessions VALUES(6,NULL,NULL,NULL)")
        result = self.engine.execute(
            aggregates=[
                {"op": "count", "alias": "all"},
                {"op": "count", "column": "bounce", "alias": "nonnull"},
                {"op": "sum", "column": "bounce", "alias": "total"},
            ],
            filters=[{"column": "id", "op": "eq", "value": 6}],
        )
        self.assertEqual(result["rows"], [[1, 0, None]])
        result = self.engine.execute(
            aggregates=[{"op": "count", "alias": "all"}],
            filters=[{"column": "id", "op": "eq", "value": 99}],
        )
        self.assertEqual(result["rows"], [[0]])

    def test_no_fragments_or_ambiguous_options(self):
        bad = [
            dict(aggregates=[{"op": "count); DROP TABLE sessions; --", "alias": "n"}]),
            dict(aggregates=[{"op": "sum", "alias": "n"}]),
            dict(aggregates=[{"op": "count", "column": "*", "alias": "n"}]),
            dict(group_by=["country"]),
            dict(aggregates=[{"op": "count", "alias": "n"}], columns=["id"]),
            dict(
                aggregates=[
                    {"op": "count", "alias": "n"},
                    {"op": "count", "alias": "n"},
                ]
            ),
            dict(order_by=[{"column": "country"}], columns=["id"]),
            dict(max_rows=0),
            dict(timeout_seconds=float("nan")),
        ]
        for kwargs in bad:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.engine.execute(**kwargs)
        alias = "n; DROP TABLE sessions; --"
        result = self.engine.execute(aggregates=[{"op": "count", "alias": alias}])
        self.assertEqual(result["columns"], [alias])
        self.assertEqual(result["rows"], [[5]])

    def test_stale_config_fails_before_execution(self):
        def stale():
            raise ValueError("Source changed")

        engine = MetricExecutor(MetricContracts(fixture(), stale), self.path)
        with self.assertRaisesRegex(ValueError, "Source changed"):
            engine.execute(aggregates=[{"op": "count", "alias": "n"}])


if __name__ == "__main__":
    unittest.main()
