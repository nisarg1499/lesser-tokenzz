"""Typed business expressions with population-preserving SQL construction.

The compiler is generic; the news adapter is a manually reviewed configuration
for five specific source definitions. It is not a prose-to-SQL model or a proof
that arbitrary business definitions are correct.
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from pathlib import Path
from typing import Any, Callable


def fingerprint(value: Any) -> str:
    payload = json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def quote(name: str) -> str:
    if not isinstance(name, str) or not name or "\x00" in name:
        raise ValueError("Invalid SQL identifier")
    return '"' + name.replace('"', '""') + '"'


def literal(value: Any) -> str:
    """Only scalar data is accepted, never SQL fragments."""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float) and math.isfinite(value):
        return repr(value)
    if isinstance(value, str) and "\x00" not in value:
        return "'" + value.replace("'", "''") + "'"
    raise ValueError("Only finite SQL scalar values are supported")


def field(name):
    return {"field": name}


def ref(name):
    return {"metric": name}


def expr(op, *args):
    return {"op": op, "args": list(args)}


class MetricContracts:
    """Compile validated ASTs, then apply output filters after metric stages."""

    def __init__(self, config: dict, verify_source: Callable[[], None] | None = None):
        self.config = config
        self.table = config["table"]
        self.columns = set(config["columns"])
        self.metrics = config["metrics"]
        self.verify_source = verify_source
        if self.columns & set(self.metrics):
            raise ValueError("Metric aliases must not overwrite physical fields")
        # Validate every metric, not merely the first one requested at runtime.
        self._order(list(self.metrics))
        for item in self.metrics.values():
            self._expression(item["expression"])

    def _verify(self):
        if self.verify_source:
            self.verify_source()

    def _dependencies(self, value: Any) -> set[str]:
        if isinstance(value, dict):
            if "metric" in value:
                return {value["metric"]}
            return set().union(*(self._dependencies(v) for v in value.values()))
        if isinstance(value, list):
            return (
                set().union(*(self._dependencies(v) for v in value)) if value else set()
            )
        return set()

    def _order(self, requested: list[str]) -> list[str]:
        ordered, active = [], set()

        def visit(name):
            if name not in self.metrics:
                raise ValueError(f"Unsupported metric: {name}")
            if name in active:
                raise ValueError("Cyclic metric dependency")
            if name in ordered:
                return
            active.add(name)
            for dependency in sorted(
                self._dependencies(self.metrics[name]["expression"])
            ):
                visit(dependency)
            active.remove(name)
            ordered.append(name)

        for name in requested:
            visit(name)
        return ordered

    def _expression(self, node: Any) -> str:
        if not isinstance(node, dict):
            return literal(node)
        if set(node) == {"field"}:
            if node["field"] not in self.columns:
                raise ValueError(f'Unmapped field: {node["field"]}')
            return quote(node["field"])
        if set(node) == {"metric"}:
            if node["metric"] not in self.metrics:
                raise ValueError("Unknown metric reference")
            return quote(node["metric"])
        if set(node) != {"op", "args"} or not isinstance(node["args"], list):
            raise ValueError("Invalid expression AST")
        op, args = node["op"], node["args"]
        binary = {
            "add": "+",
            "sub": "-",
            "mul": "*",
            "div": "/",
            "lt": "<",
            "le": "<=",
            "gt": ">",
            "ge": ">=",
            "eq": "=",
            "and": "AND",
        }
        if op in binary and len(args) == 2:
            return f"({self._expression(args[0])} {binary[op]} {self._expression(args[1])})"
        if op in ("percent_rank_asc", "percent_rank_desc") and len(args) == 1:
            direction = "ASC" if op.endswith("_asc") else "DESC"
            return f"PERCENT_RANK() OVER (ORDER BY {self._expression(args[0])} {direction})"
        if op == "case" and len(args) >= 3 and len(args) % 2 == 1:
            branches = " ".join(
                "WHEN "
                + self._expression(args[i])
                + " THEN "
                + self._expression(args[i + 1])
                for i in range(0, len(args) - 1, 2)
            )
            return f"(CASE {branches} ELSE {self._expression(args[-1])} END)"
        raise ValueError(f"Unsupported expression operation/arity: {op}")

    def get_metric_contracts(self) -> dict:
        self._verify()
        return {
            "table": self.table,
            "grain": self.config["grain"],
            "population": "All rows of the source table before output filters",
            "metrics": self.metrics,
            "source": self.config.get("source", {}),
            "semantics": self.config.get("semantics", []),
        }

    def build_metric_query(
        self,
        metrics: list[str],
        filters: list[dict] | None = None,
        columns: list[str] | None = None,
        order_by: list[dict] | None = None,
        limit: int | None = None,
    ) -> dict:
        """Build SELECT SQL. Filters never alter rank/percentile populations.

        filters use column, op (eq/ne/lt/le/gt/ge/in/is_null/not_null), value.
        order_by uses column and descending. Columns are physical identifiers;
        metrics are configured aliases. Unsupported operations fail explicitly.
        """
        self._verify()
        if not isinstance(metrics, list) or len(metrics) != len(set(metrics)):
            raise ValueError("metrics must be a unique list")
        columns = [self.config["grain"]] if columns is None else columns
        if not isinstance(columns, list) or any(c not in self.columns for c in columns):
            raise ValueError("Unknown physical output column")
        if len(columns) != len(set(columns)) or not columns and not metrics:
            raise ValueError("Require unique, nonempty output selection")
        filters, order_by = filters or [], order_by or []
        needed = list(metrics)
        for item in filters + order_by:
            name = item.get("column")
            if name in self.metrics:
                needed.append(name)
            elif name not in self.columns:
                raise ValueError(f"Unknown condition column: {name}")
        stages, previous = [], quote(self.table)
        for index, name in enumerate(self._order(needed)):
            stage = f"metric_stage_{index}"
            stages.append(
                f'{quote(stage)} AS (SELECT *, {self._expression(self.metrics[name]["expression"])} AS {quote(name)} FROM {previous})'
            )
            previous = quote(stage)
        sql = ("WITH\n  " + ",\n  ".join(stages) + "\n") if stages else ""
        sql += (
            "SELECT "
            + ", ".join(quote(c) for c in columns + metrics)
            + " FROM "
            + previous
        )
        predicates = []
        operators = {
            "eq": "=",
            "ne": "!=",
            "lt": "<",
            "le": "<=",
            "gt": ">",
            "ge": ">=",
        }
        for item in filters:
            if set(item) - {"column", "op", "value"}:
                raise ValueError("Unsupported filter fields")
            name, op = quote(item["column"]), item["op"]
            if op in ("is_null", "not_null"):
                predicates.append(
                    name + (" IS NULL" if op == "is_null" else " IS NOT NULL")
                )
            elif (
                op == "in"
                and isinstance(item.get("value"), list)
                and len(item["value"]) <= 1000
            ):
                predicates.append(
                    name + " IN (" + ", ".join(literal(v) for v in item["value"]) + ")"
                )
            elif op in operators and item.get("value") is not None:
                predicates.append(
                    name + " " + operators[op] + " " + literal(item["value"])
                )
            else:
                raise ValueError("Unsupported filter; use explicit null operations")
        if predicates:
            sql += " WHERE " + " AND ".join(predicates)
        order = []
        for item in order_by:
            if set(item) - {"column", "descending"} or not isinstance(
                item.get("descending", False), bool
            ):
                raise ValueError("Unsupported sort")
            order.append(
                quote(item["column"]) + (" DESC" if item.get("descending") else " ASC")
            )
        if order:
            sql += " ORDER BY " + ", ".join(order)
        if limit is not None:
            if type(limit) is not int or not 1 <= limit <= 10000:
                raise ValueError("limit must be an integer from 1 to 10000")
            sql += f" LIMIT {limit}"
        return {
            "sql": sql,
            "metrics": metrics,
            "population_preserved": True,
            "meaning": "Output filters apply after all metric and full-population window stages.",
            "source": self.config.get("source", {}),
            "semantics": self.config.get("semantics", []),
        }


# This adapter is a reviewed business configuration, not a universal compiler.
# Source hashes intentionally reject changed definitions until they are reviewed.
_NEWS_REVISIONS = {
    0: "fd30ac3b41a3adc193c7527897b2c050f2172368d26ee322d5b77aaaca0cb117",
    3: "62ee016aa56c3af7974e44747a05d4dbf70374a13bc9fa7b956e2852810f9aff",
    52: "e636b65f0864d404c26ab027953dc43de27a2a27da6d2f3351e952b836789357",
    53: "404a7eec7efafb0401dec014b19643a77c924e7e9a2fcd75848f1a8cd39bec31",
    54: "9ee103de978cd45b046c8e27e272f85e2f8574c632718eaafc22e036f181421e",
}


def news_contracts(database: str | Path, knowledge: str | Path) -> MetricContracts:
    """Load only schema and five approved business definitions, never task data."""
    database, knowledge = Path(database).resolve(), Path(knowledge).resolve()

    def snapshot():
        entries = {
            row["id"]: row
            for row in map(json.loads, knowledge.read_text().splitlines())
        }
        hashes = {
            key: fingerprint(entries[key]) for key in _NEWS_REVISIONS if key in entries
        }
        if hashes != _NEWS_REVISIONS:
            raise ValueError(
                "Unsupported/stale business definition revision; review required"
            )
        with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as conn:
            schema = list(conn.execute("PRAGMA table_info(sessions)"))
            fields = [row[1] for row in schema]
        if not {
            "seshkey",
            "bncrate",
            "ctrval",
            "seshviews",
            "engscore",
            "seshdur",
        }.issubset(fields):
            raise ValueError("Required physical field mapping is unavailable")
        return fields, {"record_sha256": hashes, "schema_sha256": fingerprint(schema)}

    columns, source = snapshot()
    bp, cp = ref("bounce_percentile"), ref("ctr_percentile")
    condition = lambda left, right: expr("and", left, right)
    config = {
        "table": "sessions",
        "grain": "seshkey",
        "columns": columns,
        "source": source,
        "semantics": [
            "Source definitions are manually mapped to typed expressions; no task-specific logic.",
            "SQLite native NULL ordering and arithmetic apply; source does not specify a separate NULL policy.",
            "Percentile ties use PERCENT_RANK, not percentiles interpolated between rows.",
            "Segment labels and inequality directions follow the source literally, even when counterintuitive.",
            "No joins, partitions, user-defined population filters, or aggregation are supported.",
        ],
        "metrics": {
            "user_engagement_rate": {
                "source_ids": [0],
                "unit": "engagement score times article views per second",
                "expression": expr(
                    "div",
                    expr(
                        "mul", 1.0, expr("mul", field("seshviews"), field("engscore"))
                    ),
                    field("seshdur"),
                ),
            },
            "adjusted_bounce_rate": {
                "source_ids": [3],
                "unit": "source bounce-rate scale",
                "expression": expr(
                    "mul",
                    field("bncrate"),
                    expr("sub", 1, expr("div", field("ctrval"), 100.0)),
                ),
            },
            "bounce_percentile": {
                "source_ids": [52, 3],
                "unit": "fraction_0_to_1",
                "expression": expr("percent_rank_asc", ref("adjusted_bounce_rate")),
            },
            "ctr_percentile": {
                "source_ids": [53],
                "unit": "fraction_0_to_1",
                "expression": expr("percent_rank_desc", field("ctrval")),
            },
            "performance_segment": {
                "source_ids": [54, 52, 53, 3],
                "unit": "category",
                "expression": expr(
                    "case",
                    condition(expr("lt", bp, 0.25), expr("lt", cp, 0.25)),
                    "High Bounce, Low CTR",
                    condition(expr("lt", bp, 0.25), expr("ge", cp, 0.75)),
                    "High Bounce, High CTR",
                    condition(expr("ge", bp, 0.75), expr("lt", cp, 0.25)),
                    "Low Bounce, Low CTR",
                    condition(expr("ge", bp, 0.75), expr("ge", cp, 0.75)),
                    "Low Bounce, High CTR",
                    "Average Performance",
                ),
            },
        },
    }

    def verify():
        if snapshot()[1] != source:
            raise ValueError("Schema/source changed since contract construction")

    return MetricContracts(config, verify)
