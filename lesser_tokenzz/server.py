"""Serve business definitions, live SQL, and a fresh Telem-built EU catalog."""

import argparse
import json
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .catalog_projection import lookup_membership
from .eu_catalog import read_catalog
from .evidence_resolver import EvidenceResolver
from .telem_provider import TelemProvider
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
    parser.add_argument("--auto-refresh-evidence", action="store_true")
    parser.add_argument("--search-provider", default="brave")
    parser.add_argument("--fetch-provider", default="tavily")
    args = parser.parse_args()
    if args.auto_refresh_evidence and not args.eu_catalog:
        parser.error("--auto-refresh-evidence requires --eu-catalog")
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
    def run_sql(sql: str, max_rows: Annotated[int, Field(ge=1, le=1000)] = 100) -> dict:
        """Query live business data. max_rows is 1–1000; inspect truncation. Respect metric populations."""
        return query_database(args.database, sql, max_rows)

    if args.eu_catalog:
        resolver = EvidenceResolver(
            args.eu_catalog,
            TelemProvider(
                search_providers=[args.search_provider],
                fetch_providers=[args.fetch_provider],
                timeout_s=20,
            ),
            refresh_enabled=args.auto_refresh_evidence,
        )

        @mcp.tool(
            annotations=ToolAnnotations(
                readOnlyHint=False,
                destructiveHint=False,
                idempotentHint=False,
                openWorldHint=True,
            )
        )
        def resolve_external_fact(
            subjects: list[str],
            predicate: Literal["eu_membership"] = "eu_membership",
            as_of: str | None = None,
            max_age_hours: Annotated[float, Field(gt=0, le=24)] = 24,
        ) -> dict:
            """Resolve current EU membership with compact citations; optional paid refresh on stale/missing evidence. Only canonical public country names; no private business text."""
            return resolver.resolve(subjects, predicate, as_of, max_age_hours)

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
