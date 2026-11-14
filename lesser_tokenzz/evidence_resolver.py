"""Bounded public-only EU evidence refresh; no private question enters retrieval."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import time

from .discovery_audit import discovery_audit

from .eu_catalog import (
    EU_URL,
    build_catalog,
    harmless_metadata_gaps,
    validate_fetch_response,
)

# Reviewed canonical names, not an unrestricted free-text search interface.
COUNTRIES = set(
    "Austria|Belgium|Bulgaria|Croatia|Cyprus|Czechia|Denmark|Estonia|Finland|France|Germany|Greece|Hungary|Ireland|Italy|Latvia|Lithuania|Luxembourg|Malta|Netherlands|Poland|Portugal|Romania|Slovakia|Slovenia|Spain|Sweden|United Kingdom|Norway|Switzerland|United States|Canada|Australia|Japan|China|India|Singapore|Brazil|South Africa".split(
        "|"
    )
)
REVIEWED_MEMBERS = set(
    "Austria|Belgium|Bulgaria|Croatia|Cyprus|Czechia|Denmark|Estonia|Finland|France|Germany|Greece|Hungary|Ireland|Italy|Latvia|Lithuania|Luxembourg|Malta|Netherlands|Poland|Portugal|Romania|Slovakia|Slovenia|Spain|Sweden".split(
        "|"
    )
)


SOURCES = (EU_URL, EU_URL + "?page=1")
QUERY = "current European Union EU countries complete member states official list"


class EvidenceResolver:
    """One process-local single-flight resolver. Disk files are trusted operator state."""

    def __init__(self, path, provider, *, refresh_enabled=False, now=None):
        self.path, self.provider = Path(path), provider
        self.refresh_enabled = refresh_enabled
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.lock = threading.Lock()

    def _validate(self, data, max_age_hours):
        if data.get("status") != "complete" or data.get("member_count") != 27:
            raise ValueError("unreviewed_membership_change")
        if data.get("scope") != "Current EU membership, not historical membership":
            raise ValueError("unsupported_scope")
        if set(data["members"]) != REVIEWED_MEMBERS:
            raise ValueError("invalid_members")
        if {s["url"] for s in data["sources"]} != set(SOURCES):
            raise ValueError("invalid_sources")
        for source in data["sources"]:
            digest = source.get("content_sha256", "")
            if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                raise ValueError("missing_source_hash")
            age = (
                self.now() - datetime.fromisoformat(source["fetched_at"])
            ).total_seconds()
            if not 0 <= age <= max_age_hours * 3600:
                raise ValueError("stale_or_future_evidence")
        if any(
            e.get("source_url") not in SOURCES or not e.get("passage")
            for e in data["evidence"]
        ):
            raise ValueError("invalid_evidence_reference")
        if {e["country"] for e in data["evidence"]} != set(data["members"]):
            raise ValueError("incomplete_evidence")

    def _load(self, max_age_hours):
        try:
            data = json.loads(self.path.read_text())
            self._validate(data, max_age_hours)
            return data
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def _save(self, data):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Keep the last revision for inspection; a failed refresh never replaces it.
        if self.path.exists():
            previous = self.path.read_bytes()
            revision = hashlib.sha256(previous).hexdigest()
            history = self.path.parent / (self.path.name + ".history")
            history.mkdir(exist_ok=True)
            (history / (revision + ".json")).write_bytes(previous)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", dir=self.path.parent, delete=False
            ) as file:
                temporary = Path(file.name)
                json.dump(data, file, indent=2)
            temporary.replace(self.path)
        finally:
            if temporary and temporary.exists():
                temporary.unlink()

    def resolve(
        self, subjects, predicate="eu_membership", as_of=None, max_age_hours=24
    ):
        """Only supported public country names and today's membership are accepted."""
        if (
            predicate != "eu_membership"
            or as_of not in (None, self.now().date().isoformat())
            or type(max_age_hours) not in (int, float)
            or not 0 < max_age_hours <= 24
            or not isinstance(subjects, list)
            or not 1 <= len(subjects) <= 32
            or any(not isinstance(s, str) or s not in COUNTRIES for s in subjects)
        ):
            return {"status": "unresolved", "reason": "unsupported_scope_or_subject"}
        started = time.perf_counter()
        calls = 0
        provider_runs = 0
        with self.lock:
            data = self._load(max_age_hours)
            state = "fresh_hit"
            if data is None:
                if not self.refresh_enabled:
                    return {"status": "unresolved", "reason": "refresh_disabled"}
                state = "refreshed"
                try:
                    calls += 1
                    discovery = self.provider.search(
                        QUERY, limit=3, include_domains=["european-union.europa.eu"]
                    )
                    provider_runs += len(discovery.usage["response"].get("preprocessor_runs", []))
                    # The parser supports this source family only. Other official pages
                    # are not automatically interchangeable evidence.
                    selection = discovery_audit(discovery, SOURCES)
                    if not any(row["url"] == EU_URL for row in selection["selected_sources"]):
                        raise ValueError("supported_source_not_discovered")
                    responses = []
                    for url in SOURCES:
                        calls += 1
                        result = self.provider.fetch(url)
                        raw = result.usage["response"]
                        provider_runs += len(raw.get("preprocessor_runs", []))
                        validate_fetch_response(raw, url)
                        responses.append(raw)
                    data = build_catalog(responses, time.perf_counter() - started)
                    for source in data["sources"]:
                        source["metadata_limitations"] = [
                            w
                            for response in responses
                            for run in response["preprocessor_runs"]
                            for page in (run.get("output_payload") or {}).get(
                                "fetched_results", []
                            )
                            if page.get("url") == source["url"]
                            for w in page.get("warnings", [])
                        ]
                    self._validate(data, max_age_hours)
                    data["discovery"] = {
                        "query": QUERY,
                        "sources": list(SOURCES),
                        "policy": "exact official listing family",
                        "provider_calls": calls,
                        "provider_runs": provider_runs,
                        **selection,
                    }
                    self._save(data)
                except Exception:
                    # No provider payload or exception text may leak credentials.
                    return {
                        "status": "unresolved",
                        "reason": "refresh_or_validation_failed",
                        "provider_calls": calls,
                        "elapsed_s": round(time.perf_counter() - started, 3),
                    }
            revision = hashlib.sha256(
                json.dumps(data, sort_keys=True).encode()
            ).hexdigest()
            evidence = {row["country"]: row for row in data["evidence"]}
            return {
                "status": "resolved",
                "cache_state": state,
                "predicate": predicate,
                "facts": [
                    {
                        "subject": s,
                        "member": s in data["members"],
                        "support": evidence.get(
                            s,
                            {
                                "source_urls": list(SOURCES),
                                "basis": "absent from complete validated list",
                            },
                        ),
                    }
                    for s in subjects
                ],
                "sources": [
                    {k: v for k, v in source.items() if k != "metadata_limitations"}
                    for source in data["sources"]
                ],
                "provider_metadata_incomplete": any(
                    source.get("metadata_limitations") for source in data["sources"]
                ),
                "discovery": data.get("discovery", {}) if state == "refreshed" else None,
                "revision": revision,
                "max_age_hours": max_age_hours,
                "provider_calls": calls,
                "elapsed_s": round(time.perf_counter() - started, 3),
                "telem_request_count": calls,
                "provider_run_count": provider_runs,
                "provider_cost_usd": None,
                "freshness_note": "Retrieval TTL is not proof of source accuracy; current membership only.",
            }
