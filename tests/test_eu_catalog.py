"""Catalog completeness and freshness checks using synthetic official page shapes."""

from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from lesser_tokenzz.eu_catalog import EU_URL, build_catalog, read_catalog


def page(url, text, truncated=False):
    return {
        "preprocessor_runs": [
            {
                "output_payload": {
                    "fetched_results": [
                        {
                            "url": url,
                            "content": text,
                            "status": "succeeded",
                            "content_truncated": truncated,
                            "fetched_at": "2026-11-14T00:00:00+00:00",
                            "provider": "mock",
                        }
                    ]
                }
            }
        ]
    }


class Tests(unittest.TestCase):
    def sources(self):
        return [
            page(EU_URL, "Pages (2)\nFrance\nEU Member State since 1958"),
            page(EU_URL + "?page=1", "Pages (2)\nGermany\nEU Member State since 1958"),
        ]

    def test_full_list(self):
        self.assertEqual(
            build_catalog(self.sources(), 1)["members"], ["France", "Germany"]
        )

    def test_missing_page_rejected(self):
        with self.assertRaises(ValueError):
            build_catalog(self.sources()[:1], 1)

    def test_wrong_count_rejected(self):
        sources = self.sources()
        sources[1]["preprocessor_runs"][0]["output_payload"]["fetched_results"][0][
            "content"
        ] = "Pages (2)"
        with self.assertRaises(ValueError):
            build_catalog(sources, 1)

    def test_legacy_builder_rejects_failed_raw_run(self):
        sources = self.sources()
        sources[0]["preprocessor_runs"][0]["error"] = "incomplete"
        with self.assertRaises(ValueError):
            build_catalog(sources, 1)

    def test_legacy_builder_rejects_warning(self):
        sources = self.sources()
        sources[0]["preprocessor_runs"][0]["output_payload"]["fetched_results"][0][
            "warning"
        ] = "partial"
        with self.assertRaises(ValueError):
            build_catalog(sources, 1)

    def test_stale_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.json"
            path.write_text(json.dumps(build_catalog(self.sources(), 1)))
            self.assertEqual(
                read_catalog(path, datetime(2026, 11, 16, tzinfo=timezone.utc))[
                    "status"
                ],
                "stale",
            )


if __name__ == "__main__":
    unittest.main()
