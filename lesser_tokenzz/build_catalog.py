"""Fetch two official listing pages through Telem and validate before saving."""

import argparse
import json
from pathlib import Path
import time

from .eu_catalog import EU_URL, build_catalog
from .telem_provider import TelemProvider


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--fetch-provider", required=True, help="An enabled Telem fetch provider"
    )
    args = parser.parse_args()
    # Provider selection is explicit to avoid accidental multi-provider fan-out.
    provider = TelemProvider(
        search_providers=["brave"], fetch_providers=[args.fetch_provider]
    )
    started = time.perf_counter()
    responses = [
        provider.fetch(url).usage["response"] for url in (EU_URL, EU_URL + "?page=1")
    ]
    catalog = build_catalog(responses, time.perf_counter() - started)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(json.dumps(catalog, indent=2) + "\n")
    temporary.replace(args.output)
    print(
        f"Saved {catalog['member_count']} members; build took {catalog['build_elapsed_s']:.2f}s"
    )


if __name__ == "__main__":
    main()
