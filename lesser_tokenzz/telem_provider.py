"""Optional real Telem adapter; injected transports are MOCKS, never live evidence."""

import json
import os
import time
from datetime import datetime, timezone
from urllib.request import Request, HTTPRedirectHandler, build_opener
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from .search_provider import SearchHit, SearchResponse


class _NoRedirect(HTTPRedirectHandler):
    """Never forward an authorization header to a redirected destination."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


MAX_RESPONSE_BYTES = 262144


def read_response(response):
    """Bound raw JSON bytes before parsing or allocating provider content."""
    raw = response.read(MAX_RESPONSE_BYTES + 1)
    if len(raw) > MAX_RESPONSE_BYTES:
        raise TelemRequestError("Telem response exceeds byte limit")
    return json.loads(raw)


class TelemUnavailable(RuntimeError):
    pass


class TelemRequestError(RuntimeError):
    def __init__(self, message, status=None, elapsed_s=None):
        super().__init__(message)
        self.status, self.elapsed_s, self.cost_usd = status, elapsed_s, None


def providers(values):
    if (
        not isinstance(values, (list, tuple))
        or not values
        or any(not isinstance(v, str) or not v.strip() for v in values)
    ):
        raise ValueError("Explicit nonempty provider list required; no default fan-out")
    return list(dict.fromkeys(v.strip().lower() for v in values))


class TelemProvider:
    name = "telem"

    def __init__(
        self,
        *,
        search_providers,
        fetch_providers,
        tier="default",
        timeout_s=60,
        transport=None,
        auto_routing=None,
    ):
        self.search_providers, self.fetch_providers = providers(
            search_providers
        ), providers(fetch_providers)
        if tier not in ("minimalist", "default", "extended", "max"):
            raise ValueError("Invalid tier")
        if timeout_s <= 0:
            raise ValueError("Invalid timeout")
        if auto_routing not in (None, "accuracy"):
            raise ValueError("auto_routing must be None or accuracy")
        self.auto_routing = auto_routing
        self.tier, self.timeout_s, self.transport = tier, timeout_s, transport

    def _call(self, path, payload, fetch=False):
        start = time.perf_counter()
        if self.transport is not None:
            data = self.transport(path, payload)
        else:
            key = os.environ.get("TELEM_API_KEY")
            if not key:
                raise TelemUnavailable("TELEM_API_KEY not configured; no request sent")
            base = os.environ.get("TELEM_BASE_URL", "https://hack.telem.ai/api").rstrip(
                "/"
            )
            if base not in (
                "https://router.telem.ai",
                "https://hack.telem.ai/api/router",
                "https://hack.telem.ai/api",
            ):
                raise TelemUnavailable(
                    "Unapproved Telem base URL; no credential transmitted"
                )
            request = Request(
                base + path,
                data=json.dumps(payload).encode(),
                headers={
                    "Authorization": "Bearer " + key,
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            try:
                with build_opener(_NoRedirect()).open(
                    request, timeout=self.timeout_s
                ) as response:
                    data = read_response(response)
            except HTTPError as e:
                raise TelemRequestError(
                    "Telem HTTP error", e.code, time.perf_counter() - start
                ) from None
            except (URLError, TimeoutError, ValueError):
                raise TelemRequestError(
                    "Telem transport/JSON error", elapsed_s=time.perf_counter() - start
                ) from None
        elapsed = time.perf_counter() - start
        if not isinstance(data, dict) or not isinstance(
            data.get("preprocessor_runs"), list
        ):
            raise TelemRequestError("Malformed Telem response", elapsed_s=elapsed)
        now = datetime.now(timezone.utc).isoformat()
        hits = []
        for run in data["preprocessor_runs"]:
            if not isinstance(run, dict):
                continue
            output = run.get("output_payload") or {}
            if not isinstance(output, dict):
                continue
            items = output.get("fetched_results" if fetch else "results", [])
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                if (
                    run.get("error")
                    or item.get("error")
                    or (fetch and item.get("status") != "succeeded")
                ):
                    continue
                provider = (
                    item.get("provider") if fetch else run.get("preprocessor_name")
                )
                hits.append(
                    SearchHit(
                        item.get("title") or "",
                        item.get("url") or "",
                        item.get("content") or item.get("summary") or "",
                        item.get("fetched_at") or now,
                        provider or "unknown",
                        {
                            "result": item,
                            "run_latency_ms": run.get("latency_ms"),
                            "batch_index": run.get("batch_index"),
                            "run_status": run.get("status"),
                        },
                    )
                )
        # Preserve full per-provider records: failures, latency, usage and any billing
        # fields. Published API examples do not promise invoice totals; never guess.
        return SearchResponse(
            hits,
            elapsed,
            self.name,
            cost_usd=None,
            billable_units=None,
            usage={
                "live": self.transport is None,
                "measurement": "live" if self.transport is None else "mock",
                "response": data,
                "cost_status": "unreconciled; consult provider billing",
                "search_providers": self.search_providers,
                "fetch_providers": self.fetch_providers,
            },
        )

    def search(self, query, *, limit=10, include_domains=None):
        if not isinstance(query, str) or not query.strip():
            raise ValueError("Nonempty query required")
        if type(limit) is not int or not 1 <= limit <= 20:
            raise ValueError("limit must be 1..20 per provider")
        options = {
            "providers": {"include": self.search_providers},
            "num_results": limit,
            "tier": self.tier,
        }
        if self.auto_routing:
            options["auto_routing"] = self.auto_routing
        if include_domains:
            options["include_domains"] = list(include_domains)
        return self._call(
            "/v1/search", {"user_input": {"query": query}, "search": options}
        )

    def search_many(self, queries, *, limit=3):
        """One native batch request; retain batch_index and provider failures."""
        if not isinstance(queries, list) or not 1 <= len(queries) <= 3:
            raise ValueError("search_many requires 1..3 queries")
        if any(
            not isinstance(q, str) or not q.strip() or len(q) > 500 for q in queries
        ):
            raise ValueError("Queries must be nonempty and at most 500 characters")
        if type(limit) is not int or not 1 <= limit <= 5:
            raise ValueError("limit must be 1..5")
        options = {
            "providers": {"include": self.search_providers},
            "num_results": limit,
            "tier": self.tier,
        }
        if self.auto_routing:
            options["auto_routing"] = self.auto_routing
        return self._call(
            "/v1/search",
            {"user_input": [{"query": q} for q in queries], "search": options},
        )

    def fetch(self, url):
        return self.fetch_many([url])

    def fetch_many(self, urls):
        """Read up to five distinct pages in one native Telem request."""
        if not isinstance(urls, (list, tuple)) or not 1 <= len(urls) <= 5:
            raise ValueError("fetch_many requires 1..5 URLs")
        if any(not isinstance(url, str) for url in urls) or len(set(urls)) != len(urls):
            raise ValueError("Distinct string URLs required")
        for url in urls:
            p = urlsplit(url)
            if (
                p.scheme not in ("http", "https")
                or not p.hostname
                or p.username
                or p.password
            ):
                raise ValueError("HTTP(S) URL without embedded credentials required")
        return self._call(
            "/v1/fetch",
            {
                "urls": list(urls),
                "options": {
                    "providers": self.fetch_providers,
                    "content_format": "text",
                    "inline_max_chars": 20000,
                    "no_cache": True,
                },
            },
            fetch=True,
        )
