"""Serve business definitions, live SQL, and a fresh Telem-built EU catalog."""

import argparse
import json
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .catalog_projection import lookup_membership
from .eu_catalog import read_catalog
from .metric_contract import MetricContracts, news_contracts
from .metric_executor import MetricExecutor
from .metric_executor_compact import CompactMetricExecutor
from .sql import run_sql as query_database


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--contracts", type=Path, help="Reviewed business contract JSON"
    )
    source.add_argument(
        "--news-knowledge", type=Path, help="Original approved news KB JSONL"
    )
    parser.add_argument("--eu-catalog", type=Path)
    parser.add_argument("--projected-catalog", action="store_true")
    args = parser.parse_args()
    if args.projected_catalog and not args.eu_catalog:
        parser.error("--projected-catalog requires --eu-catalog")
    contracts = (
        news_contracts(args.database, args.news_knowledge)
        if args.news_knowledge
        else MetricContracts(json.loads(args.contracts.read_text()))
    )
    catalog = CompactMetricExecutor(MetricExecutor(contracts, args.database))
    mcp = FastMCP("lesser-tokenzz")
    readonly = ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )

    @mcp.tool(annotations=readonly)
    def get_metric_contracts() -> dict:
        """Read reviewed business definitions, units, dependencies and schema."""
        result = catalog.describe()
        result.pop(
            "query_inspection", None
        )  # This server exposes SQL, not saved query handles.
        return result

    @mcp.tool(annotations=readonly)
    def run_sql(sql: str, max_rows: int = 100) -> dict:
        """Query live business data. Respect metric populations; inspect truncation."""
        return query_database(args.database, sql, max_rows)

    if args.eu_catalog:
        if args.projected_catalog:

            @mcp.tool(annotations=readonly)
            def lookup_eu_membership(countries: list[str]) -> dict:
                """Return relevant EU membership evidence. Unmatched aliases are not negatives."""
                return lookup_membership(args.eu_catalog, countries)

        else:

            @mcp.tool(annotations=readonly)
            def get_eu_membership_catalog() -> dict:
                """Read complete current EU membership, with evidence and freshness."""
                return read_catalog(args.eu_catalog)

    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
