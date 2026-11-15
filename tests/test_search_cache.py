"""Synthetic cache-behaviour tests; these do not measure live speed or accuracy."""

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from lesser_tokenzz.public_search import PublicWebSearch
from lesser_tokenzz.search_cache import PublicSearchCache, query_tokens, same_topic
from lesser_tokenzz.telem_provider import TelemProvider


class SearchCacheTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.now = datetime(2026, 11, 14, 12, tzinfo=timezone.utc)
        self.sent = []
        self.fail = False

    def transport(self, _path, payload):
        queries = [item["query"] for item in payload["user_input"]]
        self.sent.append(queries)
        if self.fail:
            return {"preprocessor_runs": []}
        return {
            "preprocessor_runs": [
                {
                    "batch_index": index,
                    "status": "succeeded",
                    "preprocessor_name": "brave",
                    "output_payload": {
                        "results": [
                            {
                                "url": f"https://example.com/{index}",
                                "summary": f"Passage about {query}",
                            }
                        ]
                    },
                }
                for index, query in enumerate(queries)
            ]
        }

    def search(self, ttl_hours=24):
        cache = PublicSearchCache(
            Path(self.directory.name), ttl_hours, clock=lambda: self.now
        )
        provider = TelemProvider(
            search_providers=["brave"],
            fetch_providers=["tavily"],
            transport=self.transport,
        )
        return PublicWebSearch(provider, cache)

    def test_second_call_hits_without_provider_request(self):
        first = self.search().search(["canada official currency"])
        self.assertEqual((first["cached"], first["telem_request_count"]), (False, 1))
        self.assertEqual(first["results"][0]["cache"], {"state": "miss"})
        # A new server instance and a reworded query still reuse the evidence.
        second = self.search().search(["What is the official currency of Canada?"])
        group = second["results"][0]
        self.assertEqual((second["cached"], second["telem_request_count"]), (True, 0))
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(group["status"], "evidence_found")
        self.assertEqual(group["cache"]["matched_query"], "canada official currency")
        self.assertEqual(group["evidence"][0]["url"], "https://example.com/0")
        self.assertIn("snippet_sha256", group["evidence"][0])
        self.assertFalse(second["answer_verified"])
        self.assertIsNone(second["cost_usd"])

    def test_different_entity_is_a_miss(self):
        self.search().search(["canada official currency"])
        result = self.search().search(["france official currency"])
        self.assertEqual(result["cache_hits"], 0)
        self.assertEqual(len(self.sent), 2)
        self.assertIsNone(same_topic(query_tokens("g7 members"), query_tokens("g20")))

    def test_only_misses_are_sent_in_one_batch(self):
        self.search().search(["canada official currency"])
        result = self.search().search(
            ["canada official currency", "g7 member countries"]
        )
        self.assertEqual(self.sent[-1], ["g7 member countries"])
        self.assertEqual((result["cache_hits"], result["cached"]), (1, False))
        self.assertEqual(
            [g["cache"]["state"] for g in result["results"]], ["hit", "miss"]
        )
        self.assertEqual(
            result["results"][1]["evidence"][0]["url"], "https://example.com/0"
        )

    def test_expired_and_future_entries_are_not_served(self):
        self.search().search(["canada official currency"])
        self.now += timedelta(hours=24, seconds=1)
        self.assertEqual(
            self.search().search(["canada official currency"])["cache_hits"], 0
        )
        self.now -= timedelta(days=3)
        self.assertEqual(
            self.search().search(["canada official currency"])["cache_hits"], 0
        )
        with self.assertRaises(ValueError):
            PublicSearchCache(self.directory.name, ttl_hours=25)

    def test_unresolved_corrupt_and_too_small_entries_are_misses(self):
        self.fail = True
        failed = self.search().search(["canada official currency"])
        self.assertEqual(failed["results"][0]["status"], "unresolved")
        self.assertEqual(list(Path(self.directory.name).glob("*.json")), [])
        self.fail = False
        self.search().search(["canada official currency"], 1)
        # A one-result entry cannot answer a three-result request.
        self.assertEqual(
            self.search().search(["canada official currency"], 3)["cache_hits"], 0
        )
        for path in Path(self.directory.name).glob("*.json"):
            path.write_text("{not json")
        self.assertEqual(
            self.search().search(["canada official currency"], 1)["cache_hits"], 0
        )


if __name__ == "__main__":
    unittest.main()
