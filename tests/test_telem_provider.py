"""MOCK protocol tests, not live access or quality measurements."""

import os, unittest
from unittest.mock import patch
from lesser_tokenzz.telem_provider import TelemProvider, TelemUnavailable


class ResponseLimitTests(unittest.TestCase):
    def test_oversized_json_rejected_before_parsing(self):
        import io
        from lesser_tokenzz.telem_provider import (
            read_response,
            MAX_RESPONSE_BYTES,
            TelemRequestError,
        )

        with self.assertRaises(TelemRequestError):
            read_response(io.BytesIO(b" " * (MAX_RESPONSE_BYTES + 1)))


class Tests(unittest.TestCase):
    def make(self, **kw):
        return TelemProvider(
            search_providers=["brave"], fetch_providers=["tavily"], **kw
        )

    def test_explicit(self):
        with self.assertRaises(ValueError):
            TelemProvider(search_providers=[], fetch_providers=["tavily"])

    def test_missing_key(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(TelemUnavailable):
                self.make().search("example")

    def test_unapproved_base_refuses_before_network(self):
        with patch.dict(
            os.environ,
            {
                "TELEM_API_KEY": "synthetic-test-value",
                "TELEM_BASE_URL": "https://unapproved.example",
            },
        ):
            with self.assertRaises(TelemUnavailable):
                self.make().search("example")

    def test_search(self):
        raw = {
            "preprocessor_runs": [
                {
                    "preprocessor_name": "brave",
                    "latency_ms": 12,
                    "cost_usd": 0.005,
                    "output_payload": {
                        "results": [
                            {"url": "https://example.com", "summary": "evidence"}
                        ]
                    },
                },
                {"preprocessor_name": "exa", "error": {"code": "timeout"}},
            ]
        }

        def mock(path, payload):
            self.assertEqual(payload["search"]["providers"]["include"], ["brave"])
            return raw

        r = self.make(transport=mock).search("example")
        self.assertEqual(r.hits[0].provider, "brave")
        self.assertEqual(r.usage["response"], raw)
        self.assertEqual(r.usage["measurement"], "mock")
        self.assertIsNone(r.cost_usd)

    def test_fetch_many_limits(self):
        provider = self.make(transport=lambda *_: self.fail("must not send request"))
        for urls in (
            [],
            ["https://example.com"] * 2,
            ["https://e.com/" + str(i) for i in range(6)],
            ["file:///tmp/x"],
            ["https://user:password@example.com"],
            [None],
        ):
            with self.subTest(urls=urls), self.assertRaises(ValueError):
                provider.fetch_many(urls)

    def test_fetch_many_one_request(self):
        calls = []

        def transport(path, payload):
            calls.append((path, payload))
            return {"preprocessor_runs": []}

        urls = ["https://example.com/a", "https://example.com/b"]
        self.make(transport=transport).fetch_many(urls)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1]["urls"], urls)
        self.assertTrue(calls[0][1]["options"]["no_cache"])

    def test_fetch(self):
        def mock(path, payload):
            self.assertEqual(payload["options"]["providers"], ["tavily"])
            self.assertTrue(payload["options"]["no_cache"])
            return {
                "preprocessor_runs": [
                    {
                        "output_payload": {
                            "fetched_results": [
                                {
                                    "url": "https://example.com",
                                    "provider": "tavily",
                                    "status": "succeeded",
                                    "content": "page",
                                    "content_truncated": True,
                                    "fetched_at": "source-time",
                                }
                            ]
                        }
                    }
                ]
            }

        r = self.make(transport=mock).fetch("https://example.com")
        self.assertTrue(r.hits[0].metadata["result"]["content_truncated"])
        self.assertEqual(r.hits[0].retrieved_at, "source-time")


if __name__ == "__main__":
    unittest.main()
