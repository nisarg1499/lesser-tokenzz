"""Build the per-question comparison from raw Codex events.

Every number comes from machine-readable events or run metadata. Token counts are
read from `turn.completed.usage`; nothing is inferred from text length. Unknown
values stay empty, never zero.
"""

import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / "runs"
ARMS = ("native", "evidence")
FIELDS = [
    "question_id",
    "kind",
    "arm",
    "label",
    "numeric_match",
    "wall_s",
    "turn_s",
    "web_search_s",
    "external_evidence_tool_s",
    "input_tokens",
    "cached_input_tokens",
    "uncached_input_tokens",
    "output_tokens",
    "eu_cache_state",
    "telem_requests",
    "provider_cost_usd",
    "native_web_search_calls",
    "mcp_calls",
    "shell_commands",
    "errors",
    "tools_used",
]


def load_events(path):
    events = []
    for line in path.read_text().splitlines():
        record = json.loads(line)
        events.append((record["received_at"], json.loads(record["raw"])))
    return events


def numeric_match(answer, reference):
    """True when every reference value and keyword appears in the answer."""
    numbers = [
        float(n) for n in re.findall(r"-?\d+(?:\.\d+)?", answer.replace(",", ""))
    ]
    values_ok = all(
        any(abs(n - value) <= 0.01 for n in numbers) for value in reference["values"]
    )
    keywords_ok = all(
        k.lower() in answer.lower() for k in reference.get("keywords", [])
    )
    return values_ok and keywords_ok


def summarize(question, arm, reference):
    out = RUNS / question["id"]
    meta = json.loads((out / f"{arm}.meta.json").read_text())
    events = load_events(out / f"{arm}.events.jsonl")
    answer_path = out / f"{arm}.answer.txt"
    answer = answer_path.read_text() if answer_path.exists() else ""

    started = {}
    web_s = evidence_s = 0.0
    web_calls = mcp_calls = shell = errors = 0
    telem_requests = 0
    cache_state = ""
    cost = ""
    tools = []
    usage = {}
    first = last = None
    for at, event in events:
        kind = event.get("type")
        item = event.get("item") or {}
        if kind == "thread.started":
            first = at
        if kind == "turn.completed":
            last = at
            usage = event.get("usage", {})
        if kind in ("turn.failed", "error"):
            errors += 1
        if kind == "item.started":
            started[item.get("id")] = at
        if kind != "item.completed":
            continue
        # Duration is observable only when both start and completion were emitted.
        duration = at - started[item["id"]] if item.get("id") in started else 0.0
        if item.get("type") == "web_search":
            web_calls += 1
            web_s += duration
            tools.append("web_search")
        elif item.get("type") == "command_execution":
            shell += 1
        elif item.get("type") == "mcp_tool_call":
            mcp_calls += 1
            tools.append(item.get("tool"))
            if item.get("error") or item.get("status") != "completed":
                errors += 1
            if item.get("tool") in ("resolve_external_fact", "search_public_web"):
                evidence_s += duration
                try:
                    result = json.loads(item["result"]["content"][0]["text"])
                except (KeyError, TypeError, ValueError, IndexError):
                    result = {}
                if item["tool"] == "resolve_external_fact":
                    cache_state = result.get("cache_state", "")
                    telem_requests += result.get("telem_request_count") or 0
                    if result.get("provider_cost_usd") is not None:
                        cost = result["provider_cost_usd"]
                else:
                    # The server reports its own count; a full cache hit sends none.
                    requests = result.get("telem_request_count")
                    telem_requests += 1 if requests is None else requests

    input_tokens = usage.get("input_tokens")
    cached = usage.get("cached_input_tokens")
    # Codex reports cached input as a subset of input; refuse to subtract otherwise.
    uncached = ""
    if input_tokens is not None and cached is not None and cached <= input_tokens:
        uncached = input_tokens - cached
    return {
        "question_id": question["id"],
        "kind": question["kind"],
        "arm": arm,
        "label": meta["label"],
        "numeric_match": numeric_match(answer, reference) if answer else False,
        "wall_s": meta["wall_seconds"],
        "turn_s": round(last - first, 2) if first and last else "",
        "web_search_s": round(web_s, 2) if arm == "native" else "",
        "external_evidence_tool_s": round(evidence_s, 2) if arm == "evidence" else "",
        "input_tokens": input_tokens if input_tokens is not None else "",
        "cached_input_tokens": cached if cached is not None else "",
        "uncached_input_tokens": uncached,
        "output_tokens": usage.get("output_tokens", ""),
        "eu_cache_state": cache_state,
        "telem_requests": telem_requests if arm == "evidence" else "",
        "provider_cost_usd": cost,
        "native_web_search_calls": web_calls,
        "mcp_calls": mcp_calls,
        "shell_commands": shell,
        "errors": errors,
        "tools_used": " ".join(dict.fromkeys(t for t in tools if t)),
    }


def main():
    questions = json.loads((ROOT / "demo" / "questions.json").read_text())["questions"]
    references = json.loads(
        (ROOT / "demo" / "grader_only" / "references.json").read_text()
    )["references"]
    rows = []
    for question in questions:
        for arm in ARMS:
            if (RUNS / question["id"] / f"{arm}.events.jsonl").exists():
                rows.append(summarize(question, arm, references[question["id"]]))
    if not rows:
        sys.exit("no runs found under runs/")
    with (RUNS / "comparison.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    show = FIELDS[:1] + FIELDS[2:3] + FIELDS[4:13] + FIELDS[13:15] + FIELDS[16:20]
    widths = [max(len(f), *(len(str(r[f])) for r in rows)) for f in show]
    for line in [show] + [[str(r[f]) for f in show] for r in rows]:
        print("  ".join(cell.ljust(w) for cell, w in zip(line, widths)))
    print(f"\nWrote {RUNS / 'comparison.csv'} ({len(rows)} runs)")


if __name__ == "__main__":
    main()
