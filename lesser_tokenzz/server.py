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
from .monitor_invalidation import MonitorInvalidation, TelemMonitorClient
from .telem_provider import TelemProvider
from .public_search import PublicWebSearch
from .source_bookmarks import SourceBookmarks
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
    parser.add_argument(
        "--source-bookmarks",
        type=Path,
        help="Opt-in directory for exact corroborated source passages",
    )
    parser.add_argument(
        "--trusted-source-domain",
        action="append",
        default=[],
        help="Exact operator-vetted hostname for source bookmarking (repeatable)",
    )
    parser.add_argument(
        "--web-fallback",
        action="store_true",
        help="Opt-in paid public search for unsupported external facts",
    )
    parser.add_argument(
        "--telem-monitor-id",
        help="Existing reviewed monitor; polls before each evidence read",
    )
    parser.add_argument("--projected-catalog", action="store_true")
    parser.add_argument("--auto-refresh-evidence", action="store_true")
    parser.add_argument(
        "--search-provider",
        default="brave",
        help="Comma-separated bounded provider allowlist",
    )
    parser.add_argument(
        "--auto-routing",
        choices=["accuracy"],
        help="Opt-in Telem provider routing within the allowlist",
    )
    parser.add_argument("--fetch-provider", default="tavily")
    args = parser.parse_args()
    if args.source_bookmarks and not (args.web_fallback and args.trusted_source_domain):
        parser.error("--source-bookmarks requires --web-fallback and trusted domains")
    if args.telem_monitor_id and not (args.eu_catalog and args.auto_refresh_evidence):
        parser.error("--telem-monitor-id requires catalog and auto-refresh")
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

    if args.web_fallback:
        public_search = PublicWebSearch(
            TelemProvider(
                search_providers=args.search_provider.split(","),
                fetch_providers=[args.fetch_provider],
                timeout_s=20,
                auto_routing=args.auto_routing,
            )
        )

        @mcp.tool(
            annotations=ToolAnnotations(
                readOnlyHint=False,
                destructiveHint=False,
                idempotentHint=False,
                openWorldHint=True,
            )
        )
        def search_public_web(
            public_queries: Annotated[list[str], Field(min_length=1, max_length=3)],
            max_results: Annotated[int, Field(ge=1, le=5)] = 3,
        ) -> dict:
            """Fallback for external facts outside the EU resolver. Batch 1..3 independent public-only queries through Telem. Never send DB rows, private context, secrets or full business questions. Returns cited untrusted snippets, not verified answers; assess sources and report uncertainty. Paid external transmission; no cache writes. Use EU resolver for supported EU facts."""
            return public_search.search(public_queries, max_results)

    if args.source_bookmarks:
        bookmarks = SourceBookmarks(
            args.source_bookmarks,
            public_search.provider,
            args.trusted_source_domain,
        )

        @mcp.tool(
            annotations=ToolAnnotations(
                readOnlyHint=False,
                destructiveHint=False,
                idempotentHint=False,
                openWorldHint=True,
            )
        )
        def bookmark_public_evidence(
            public_query: str,
            source_urls: Annotated[list[str], Field(min_length=2, max_length=2)],
            exact_passage: str,
        ) -> dict:
            """Fetch two distinct vetted public sources and persist only an exact shared passage with complete fetch metadata. Never send private context. Automated source check, not claim truth verification: ambiguity and semantic conflicts remain unresolved. No write if checks fail. Does not alter EU fact cache."""
            return bookmarks.learn(public_query, source_urls, exact_passage)

        @mcp.tool(annotations=readonly)
        def lookup_public_bookmarks(public_query: str) -> dict:
            """Read fresh exact-query source bookmarks as untrusted evidence, never verified facts. Reassess applicability and conflicts; no semantic matching or truth guarantee."""
            return bookmarks.lookup(public_query)

    if args.eu_catalog:
        resolver = EvidenceResolver(
            args.eu_catalog,
            TelemProvider(
                search_providers=args.search_provider.split(","),
                auto_routing=args.auto_routing,
                fetch_providers=[args.fetch_provider],
                timeout_s=20,
            ),
            refresh_enabled=args.auto_refresh_evidence,
            monitor=(
                MonitorInvalidation(
                    str(args.eu_catalog) + ".monitor.json",
                    TelemMonitorClient(args.telem_monitor_id),
                )
                if args.telem_monitor_id
                else None
            ),
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

        if args.projected_catalog and not args.telem_monitor_id:

            @mcp.tool(annotations=readonly)
            def lookup_eu_membership(countries: list[str]) -> dict:
                """Return relevant EU membership evidence. Unmatched aliases are not negatives."""
                return lookup_membership(args.eu_catalog, countries)

        elif not args.telem_monitor_id:

            @mcp.tool(annotations=readonly)
            def get_eu_membership_catalog() -> dict:
                """Read complete current EU membership, with evidence and freshness."""
                return read_catalog(args.eu_catalog)

    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
