"""Validate and serve a full EU membership dimension from real Telem page reads."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

EU_URL = "https://european-union.europa.eu/principles-countries-history/eu-countries_en"


def harmless_metadata_gaps(warnings):
    """Accept only known unavailable metadata, never partial-content warnings."""
    fields = (
        "cache_state",
        "description",
        "http_status",
        "js_rendered",
        "pdf_mode",
        "warning",
    )
    return isinstance(warnings, list) and all(
        isinstance(w, dict)
        and w.get("code") == "capability_gap"
        and any("`" + field + "`" in w.get("message", "") for field in fields)
        for w in warnings
    )


def validate_fetch_response(response, expected_url):
    """Validate the exact raw records consumed by build_catalog, not filtered hits."""
    runs = response.get("preprocessor_runs")
    if not isinstance(runs, list) or len(runs) != 1:
        raise ValueError("ambiguous_fetch_runs")
    run = runs[0]
    if run.get("error") or run.get("warning") or run.get("warnings"):
        raise ValueError("failed_fetch_run")
    pages = (run.get("output_payload") or {}).get("fetched_results")
    if not isinstance(pages, list) or len(pages) != 1:
        raise ValueError("missing_or_duplicate_page")
    page = pages[0]
    if (
        page.get("url") != expected_url
        or page.get("canonical_url", expected_url) != expected_url
        or page.get("error")
        or (
            page.get("http_status") is not None
            and (
                type(page["http_status"]) is not int
                or not 200 <= page["http_status"] < 300
                or page["http_status"] == 206
            )
        )
        or page.get("status") != "succeeded"
        or page.get("warning")
        or not harmless_metadata_gaps(page.get("warnings", []))
        or page.get("content_truncated")
        or not isinstance(page.get("content"), str)
        or not 0 < len(page["content"]) <= 20000
    ):
        raise ValueError("unsafe_or_partial_source")


def split_fetch_batch(response, expected_urls):
    """Match every batch result by URL, never position, before building a catalog."""
    runs = response.get("preprocessor_runs")
    if not isinstance(runs, list) or len(runs) != len(expected_urls):
        raise ValueError("missing_or_extra_batch_runs")
    by_url = {}
    for run in runs:
        pages = (run.get("output_payload") or {}).get("fetched_results")
        if not isinstance(pages, list) or len(pages) != 1:
            raise ValueError("missing_or_duplicate_batch_page")
        url = pages[0].get("url")
        if url not in expected_urls or url in by_url:
            raise ValueError("unexpected_or_duplicate_batch_url")
        single = {"preprocessor_runs": [run]}
        validate_fetch_response(single, url)
        by_url[url] = single
    return [by_url[url] for url in expected_urls]


def build_catalog(responses, build_elapsed_s):
    """Require both complete listing pages and agreement with their stated total."""
    if len(responses) != 2:
        raise ValueError("Exactly two official listing responses are required")
    for response, expected_url in zip(responses, (EU_URL, EU_URL + "?page=1")):
        validate_fetch_response(response, expected_url)
    members, sources, totals = {}, [], set()
    for response in responses:
        for run in response["preprocessor_runs"]:
            for page in (run.get("output_payload") or {}).get("fetched_results", []):
                url = page.get("canonical_url") or page.get("url")
                if url not in (EU_URL, EU_URL + "?page=1"):
                    continue
                if page.get("status") != "succeeded" or page.get("content_truncated"):
                    raise ValueError("Incomplete official source page")
                text = page["content"]
                totals.update(int(n) for n in re.findall(r"Pages\s*\((\d+)\)", text))
                lines = text.splitlines()
                for i, line in enumerate(lines):
                    if line.startswith("EU Member State since ") and i:
                        name = lines[i - 1].strip().removeprefix("the ")
                        if not re.fullmatch(r"[A-Za-z ]{2,40}", name):
                            raise ValueError("Unexpected member label")
                        members[name] = {
                            "country": name,
                            "source_url": url,
                            "passage": line,
                        }
                sources.append(
                    {
                        "url": url,
                        "fetched_at": page["fetched_at"],
                        "provider": page.get("provider"),
                        "content_sha256": hashlib.sha256(text.encode()).hexdigest(),
                    }
                )
    if {s["url"] for s in sources} != {EU_URL, EU_URL + "?page=1"}:
        raise ValueError("Both listing pages are required")
    if len(totals) != 1 or len(members) != next(iter(totals)):
        raise ValueError("Extracted member count does not match official stated total")
    return {
        "status": "complete",
        "scope": "Current EU membership, not historical membership",
        "member_count": len(members),
        "members": sorted(members),
        "evidence": [members[name] for name in sorted(members)],
        "sources": sources,
        "built_at": min(source["fetched_at"] for source in sources),
        "ttl_hours": 24,
        "build_elapsed_s": build_elapsed_s,
        "build_api_calls": len(responses),
        "build_cost_usd": None,
        "measurement": "live Telem fetch; deterministic parsing",
    }


def read_catalog(path, now=None):
    data = json.loads(Path(path).read_text())
    now = now or datetime.now(timezone.utc)
    age = (now - datetime.fromisoformat(data["built_at"])).total_seconds()
    if not 0 <= age <= data["ttl_hours"] * 3600:
        return {
            "status": "stale",
            "instruction": "Refresh official list through Telem before use",
        }
    return data
