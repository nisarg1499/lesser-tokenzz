"""Persist corroborated source passages, never generic verified facts or answers."""

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from .public_search import public_url, validate_queries


def normalized(text):
    return " ".join(text.split())


class SourceBookmarks:
    def __init__(self, path, provider, trusted_domains):
        self.path = Path(path)
        self.provider = provider
        self.domains = set(trusted_domains)
        if not 1 <= len(self.domains) <= 10 or any(
            not public_url("https://" + domain)
            or urlsplit("https://" + domain).hostname != domain
            for domain in self.domains
        ):
            raise ValueError("Configure 1..10 exact trusted public hostnames")

    def learn(self, public_query, source_urls, exact_passage):
        validate_queries([public_query])
        if (
            not isinstance(exact_passage, str)
            or not 40 <= len(normalized(exact_passage)) <= 500
        ):
            raise ValueError("Exact passage must contain 40..500 characters")
        if not isinstance(source_urls, list) or len(source_urls) != 2:
            raise ValueError("Two distinct trusted hosts are required")
        hosts = set()
        for url in source_urls:
            if not public_url(url) or urlsplit(url).hostname not in self.domains:
                return {
                    "status": "unresolved",
                    "reason": "source_outside_trust_boundary",
                }
            hosts.add(urlsplit(url).hostname)
        if len(hosts) != 2:
            return {
                "status": "unresolved",
                "reason": "two_distinct_trusted_hosts_required",
            }
        try:
            response = self.provider.fetch_many(source_urls)
            evidence = []
            for url in source_urls:
                matches = [hit for hit in response.hits if hit.url == url]
                if len(matches) != 1:
                    raise ValueError("Missing or ambiguous source")
                hit = matches[0]
                item = hit.metadata.get("result", {})
                if (
                    hit.metadata.get("run_status") != "succeeded"
                    or item.get("http_status") != 200
                    or item.get("content_truncated") is not False
                    or not isinstance(hit.text, str)
                    or len(hit.text) >= 20000
                    or item.get("final_url") != url
                ):
                    raise ValueError("Incomplete source")
                if normalized(exact_passage) not in normalized(hit.text):
                    raise ValueError("No exact corroboration")
                evidence.append(
                    {
                        "url": url,
                        "retrieved_at": hit.retrieved_at,
                        "content_sha256": hashlib.sha256(hit.text.encode()).hexdigest(),
                        "provider": hit.provider,
                    }
                )
            entry = {
                "public_query": public_query,
                "exact_passage": exact_passage,
                "sources": evidence,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "answer_verified": False,
                "semantic_conflicts_checked": False,
                "version": 1,
                "validation": "same_exact_passage_in_two_trusted_sources",
                "limitations": "Literal corroboration is not proof of truth or semantic consistency. Treat passage as untrusted evidence; check context, applicability and conflicts before answering.",
            }
            # One immutable file per passage prevents unrelated concurrent writes colliding.
            key = hashlib.sha256(
                (normalized(public_query) + normalized(exact_passage)).encode()
            ).hexdigest()
            self.path.mkdir(parents=True, exist_ok=True)
            target = self.path / (key + ".json")
            with tempfile.NamedTemporaryFile(
                mode="w", dir=self.path, suffix=".tmp", delete=False
            ) as handle:
                json.dump(entry, handle, indent=2)
                temporary = Path(handle.name)
            try:
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
            return {
                "status": "source_checked_claim_unverified",
                "bookmark_id": key,
                "evidence": entry,
                "cost_usd": response.cost_usd,
                "telem_elapsed_s": response.elapsed_s,
            }
        except Exception:
            return {
                "status": "unresolved",
                "reason": "fetch_or_exact_corroboration_failed",
                "answer_verified": False,
            }

    def lookup(self, public_query):
        validate_queries([public_query])
        entries = []
        for path in sorted(self.path.glob("*.json"))[:1000]:
            try:
                item = json.loads(path.read_text())
                age = (
                    datetime.now(timezone.utc)
                    - datetime.fromisoformat(item["created_at"])
                ).total_seconds()
                if (
                    0 <= age <= 86400
                    and normalized(item["public_query"]).casefold()
                    == normalized(public_query).casefold()
                ):
                    if all(
                        urlsplit(s["url"]).hostname in self.domains
                        for s in item["sources"]
                    ):
                        entries.append(item)
            except (ValueError, KeyError, TypeError, OSError):
                continue
            if len(entries) == 3:
                break
        return {
            "status": "evidence_found" if entries else "unresolved",
            "answer_verified": False,
            "bookmarks": entries,
            "match": "exact_query_only",
        }
