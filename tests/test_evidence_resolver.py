"""Synthetic transport tests; these do not demonstrate live Telem performance."""

from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from lesser_tokenzz.evidence_resolver import (
    EvidenceResolver,
    COUNTRIES,
    SOURCES,
    REVIEWED_MEMBERS,
)
from lesser_tokenzz.telem_provider import TelemProvider

NOW = datetime(2026, 11, 14, 12, tzinfo=timezone.utc)
MEMBERS = sorted(REVIEWED_MEMBERS)


class Tests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "eu.json"
        self.calls = []
        self.partial = False

        def transport(path, payload):
            self.calls.append((path, payload))
            if path.endswith("search"):
                return {
                    "preprocessor_runs": [
                        {
                            "preprocessor_name": "mock",
                            "output_payload": {"results": [{"url": SOURCES[0]}]},
                        }
                    ]
                }
            runs = []
            for url in payload["urls"]:
                names = MEMBERS[:14] if url == SOURCES[0] else MEMBERS[14:]
                content = "Pages (27)\n" + "\n".join(
                    n + "\nEU Member State since 1958" for n in names
                )
                runs.append(
                    {
                        "output_payload": {
                            "fetched_results": [
                                {
                                    "url": url,
                                    "provider": "mock",
                                    "content": content,
                                    "content_truncated": self.partial,
                                    "status": "succeeded",
                                    "fetched_at": NOW.isoformat(),
                                }
                            ]
                        }
                    }
                )
            return {"preprocessor_runs": runs}

        self.resolver = EvidenceResolver(
            self.path,
            TelemProvider(
                search_providers=["mock"], fetch_providers=["mock"], transport=transport
            ),
            refresh_enabled=True,
            now=lambda: NOW,
        )

    def test_reviewed_nonmember_names(self):
        result = self.resolver.resolve(["Brazil", "South Africa"])
        self.assertEqual(result["status"], "resolved")
        self.assertTrue(all(not row["member"] for row in result["facts"]))

    def test_refresh_then_hit(self):
        first = self.resolver.resolve(["France"])
        self.assertEqual(first["cache_state"], "refreshed")
        self.assertEqual(len(self.calls), 2)
        second = self.resolver.resolve(["Germany"])
        self.assertEqual(second["cache_state"], "fresh_hit")
        self.assertEqual(len(self.calls), 2)
        self.assertNotIn("France", json.dumps(self.calls[0]))

    def test_reordered_batch_matches_by_url(self):
        original = self.resolver.provider.transport

        def reverse(path, payload):
            data = original(path, payload)
            if path.endswith("fetch"):
                data["preprocessor_runs"].reverse()
            return data

        self.resolver.provider.transport = reverse
        result = self.resolver.resolve(["France"])
        self.assertEqual(result["status"], "resolved")
        self.assertEqual(result["provider_calls"], 2)
        self.assertEqual(self.calls[1][1]["urls"], list(SOURCES))
        self.assertEqual(json.loads(self.path.read_text())["build_api_calls"], 1)

    def test_batch_partial_failure_never_publishes(self):
        original = self.resolver.provider.transport
        for kind in (
            "missing",
            "second_failed",
            "second_truncated",
            "http_error",
            "http_partial",
            "duplicate",
            "unexpected",
        ):
            with self.subTest(kind=kind):

                def broken(path, payload):
                    data = original(path, payload)
                    if path.endswith("fetch"):
                        runs = data["preprocessor_runs"]
                        if kind == "missing":
                            runs.pop()
                        elif kind == "second_failed":
                            runs[1]["error"] = "provider failed"
                        elif kind == "second_truncated":
                            runs[1]["output_payload"]["fetched_results"][0][
                                "content_truncated"
                            ] = True
                        elif kind == "http_error":
                            runs[1]["output_payload"]["fetched_results"][0][
                                "http_status"
                            ] = 503
                        elif kind == "http_partial":
                            runs[1]["output_payload"]["fetched_results"][0][
                                "http_status"
                            ] = 206
                        elif kind == "duplicate":
                            runs[1] = runs[0]
                        else:
                            runs[1]["output_payload"]["fetched_results"][0][
                                "url"
                            ] = "https://example.com"
                    return data

                self.resolver.provider.transport = broken
                self.assertEqual(
                    self.resolver.resolve(["France"])["status"], "unresolved"
                )
                self.assertFalse(self.path.exists())

    def test_unsupported_no_outbound(self):
        for subjects, predicate, date in [
            (["private-company"], "eu_membership", None),
            (["France"], "revenue", None),
            (["France"], "eu_membership", "2020-01-01"),
        ]:
            self.assertEqual(
                self.resolver.resolve(subjects, predicate, date)["status"], "unresolved"
            )
        self.assertEqual(self.calls, [])

    def test_partial_does_not_publish(self):
        self.partial = True
        self.assertEqual(self.resolver.resolve(["France"])["status"], "unresolved")
        self.assertFalse(self.path.exists())

    def test_expired_refresh_failure_preserves_revision(self):
        self.resolver.resolve(["France"])
        data = json.loads(self.path.read_text())
        for source in data["sources"]:
            source["fetched_at"] = (NOW - timedelta(days=2)).isoformat()
        self.path.write_text(json.dumps(data))
        old = self.path.read_bytes()
        self.partial = True
        self.assertEqual(self.resolver.resolve(["France"])["status"], "unresolved")
        self.assertEqual(self.path.read_bytes(), old)

    def test_future_evidence_refreshes(self):
        self.resolver.resolve(["France"])
        data = json.loads(self.path.read_text())
        data["sources"][0]["fetched_at"] = (NOW + timedelta(days=1)).isoformat()
        self.path.write_text(json.dumps(data))
        self.assertEqual(self.resolver.resolve(["France"])["cache_state"], "refreshed")
        self.assertEqual(len(self.calls), 4)

    def test_atomic_failure_preserves_old_file(self):
        self.path.write_text("old revision")
        with patch.object(Path, "replace", side_effect=OSError("disk error")):
            self.assertEqual(self.resolver.resolve(["France"])["status"], "unresolved")
        self.assertEqual(self.path.read_text(), "old revision")

    def test_conflicting_count_rejected(self):
        self.resolver.resolve(["France"])
        data = json.loads(self.path.read_text())
        data["member_count"] = 28
        with self.assertRaises(ValueError):
            self.resolver._validate(data, 24)

    def test_metadata_gap_policy(self):
        from lesser_tokenzz.evidence_resolver import harmless_metadata_gaps

        self.assertTrue(
            harmless_metadata_gaps(
                [{"code": "capability_gap", "message": "cannot supply `cache_state`"}]
            )
        )
        self.assertFalse(
            harmless_metadata_gaps(
                [{"code": "truncated", "message": "partial content"}]
            )
        )

    def test_raw_error_run_cannot_bypass_filtered_hits(self):
        original = self.resolver.provider.transport

        def broken(path, payload):
            result = original(path, payload)
            if path.endswith("fetch"):
                run = result["preprocessor_runs"][0]
                run["error"] = "upstream incomplete"
                run["output_payload"]["fetched_results"][0][
                    "warning"
                ] = "partial content"
            return result

        self.resolver.provider.transport = broken
        self.assertEqual(self.resolver.resolve(["France"])["status"], "unresolved")
        self.assertFalse(self.path.exists())

    def test_invalid_raw_page_shapes_fail_closed(self):
        original = self.resolver.provider.transport
        for kind in ("item_error", "duplicate", "wrong_url", "extra_run"):
            with self.subTest(kind=kind):

                def broken(path, payload):
                    result = original(path, payload)
                    if path.endswith("fetch"):
                        run = result["preprocessor_runs"][0]
                        pages = run["output_payload"]["fetched_results"]
                        if kind == "item_error":
                            pages[0]["error"] = "incomplete"
                        elif kind == "duplicate":
                            pages.append(dict(pages[0]))
                        elif kind == "wrong_url":
                            pages[0]["url"] = SOURCES[1]
                        else:
                            result["preprocessor_runs"].append(dict(run))
                    return result

                self.resolver.provider.transport = broken
                self.assertEqual(
                    self.resolver.resolve(["France"])["status"], "unresolved"
                )
                self.assertFalse(self.path.exists())

    def test_disabled_and_policy(self):
        self.resolver.refresh_enabled = False
        self.assertEqual(
            self.resolver.resolve(["France"])["reason"], "refresh_disabled"
        )
        self.assertEqual(
            self.resolver.resolve(["France"], max_age_hours=25)["status"], "unresolved"
        )
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
