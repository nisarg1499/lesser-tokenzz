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

## 4. Freshness, monitor signals and refresh

The resolver first validates the requested fact scope. If an existing Telem monitor
is configured, it polls that monitor's replayable change stream before cache use.
Semantic events advance a durable invalidation generation; a run-only event does
not. Poll failures return unresolved. The older catalog tools are hidden in monitor
mode so the agent cannot skip this gate.

A cache hit requires complete evidence within the requested age limit and, in
monitor mode, the current monitor generation. TTL is capped at 24 hours and remains
a backup for missed monitor signals. A timestamp does not establish factual truth.

With automatic refresh enabled, missing, expired or invalidated evidence triggers
one constrained Telem search and one batch Fetch request for two fixed official pages. Optional Telem
accuracy routing selects within a bounded provider allowlist. Discovery rankings
are audit metadata, not adaptive fetch selection. Validation precedes atomic save;
failed refreshes remain unresolved rather than serving stale facts as current.

Historical questions, unsupported predicates and unresolved country aliases remain
out of scope. See [architecture](docs/architecture.md) for the complete diagram and
[monitor integration](docs/monitor-invalidation.md) for setup and verification.

## What is reused

We reuse business definitions and a sourced public fact dimension across different questions. We do not reuse final answers or database query results. Business data is queried live. This implementation does not use embedding similarity to decide cache hits, learn from previous answers, or automatically generalize to other public fact types.

## Limits

- The public parser supports the current two-page EU listing format only; page changes can require an adapter update.
- Custom business definitions require human review. Schema validation is not proof of business correctness.
- Exact country-name matching is not entity resolution.
- The agent can still write incorrect SQL or misuse evidence.
- The recorded pilot improvements are a small historical result, not a guarantee. See `docs/results.md` for selection, regressions and measurement boundaries.

## Opt-in configuration

`--auto-refresh-evidence` enables paid refresh inside the resolver. Optional
`--auto-routing accuracy` lets Telem choose within `--search-provider`'s allowlist.
Optional `--telem-monitor-id` adds authenticated polling of an existing reviewed
monitor before cache reuse. It requires automatic refresh and a catalog path; it
does not create recurring monitors or expose a public webhook.

Monitor-mode latency and costs are separate from the earlier monitor-disabled
benchmark. See [results](docs/resolver-results.md) for measurement boundaries.
