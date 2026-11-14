# Algorithm

## Goal

Answer related questions over live business data and public facts without rediscovering the same definitions and evidence each time. The MCP supplies reusable context; the agent still reasons about the question and writes SQL.

## 1. Load the business catalog

**Inputs:** a SQLite database and reviewed metric definitions.

At startup, read the table schema and metric configuration. Definitions include field mappings, formulas, units, dependencies, and the population used for ranks or percentiles. The original news adapter checks approved source fingerprints; custom contract JSON is trusted operator input.

**Output:** `get_metric_contracts` returns that catalog, not business rows or answers. The agent uses it to write SQL. For example, a percentile defined over all sessions must be computed before filtering to a country. The server describes this rule; it does not prove that agent-written SQL follows it.

## 2. Build the public fact catalog once

**Inputs:** a Telem API key and an explicitly selected fetch provider.

The separate build command fetches two fixed official EU membership listing pages through Telem. It extracts country names and membership passages, requires both complete pages, and checks that the extracted count matches the pages' stated total. If validation fails, it does not publish a replacement catalog.

**Output:** a local catalog with members, short supporting passages, source URLs, retrieval times, content hashes, a 24-hour TTL, and measured build time. Provider cost remains unknown unless measured separately. This is deterministic extraction, not an extra LLM call.

## 3. Answer a follow-up question

1. The client sends its question to the agent.
2. The agent reads the business catalog and, when needed, the public fact catalog.
3. The agent combines the metric rules and relevant countries into SQL.
4. `run_sql` executes against the live database in read-only mode.
5. The agent interprets the result and cites the public sources supporting its classification.

The default public tool returns the full EU list. Optional projection returns matches and supporting passages for requested country names. Both use the same validated catalog. SQL results have a timeout, a row cap, and explicit string/row truncation indicators; the agent must narrow or aggregate a query if the preview is insufficient.

## 4. Freshness and fallback

Every public catalog read checks its age. A future-dated or expired catalog returns `stale` with a refresh instruction, rather than presenting old membership as current. Refresh is an explicit build command, not an automatic paid request inside the MCP server.

The server has no automatic web-search fallback. If a question needs an uncovered fact, historical membership, or an unresolved country alias, the agent must use an independently configured search tool or report that it cannot verify the fact. A missing name is not proof of non-membership. Callers must not silently treat stale or out-of-scope evidence as an answer.

## What is reused

We reuse business definitions and a sourced public fact dimension across different questions. We do not reuse final answers or database query results. Business data is queried live. This implementation does not use embedding similarity to decide cache hits, learn from previous answers, or automatically generalize to other public fact types.

## Limits

- The public parser supports the current two-page EU listing format only; page changes can require an adapter update.
- Custom business definitions require human review. Schema validation is not proof of business correctness.
- Exact country-name matching is not entity resolution.
- The agent can still write incorrect SQL or misuse evidence.
- The recorded pilot improvements are a small historical result, not a guarantee. See `docs/results.md` for selection, regressions and measurement boundaries.

## Opt-in automatic evidence refresh

`resolve_external_fact` now checks scoped current EU evidence and can rebuild it
when missing or stale. With `--auto-refresh-evidence`, one constrained Telem search
must find the supported official listing, then two bounded page fetches supply the
complete source set. Validation precedes atomic publication; failures remain
unresolved. Related requests reuse the validated facts, not prior SQL or answers.
See [implementation and live smoke](docs/evidence-refresh.md). Automatic provider
routing and general fact extraction remain future work.
