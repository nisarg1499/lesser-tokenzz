"""Project a complete public fact catalog without returning unrelated evidence."""

import hashlib
import json
from .eu_catalog import read_catalog


def lookup_membership(path, countries):
    """Match supplied names against the complete current EU list, preserving proof."""
    if not isinstance(countries, list) or not 1 <= len(countries) <= 32:
        raise ValueError("Supply 1 to 32 public country names")
    if any(
        not isinstance(name, str) or not name.strip() or len(name) > 80
        for name in countries
    ):
        raise ValueError("Country names must be nonempty bounded strings")
    catalog = read_catalog(path)
    if catalog["status"] != "complete":
        return catalog
    names = {name.casefold(): name for name in catalog["members"]}
    matches = [
        {
            "requested_name": name,
            "matched_member": names.get(name.strip().casefold()),
            "listed_in_complete_eu_list": name.strip().casefold() in names,
        }
        for name in countries
    ]
    positives = {row["matched_member"] for row in matches if row["matched_member"]}
    return {
        "status": "complete",
        "scope": catalog["scope"],
        "member_count": catalog["member_count"],
        "matches": matches,
        "supporting_passages": [
            row for row in catalog["evidence"] if row["country"] in positives
        ],
        "sources": catalog["sources"],
        "built_at": catalog["built_at"],
        "ttl_hours": catalog["ttl_hours"],
        "complete_member_list_sha256": hashlib.sha256(
            json.dumps(catalog["members"]).encode()
        ).hexdigest(),
        "matching_policy": "Case-insensitive exact country-name matching; not semantic similarity. "
        "A missing noncanonical name is not proof of non-membership. "
        "Use canonical country names; no historical classification.",
    }
