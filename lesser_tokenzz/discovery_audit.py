"""Compact, inspectable source selection; ranking is not proof of truth."""

from urllib.parse import urlsplit, urlunsplit


def discovery_audit(response, supported_urls):
    """Fuse provider order using RRF, retaining only reviewed parser-compatible URLs.

    A provider votes once per URL. Other results are counted but never fetched.
    Telem chooses providers; this local deterministic step ranks their URLs.
    """
    def canonical(url):
        parts = urlsplit(url)
        return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip('/'), parts.query, ''))

    supported = {canonical(url) for url in supported_urls}
    by_provider = {}
    candidates = {}
    rejected = 0
    for hit in response.hits:
        url = canonical(hit.url)
        seen = by_provider.setdefault(hit.provider, set())
        if url in seen:
            continue
        seen.add(url)
        rank = len(seen)
        if url not in supported:
            rejected += 1
            continue
        row = candidates.setdefault(url, {"url": url, "rrf_score": 0.0, "providers": []})
        row["rrf_score"] += 1 / (60 + rank)
        row["providers"].append({"provider": hit.provider, "rank": rank})
    ordered = sorted(candidates.values(), key=lambda row: (-row['rrf_score'], row['url']))
    for row in ordered:
        row['rrf_score'] = round(row['rrf_score'], 8)
    raw = response.usage.get('response', {})
    return {
        "selection_policy": "Reviewed source family, then reciprocal rank fusion (k=60)",
        "selected_sources": ordered,
        "rejected_result_count": rejected,
        "routing": [{"providers": r.get('providers', [])} for r in raw.get('routing') or []],
        "routing_unavailable": any(
            'routing_unavailable' in str(run.get('warnings', []))
            for run in raw.get('preprocessor_runs', [])
        ),
    }
