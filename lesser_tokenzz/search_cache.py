"""Opt-in 24-hour reuse of public search snippets across questions.

This caches untrusted search evidence, never answers or database results. A hit
saves a provider request; it does not verify the claim. Matching is a conservative
normalized-keyword comparison, not semantic retrieval.
"""

import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

MAX_TTL_HOURS = 24
MAX_ENTRIES = 500
# Filler words carry no fact identity; entities and predicates are kept.
STOPWORDS = frozenset(
    "a an and are as at by current currently do does for from in is it its list "
    "now of on or that the their this to today use used uses using what which "
    "who whose with".split()
)


def query_tokens(query):
    """Reduce a query to its identifying keywords, independent of word order."""
    text = re.sub(r"\bsite:\S+", " ", query.lower())
    tokens = set()
    for word in re.findall(r"[a-z0-9]+", text):
        if word in STOPWORDS or re.fullmatch(r"(?:19|20)\d\d", word):
            continue
        # Light plural folding only: "countries" and "country" name the same thing.
        if len(word) > 4 and word.endswith("ies"):
            word = word[:-3] + "y"
        elif len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
            word = word[:-1]
        tokens.add(word)
    return frozenset(tokens)


def same_topic(left, right):
    """Equal keyword sets, or one contains the other with only minor extra words.

    Swapping one entity for another changes both sides, so "canada currency" never
    matches "france currency". Returns a similarity in (0, 1] or None.
    """
    if not left or not right:
        return None
    if left == right:
        return 1.0
    small, large = sorted((left, right), key=len)
    if small <= large and len(small) >= 3 and len(small) / len(large) >= 0.6:
        return round(len(small) / len(large), 2)
    return None


class PublicSearchCache:
    def __init__(self, directory, ttl_hours=MAX_TTL_HOURS, clock=None):
        if not 0 < ttl_hours <= MAX_TTL_HOURS:
            raise ValueError("Search cache TTL must be within 24 hours")
        self.directory = Path(directory)
        self.ttl = timedelta(hours=ttl_hours)
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def lookup(self, query, max_results):
        """Return the freshest matching entry, or None. Corrupt or stale is a miss."""
        tokens = query_tokens(query)
        now = self.clock()
        best = None
        try:
            paths = sorted(self.directory.glob("*.json"))[:MAX_ENTRIES]
        except OSError:
            return None
        for path in paths:
            try:
                entry = json.loads(path.read_text())
                cached_at = datetime.fromisoformat(entry["cached_at"])
                evidence = entry["evidence"]
                similarity = same_topic(tokens, frozenset(entry["tokens"]))
                if similarity is None or not isinstance(evidence, list) or not evidence:
                    continue
                # Expired or future-dated evidence is never served as current.
                if not timedelta(0) <= now - cached_at <= self.ttl:
                    continue
                # A smaller cached result cannot satisfy a larger request.
                if entry["max_results"] < max_results:
                    continue
            except (OSError, ValueError, KeyError, TypeError):
                continue
            if best is None or (similarity, cached_at) > (best[0], best[1]):
                best = (similarity, cached_at, entry)
        if best is None:
            return None
        similarity, cached_at, entry = best
        return {
            "evidence": entry["evidence"][:max_results],
            "provider_runs": entry.get("provider_runs", []),
            "cache": {
                "state": "hit",
                "matched_query": entry["query"],
                "similarity": similarity,
                "cached_at": entry["cached_at"],
                "age_s": round((now - cached_at).total_seconds(), 1),
                "expires_at": (cached_at + self.ttl).isoformat(),
            },
        }

    def store(self, query, max_results, evidence, provider_runs):
        """Persist one successful query group atomically; failures are not cached."""
        tokens = query_tokens(query)
        if not tokens or not evidence:
            return False
        entry = {
            "query": query,
            "tokens": sorted(tokens),
            "max_results": max_results,
            "cached_at": self.clock().isoformat(),
            "evidence": [
                {
                    **item,
                    "snippet_sha256": hashlib.sha256(
                        item["snippet"].encode()
                    ).hexdigest(),
                }
                for item in evidence
            ],
            "provider_runs": provider_runs,
            "claim_status": "unverified_search_snippets",
        }
        name = hashlib.sha256(" ".join(entry["tokens"]).encode()).hexdigest()[:32]
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            handle, temporary = tempfile.mkstemp(dir=self.directory, suffix=".tmp")
            with os.fdopen(handle, "w") as stream:
                json.dump(entry, stream)
            os.replace(temporary, self.directory / f"{name}.json")
        except OSError:
            # A failed write must not fail the search; the fresh result is still valid.
            return False
        return True
