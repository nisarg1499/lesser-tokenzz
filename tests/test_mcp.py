"""Exercise the actual stdio handshake and tools using a synthetic database."""

import asyncio
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class MCPTests(unittest.TestCase):
    def test_stdio_catalog_and_sql(self):
        self.check_tools(False)

    def test_opt_in_public_search(self):
        self.check_tools(True)

    def test_opt_in_bookmark_tools(self):
        self.check_tools(True, True)

    def check_tools(self, fallback, bookmarks=False):
        async def check():
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                db = root / "sample.sqlite"
                with sqlite3.connect(db) as conn:
                    conn.execute("CREATE TABLE rows (id INTEGER)")
                    conn.execute("INSERT INTO rows VALUES (1)")
                config = root / "contract.json"
                config.write_text(
                    json.dumps(
                        {
                            "table": "rows",
                            "grain": "id",
                            "columns": ["id"],
                            "metrics": {},
                        }
                    )
                )
                params = StdioServerParameters(
                    command=sys.executable,
                    args=[
                        "-m",
                        "lesser_tokenzz.server",
                        "--database",
                        str(db),
                        "--contracts",
                        str(config),
                        "--eu-catalog",
                        str(root / "missing-eu.json"),
                    ]
                    + (["--web-fallback"] if fallback else [])
                    + (
                        [
                            "--source-bookmarks",
                            str(root / "bookmarks"),
                            "--trusted-source-domain",
                            "a.example.com",
                            "--trusted-source-domain",
                            "b.example.com",
                        ]
                        if bookmarks
                        else []
                    ),
                )
                async with stdio_client(params) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        listing = await session.list_tools()
                        self.assertEqual(
                            {t.name for t in listing.tools},
                            {
                                "get_metric_contracts",
                                "run_sql",
                                "get_eu_membership_catalog",
                                "resolve_external_fact",
                            }
                            | ({"search_public_web"} if fallback else set())
                            | (
                                {"bookmark_public_evidence", "lookup_public_bookmarks"}
                                if bookmarks
                                else set()
                            ),
                        )
                        schemas = {t.name: t.inputSchema for t in listing.tools}
                        if bookmarks:
                            result = await session.call_tool(
                                "lookup_public_bookmarks",
                                {"public_query": "public topic"},
                            )
                            self.assertEqual(
                                json.loads(result.content[0].text)["status"],
                                "unresolved",
                            )
                        if fallback:
                            props = schemas["search_public_web"]["properties"]
                            self.assertEqual(props["public_queries"]["maxItems"], 3)
                            self.assertEqual(props["max_results"]["maximum"], 5)
                            rejected = await session.call_tool(
                                "search_public_web", {"public_queries": ["q"] * 4}
                            )
                            self.assertTrue(rejected.isError)
                        rows = schemas["run_sql"]["properties"]["max_rows"]
                        self.assertEqual((rows["minimum"], rows["maximum"]), (1, 1000))
                        predicate = schemas["resolve_external_fact"]["properties"][
                            "predicate"
                        ]
                        self.assertEqual(predicate.get("const"), "eu_membership")
                        rejected = await session.call_tool(
                            "run_sql", {"sql": "SELECT 1", "max_rows": 10000}
                        )
                        self.assertTrue(rejected.isError)
                        rejected = await session.call_tool(
                            "resolve_external_fact",
                            {
                                "subjects": ["France"],
                                "predicate": "current EU membership",
                            },
                        )
                        self.assertTrue(rejected.isError)
                        result = await session.call_tool(
                            "resolve_external_fact", {"subjects": ["France"]}
                        )
                        self.assertFalse(result.isError)
                        self.assertEqual(
                            json.loads(result.content[0].text)["reason"],
                            "refresh_disabled",
                        )
                        result = await session.call_tool("get_metric_contracts", {})
                        self.assertFalse(result.isError)
                        result = await session.call_tool(
                            "run_sql", {"sql": "SELECT id FROM rows"}
                        )
                        self.assertFalse(result.isError)
                        self.assertEqual(
                            json.loads(result.content[0].text)["rows"], [[1]]
                        )

        asyncio.run(check())
