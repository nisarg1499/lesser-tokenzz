"""Fail-closed source provenance tests, not generic truth verification."""

import tempfile
import unittest
from pathlib import Path
from lesser_tokenzz.source_bookmarks import SourceBookmarks
from lesser_tokenzz.search_provider import SearchHit, SearchResponse

QUOTE = "This exact public passage occurs in both independently fetched documents."
URLS = ["https://a.example.com/a", "https://b.example.com/b"]


class Provider:
    def __init__(self, change=None):
        self.change = change

    def fetch_many(self, urls):
        hits = []
        for url in urls:
            item = {"http_status": 200, "content_truncated": False, "final_url": url}
            if self.change:
                item.update(self.change)
            hits.append(
                SearchHit(
                    "source",
                    url,
                    QUOTE,
                    "2026-11-14T00:00:00+00:00",
                    "mock",
                    {"result": item, "run_status": "succeeded"},
                )
            )
        return SearchResponse(hits, 0.1, "mock")


class SourceBookmarkTests(unittest.TestCase):
    def test_save_and_reuse_without_claim_verification(self):
        with tempfile.TemporaryDirectory() as d:
            store = SourceBookmarks(d, Provider(), ["a.example.com", "b.example.com"])
            result = store.learn("public topic", URLS, QUOTE)
            self.assertEqual(result["status"], "source_checked_claim_unverified")
            self.assertFalse(result["evidence"]["answer_verified"])
            self.assertFalse(result["evidence"]["semantic_conflicts_checked"])
            self.assertEqual(len(store.lookup("public topic")["bookmarks"]), 1)
            self.assertEqual(store.lookup("different topic")["status"], "unresolved")

    def test_blank_passage_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            store = SourceBookmarks(d, Provider(), ["a.example.com", "b.example.com"])
            with self.assertRaises(ValueError):
                store.learn("public", URLS, " " * 40)

    def test_failed_provider_run_cannot_persist(self):
        class FailedProvider(Provider):
            def fetch_many(self, urls):
                response = super().fetch_many(urls)
                response.hits[0].metadata["run_status"] = "failed"
                return response

        with tempfile.TemporaryDirectory() as d:
            store = SourceBookmarks(
                d, FailedProvider(), ["a.example.com", "b.example.com"]
            )
            self.assertEqual(store.learn("public", URLS, QUOTE)["status"], "unresolved")

    def test_unknown_truncation_redirect_and_partial_fail_closed(self):
        for change in (
            {"content_truncated": True},
            {"content_truncated": None},
            {"final_url": None},
            {"final_url": "http://localhost"},
            {"http_status": 206},
        ):
            with tempfile.TemporaryDirectory() as d:
                store = SourceBookmarks(
                    d, Provider(change), ["a.example.com", "b.example.com"]
                )
                self.assertEqual(
                    store.learn("public", URLS, QUOTE)["status"], "unresolved"
                )
                self.assertEqual(list(Path(d).glob("*.json")), [])

    def test_missing_quote_unknown_trust_duplicate_hosts(self):
        with tempfile.TemporaryDirectory() as d:
            store = SourceBookmarks(d, Provider(), ["a.example.com", "b.example.com"])
            for urls, quote in [
                (
                    URLS,
                    "A different sentence that is not present anywhere in the source pages.",
                ),
                ([URLS[0], URLS[0]], QUOTE),
                ([URLS[0], "https://evil.example/a"], QUOTE),
            ]:
                self.assertEqual(
                    store.learn("public", urls, quote)["status"], "unresolved"
                )
