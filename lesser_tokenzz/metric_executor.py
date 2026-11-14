"""Execute reviewed metric plans with bounded results, without another model call."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from .metric_contract import MetricContracts, quote


class MetricExecutor:
    """Compose metric stages, output filters, optional summaries, then row limits.

    The database is opened read-only for each call. Callers provide structured
    selections, never SQL fragments. Aggregate NULL/type behavior is SQLite's.
    """

    def __init__(self, contracts: MetricContracts, database: str | Path):
        self.contracts = contracts
        self.database = Path(database).resolve()

    def execute(
        self,
        metrics=None,
        columns=None,
        filters=None,
        group_by=None,
        aggregates=None,
        order_by=None,
        limit=None,
        max_rows=100,
        max_cells=1000,
        max_cell_chars=2000,
        timeout_seconds=10,
    ):
        """Return columns + row arrays, compiled SQL, provenance and truncation.

        aggregates: [{op: count|avg|sum|min|max, column: name|None, alias: name}].
        Only count accepts column=None (COUNT(*)). Grouping requires aggregates;
        grouped output is group_by followed by aggregate aliases. metrics and
        columns are row-mode selections and must be omitted in summary mode.
        limit is a requested SQL limit; caps independently bound tool output.
        """
        for name, value, upper in [
            ("max_rows", max_rows, 10000),
            ("max_cells", max_cells, 100000),
            ("max_cell_chars", max_cell_chars, 10000),
        ]:
            if type(value) is not int or not 1 <= value <= upper:
                raise ValueError(f"{name} must be an integer from 1 to {upper}")
        if type(timeout_seconds) not in (int, float) or not 0 < timeout_seconds <= 60:
            raise ValueError("timeout_seconds must be positive and at most 60")
        if limit is not None and (type(limit) is not int or not 1 <= limit <= 10000):
            raise ValueError("limit must be an integer from 1 to 10000")
        groups = self._list(group_by, "group_by")
        summaries = self._list(aggregates, "aggregates")
        sorts = self._list(order_by, "order_by")
        if groups and not summaries:
            raise ValueError("group_by requires aggregates")
        if summaries:
            if metrics is not None or columns is not None:
                raise ValueError(
                    "Use group_by and aggregates instead of metrics/columns for summaries"
                )
            plan, outputs = self._summary(groups, summaries, filters)
        else:
            plan = self.contracts.build_metric_query(
                metrics=[] if metrics is None else metrics,
                columns=columns,
                filters=filters,
            )
            outputs = (
                [self.contracts.config["grain"]] if columns is None else columns
            ) + ([] if metrics is None else metrics)
        if len(outputs) > max_cells:
            raise ValueError("Selection exceeds cell budget; request fewer columns")
        sql = plan["sql"]
        if sorts:
            terms = []
            for item in sorts:
                if not isinstance(item, dict) or set(item) - {"column", "descending"}:
                    raise ValueError("Invalid sort entry")
                if (
                    item.get("column") not in outputs
                    or type(item.get("descending", False)) is not bool
                ):
                    raise ValueError(
                        "Sort must name an output column and a boolean direction"
                    )
                terms.append(
                    quote(item["column"])
                    + (" DESC" if item.get("descending") else " ASC")
                )
            sql += " ORDER BY " + ", ".join(terms)
        # One extra row distinguishes a complete bounded result from truncation.
        capacity = min(max_rows, max_cells // len(outputs))
        fetch_limit = min(limit, capacity + 1) if limit is not None else capacity + 1
        executed_sql = sql + f" LIMIT {fetch_limit}"
        started = time.monotonic()
        with sqlite3.connect(self.database.as_uri() + "?mode=ro", uri=True) as conn:
            conn.execute("PRAGMA query_only=ON")
            conn.set_progress_handler(
                lambda: int(time.monotonic() - started > timeout_seconds), 1000
            )
            cursor = conn.execute(executed_sql)
            names = [item[0] for item in cursor.description]
            fetched = cursor.fetchall()
        rows, shortened = [], []
        for ri, row in enumerate(fetched[:capacity]):
            values = []
            for ci, value in enumerate(row):
                if isinstance(value, bytes):
                    raise ValueError(
                        "Binary values are unsupported; select other columns"
                    )
                if isinstance(value, str) and len(value) > max_cell_chars:
                    value = value[:max_cell_chars]
                    shortened.append([ri, ci])
                values.append(value)
            rows.append(values)
        return {
            "columns": names,
            "rows": rows,
            "returned_rows": len(rows),
            "row_cap_truncated": len(fetched) > capacity,
            "truncated_cells": shortened,
            "requested_limit": limit,
            "requested_limit_may_omit_rows": limit is not None
            and len(fetched) >= limit,
            "caps": {
                "rows": max_rows,
                "cells": max_cells,
                "cell_chars": max_cell_chars,
            },
            "sql": executed_sql,
            "source": plan.get("source", {}),
            "semantics": plan.get("semantics", [])
            + [
                "Global metric stages precede output filters; grouping follows those filters.",
                "COUNT(column) excludes NULL; COUNT(*) includes rows. Other aggregates use SQLite native NULL/type semantics.",
                "Without explicit order_by, result order is unspecified.",
            ],
            "elapsed_seconds": time.monotonic() - started,
        }

    @staticmethod
    def _list(value, name):
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError(f"{name} must be a list")
        return value

    def _summary(self, groups, summaries, filters):
        available = self.contracts.columns | set(self.contracts.metrics)
        if any(not isinstance(g, str) or g not in available for g in groups) or len(
            set(groups)
        ) != len(groups):
            raise ValueError(
                "Group columns must be unique configured fields or metrics"
            )
        needed, terms, aliases = list(groups), [], []
        for item in summaries:
            if not isinstance(item, dict) or set(item) - {"op", "column", "alias"}:
                raise ValueError("Invalid aggregate entry")
            op, column, alias = item.get("op"), item.get("column"), item.get("alias")
            if op not in ("count", "avg", "sum", "min", "max"):
                raise ValueError("Unsupported aggregate operation")
            if not isinstance(alias, str) or not alias or alias in groups + aliases:
                raise ValueError("Aggregate aliases must be nonempty and unique")
            if column is None:
                if op != "count":
                    raise ValueError("Only count accepts an omitted column")
                argument = "*"
            elif not isinstance(column, str) or column not in available:
                raise ValueError(
                    "Aggregate column must be a configured field or metric"
                )
            else:
                needed.append(column)
                argument = quote(column)
            aliases.append(alias)
            terms.append(f"{op.upper()}({argument}) AS {quote(alias)}")
        needed = list(dict.fromkeys(needed)) or [self.contracts.config["grain"]]
        plan = self.contracts.build_metric_query(
            metrics=[n for n in needed if n in self.contracts.metrics],
            columns=[n for n in needed if n in self.contracts.columns],
            filters=filters,
        )
        projection = [quote(g) for g in groups] + terms
        plan["sql"] = (
            "SELECT "
            + ", ".join(projection)
            + " FROM ("
            + plan["sql"]
            + ') AS "filtered_metrics"'
        )
        if groups:
            plan["sql"] += " GROUP BY " + ", ".join(quote(g) for g in groups)
        return plan, groups + aliases
