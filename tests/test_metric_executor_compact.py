"""Synthetic compact-wrapper tests, without benchmark fixtures."""

import sqlite3
import unittest

from lesser_tokenzz.metric_executor_compact import CompactMetricExecutor
import test_metric_executor as fixtures


class CompactTests(unittest.TestCase):
    setUp = fixtures.MetricExecutorTests.setUp
    tearDown = fixtures.MetricExecutorTests.tearDown

    def test_compact_preserves_values_and_offers_sql_on_demand(self):
        compact = CompactMetricExecutor(self.engine)
        options = dict(
            columns=["id"],
            metrics=["bounce_rank"],
            filters=[{"column": "country", "op": "eq", "value": "CA"}],
            order_by=[{"column": "id"}],
        )
        expected = self.engine.execute(**options)
        result = compact.execute(**options)
        self.assertEqual(result["rows"], expected["rows"])
        self.assertNotIn("sql", result)
        self.assertNotIn("record_sha256", result["source"])
        details = compact.read_query(result["query_handle"])
        self.assertEqual(details["sql"], expected["sql"])
        self.assertEqual(details["source"], expected["source"])
        details["source"].clear()
        self.assertEqual(
            compact.read_query(result["query_handle"])["source"], expected["source"]
        )

    def test_describe_schema_and_equal_information(self):
        description = CompactMetricExecutor(self.engine).describe()
        self.assertEqual(description["columns"][0]["name"], "id")
        self.assertEqual(description["columns"][0]["type"], "INTEGER")
        self.assertNotIn("expression", description["metrics"][0])
        self.assertEqual(
            description["definitions"],
            self.engine.contracts.get_metric_contracts()["metrics"],
        )
        self.assertIsNone(
            CompactMetricExecutor(self.engine).describe(include_definitions=False)[
                "definitions"
            ]
        )
        self.assertIn("population", description)

    def test_local_handles_and_eviction(self):
        first = CompactMetricExecutor(self.engine, max_saved_queries=1)
        second = CompactMetricExecutor(self.engine)
        handle = first.execute(columns=["id"])["query_handle"]
        with self.assertRaises(ValueError):
            second.read_query(handle)
        first.execute(columns=["id"])
        with self.assertRaises(ValueError):
            first.read_query(handle)

    def test_schema_revision_rejected_but_history_readable(self):
        compact = CompactMetricExecutor(self.engine)
        handle = compact.execute(columns=["id"])["query_handle"]
        with sqlite3.connect(self.path) as conn:
            conn.execute("ALTER TABLE sessions ADD COLUMN new_field TEXT")
        with self.assertRaises(ValueError):
            compact.describe()
        self.assertIn("sql", compact.read_query(handle))

    def test_truncation_retained_and_extra_warning_visible(self):
        self.engine.contracts.config["semantics"] = [
            "Fixture requires manual validation."
        ]
        compact = CompactMetricExecutor(self.engine)
        result = compact.execute(columns=["country"], max_rows=1, max_cell_chars=1)
        self.assertTrue(result["truncation"]["row_cap_truncated"])
        self.assertEqual(result["truncation"]["truncated_cells"], [[0, 0]])
        self.assertEqual(
            result["additional_limitations"], ["Fixture requires manual validation."]
        )
