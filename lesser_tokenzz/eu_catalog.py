"""Validate and serve a full EU membership dimension from real Telem page reads."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

EU_URL = "https://european-union.europa.eu/principles-countries-history/eu-countries_en"


def build_catalog(responses, build_elapsed_s):
    """Require both complete listing pages and agreement with their stated total."""
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
