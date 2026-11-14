"""Projection correctness and context-size checks; no model or external calls."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from lesser_tokenzz.catalog_projection import lookup_membership


class Tests(unittest.TestCase):
    def catalog(self):
        return {
            "status": "complete",
            "scope": "Current EU membership",
            "member_count": 3,
            "members": ["France", "Germany", "Spain"],
            "evidence": [
                {"country": name, "passage": "Member"}
                for name in ["France", "Germany", "Spain"]
            ],
            "sources": [{"url": "https://official.example/list"}],
            "built_at": "2026-11-14T00:00:00+00:00",
            "ttl_hours": 24,
        }

    def test_projection_keeps_completeness_and_relevant_evidence(self):
        with patch(
            "lesser_tokenzz.catalog_projection.read_catalog",
            return_value=self.catalog(),
        ):
            result = lookup_membership("unused", ["France", "India"])
        self.assertEqual(result["member_count"], 3)
        self.assertEqual(
            [row["country"] for row in result["supporting_passages"]], ["France"]
        )
        self.assertFalse(result["matches"][1]["listed_in_complete_eu_list"])
        self.assertEqual(len(result["complete_member_list_sha256"]), 64)

    def test_no_fuzzy_inference(self):
        with patch(
            "lesser_tokenzz.catalog_projection.read_catalog",
            return_value=self.catalog(),
        ):
            result = lookup_membership("unused", ["Frenchland"])
        self.assertIsNone(result["matches"][0]["matched_member"])
        self.assertIn("noncanonical", result["matching_policy"])

    def test_stale_and_bad_inputs(self):
        with patch(
            "lesser_tokenzz.catalog_projection.read_catalog",
            return_value={"status": "stale"},
        ):
            self.assertEqual(
                lookup_membership("unused", ["France"]), {"status": "stale"}
            )
        with self.assertRaises(ValueError):
            lookup_membership("unused", [])


if __name__ == "__main__":
    unittest.main()
