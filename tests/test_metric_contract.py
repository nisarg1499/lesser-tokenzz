"""Synthetic fixtures only: no benchmark tasks, answers or solver traces."""

import sqlite3
import unittest

from lesser_tokenzz.metric_contract import MetricContracts, expr, field, ref


def fixture():
    return {
        "table": "sessions",
        "grain": "id",
        "columns": ["id", "country", "bounce", "ctr"],
        "source": {"fixture": True},
        "metrics": {
            "adjusted": {
                "expression": expr(
                    "mul",
                    field("bounce"),
                    expr("sub", 1, expr("div", field("ctr"), 100.0)),
                )
            },
            "bounce_rank": {"expression": expr("percent_rank_asc", ref("adjusted"))},
            "ctr_rank": {"expression": expr("percent_rank_desc", field("ctr"))},
            "segment": {
                "expression": expr(
                    "case", expr("lt", ref("bounce_rank"), 0.25), "low", "other"
                )
            },
        },
    }


class MetricContractTests(unittest.TestCase):
    def setUp(self):
        self.engine = MetricContracts(fixture())
        self.db = sqlite3.connect(":memory:")
        self.db.execute(
            "CREATE TABLE sessions(id INTEGER,country TEXT,bounce REAL,ctr REAL)"
        )
        self.db.executemany(
            "INSERT INTO sessions VALUES(?,?,?,?)",
            [
                (1, "US", 10, 0),
                (2, "CA", 20, 0),
                (3, "US", 30, 0),
                (4, "US", 30, 0),
                (5, "CA", 50, 0),
            ],
        )

    def tearDown(self):
        self.db.close()

    def rows(self, **kwargs):
        return self.db.execute(
            self.engine.build_metric_query(**kwargs)["sql"]
        ).fetchall()

    def test_filter_after_full_population(self):
        rows = self.rows(
            metrics=["bounce_rank"],
            columns=["id"],
            filters=[{"column": "country", "op": "eq", "value": "CA"}],
            order_by=[{"column": "id"}],
        )
        self.assertEqual(rows, [(2, 0.25), (5, 1.0)])
        wrong = self.db.execute(
            "SELECT id,PERCENT_RANK() OVER(ORDER BY bounce) FROM sessions WHERE country='CA' ORDER BY id"
        ).fetchall()
        self.assertNotEqual(rows, wrong)

    def test_filter_invariance_and_ties(self):
        full = dict(self.rows(metrics=["bounce_rank"], columns=["id"]))
        selected = self.rows(
            metrics=["bounce_rank"],
            columns=["id"],
            filters=[{"column": "id", "op": "in", "value": [3, 4]}],
        )
        self.assertEqual(selected, [(3, full[3]), (4, full[4])])
        self.assertEqual(full[3], full[4])

    def test_derived_filter_compiles_dependencies(self):
        self.assertEqual(
            self.rows(
                metrics=[],
                columns=["id"],
                filters=[{"column": "segment", "op": "eq", "value": "low"}],
            ),
            [(1,)],
        )

    def test_null_semantics_declared_by_sql(self):
        self.db.execute("INSERT INTO sessions VALUES(6,NULL,NULL,NULL)")
        expected = self.db.execute(
            "WITH a AS (SELECT *,bounce*(1-ctr/100.0) AS v FROM sessions), b AS (SELECT id,PERCENT_RANK() OVER(ORDER BY v) AS r FROM a) SELECT id,r FROM b ORDER BY id"
        ).fetchall()
        self.assertEqual(
            self.rows(
                metrics=["bounce_rank"], columns=["id"], order_by=[{"column": "id"}]
            ),
            expected,
        )
        self.assertEqual(
            self.rows(
                metrics=[],
                columns=["id"],
                filters=[{"column": "country", "op": "is_null"}],
            ),
            [(6,)],
        )

    def test_single_row_percent_rank(self):
        self.db.execute("DELETE FROM sessions WHERE id != 1")
        self.assertEqual(self.rows(metrics=["bounce_rank"], columns=["id"]), [(1, 0.0)])

    def test_no_sql_fragment_inputs(self):
        attack = "US' OR 1=1 --"
        self.assertEqual(
            self.rows(
                metrics=[],
                columns=["id"],
                filters=[{"column": "country", "op": "eq", "value": attack}],
            ),
            [],
        )
        with self.assertRaises(ValueError):
            self.rows(metrics=[], columns=["id; DROP TABLE sessions"])
        with self.assertRaises(ValueError):
            self.rows(
                metrics=["bounce_rank"],
                filters=[{"column": "country", "op": "sql", "value": "1=1"}],
            )
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0], 5
        )

    def test_unsupported_ast_and_missing_mapping(self):
        for node in [expr("raw_sql", "SELECT 1"), field("not_mapped")]:
            config = fixture()
            config["metrics"]["adjusted"]["expression"] = node
            with self.assertRaises(ValueError):
                MetricContracts(config)

    def test_cycles_rejected(self):
        config = fixture()
        config["metrics"]["adjusted"]["expression"] = ref("bounce_rank")
        with self.assertRaises(ValueError):
            MetricContracts(config)

    def test_changed_source_fails_closed(self):
        state = {"current": "source1"}

        def verify():
            if state["current"] != "source1":
                raise ValueError("Source changed")

        engine = MetricContracts(fixture(), verify)
        engine.get_metric_contracts()
        state["current"] = "source2"
        with self.assertRaises(ValueError):
            engine.build_metric_query(["bounce_rank"])
        with self.assertRaises(ValueError):
            engine.get_metric_contracts()

    def test_rejects_unsupported_runtime_options(self):
        for kwargs in [
            dict(metrics=["missing"]),
            dict(metrics=["bounce_rank"], limit=0),
            dict(
                metrics=["bounce_rank"],
                filters=[{"column": "id", "op": "gt", "value": float("nan")}],
            ),
            dict(
                metrics=["bounce_rank"],
                filters=[{"column": "id", "op": "eq", "value": None}],
            ),
            dict(
                metrics=["bounce_rank"],
                order_by=[{"column": "id", "descending": "yes"}],
            ),
        ]:
            with self.assertRaises(ValueError):
                self.engine.build_metric_query(**kwargs)

    def test_sorted_and_limited_output(self):
        self.assertEqual(
            self.rows(
                metrics=["bounce_rank"],
                columns=["id"],
                order_by=[{"column": "id", "descending": True}],
                limit=2,
            ),
            [(5, 1.0), (4, 0.5)],
        )

    def test_zero_selected_rows(self):
        self.assertEqual(
            self.rows(
                metrics=["bounce_rank"],
                columns=["id"],
                filters=[{"column": "country", "op": "in", "value": []}],
            ),
            [],
        )


if __name__ == "__main__":
    unittest.main()
