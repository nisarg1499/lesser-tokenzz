"""Small agent-facing results with session-local, opt-in query inspection."""

from __future__ import annotations

import copy
import secrets
import sqlite3
from collections import OrderedDict

from .metric_contract import fingerprint
from .metric_executor import MetricExecutor


class CompactMetricExecutor:
    """Wrap an executor without changing its calculations or output bounds.

    Create one instance per agent session. Query handles are random, local to
    that instance and bounded in memory; they are not shared caches or secrets.
    """

    def __init__(self, executor: MetricExecutor, max_saved_queries: int = 100):
        if type(max_saved_queries) is not int or not 1 <= max_saved_queries <= 1000:
            raise ValueError("max_saved_queries must be between 1 and 1000")
        self.executor = executor
        self.max_saved_queries = max_saved_queries
        self._queries = OrderedDict()
        self._schema = self._read_schema()
        self._schema_version = fingerprint(self._schema)
        self._validate()

    def _read_schema(self):
        # Table identifiers are quoted by escaping; no caller SQL is accepted.
        table = self.executor.contracts.table.replace('"', '""')
        with sqlite3.connect(
            self.executor.database.as_uri() + "?mode=ro", uri=True
        ) as conn:
            return list(conn.execute(f'PRAGMA table_info("{table}")'))

    def _validate(self):
        contract = self.executor.contracts.get_metric_contracts()
        schema = self._read_schema()
        if fingerprint(schema) != self._schema_version:
            raise ValueError("Schema changed since this session started")
        if {row[1] for row in schema} != self.executor.contracts.columns:
            raise ValueError("Schema columns do not match the configured contract")
        approved = contract.get("source", {}).get("schema_sha256")
        if approved and approved != self._schema_version:
            raise ValueError("Schema does not match approved source fingerprint")
        return contract

    @staticmethod
    def _source(source):
        return {
            "ids": sorted(source.get("record_sha256", {}), key=str),
            "version": fingerprint(source),
        }

    def describe(self, include_definitions: bool = True):
        """Provide usable field names/types without a second schema tool call."""
        if type(include_definitions) is not bool:
            raise ValueError("include_definitions must be a boolean")
        contract = self._validate()
        metrics = []
        for name, item in contract["metrics"].items():
            metrics.append(
                {
                    "name": name,
                    "unit": item.get("unit", "unspecified"),
                    "source_ids": item.get("source_ids", []),
                    "depends_on": sorted(
                        self.executor.contracts._dependencies(item["expression"])
                    ),
                }
            )
        return {
            "table": contract["table"],
            "grain": contract["grain"],
            "columns": [
                {
                    "name": row[1],
                    "type": row[2] or "undeclared",
                    "not_null_declared": bool(row[3]),
                    "primary_key_position": row[5],
                }
                for row in self._schema
            ],
            "metrics": metrics,
            "population": contract["population"],
            "limitations": contract.get("semantics", []),
            "source": self._source(contract.get("source", {})),
            "definitions": (
                copy.deepcopy(contract["metrics"]) if include_definitions else None
            ),
            "query_inspection": "execute returns a session-local query_handle; read_query retrieves exact SQL and provenance.",
        }

    def execute(self, **kwargs):
        """Return decision data; retain the complete underlying response locally."""
        self._validate()
        result = self.executor.execute(**kwargs)
        handle = secrets.token_urlsafe(18)
        self._queries[handle] = copy.deepcopy(result)
        while len(self._queries) > self.max_saved_queries:
            self._queries.popitem(last=False)
        summary = {
            "query_handle": handle,
            "columns": result["columns"],
            "rows": result["rows"],
            "returned_rows": result["returned_rows"],
            "source": self._source(result["source"]),
            "scope": "Full-population metrics → output filters → optional aggregation → sort/limit.",
            "semantics": {
                "nulls": "SQLite native NULL/type behavior; no separate business NULL policy inferred.",
                "ties": "PERCENT_RANK ties share rank, not interpolated percentiles.",
                "labels": "Configured source labels and thresholds are followed literally.",
                "order": "Unspecified unless order_by is provided.",
            },
            "truncation": {
                key: result[key]
                for key in (
                    "row_cap_truncated",
                    "truncated_cells",
                    "requested_limit",
                    "requested_limit_may_omit_rows",
                    "caps",
                )
            },
            "elapsed_seconds": result["elapsed_seconds"],
        }
        # Other domain adapters may have extra caveats. Keep them visible rather
        # than assuming the standard news caveats cover arbitrary configurations.
        known_prefixes = (
            "Source definitions are manually mapped",
            "SQLite native NULL",
            "Percentile ties use PERCENT_RANK",
            "Segment labels and inequality",
            "No joins, partitions",
            "Global metric stages precede",
            "COUNT(column) excludes NULL",
            "Without explicit order_by",
        )
        extras = [s for s in result["semantics"] if not s.startswith(known_prefixes)]
        if extras:
            summary["additional_limitations"] = extras
        summary["unsupported"] = (
            "No joins, custom populations, partitions, DISTINCT or HAVING."
        )
        summary["semantics"][
            "aggregates"
        ] = "COUNT(column) excludes NULL; COUNT(*) counts rows."
        return summary

    def read_query(self, query_handle: str):
        """Inspect a prior query; never rerun it or reinterpret stale evidence."""
        if not isinstance(query_handle, str) or query_handle not in self._queries:
            raise ValueError("Unknown, expired, or different-session query handle")
        result = self._queries[query_handle]
        return copy.deepcopy(
            {
                "query_handle": query_handle,
                "sql": result["sql"],
                "source": result["source"],
                "semantics": result["semantics"],
                "note": "Historical execution record, not a new source validation.",
            }
        )
