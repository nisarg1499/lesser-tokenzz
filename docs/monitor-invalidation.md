# Monitor-driven evidence invalidation

## Delivery status

The optional integration is implemented locally. The implementation worker reports
74 passing offline tests, including restart/replay, scope checks, invalidation,
refresh failure and polling outages. Independent review and live integration checks
remain separate.
A recurring live monitor has **not** been created or verified as part of this change.
Do not describe offline tests or authenticated read-only API checks as a working
scheduled production monitor. Update this section with the final verified results
before publication.

## Purpose

A timer alone cannot notice a source change early. A configured Telem Monitor can
supply a change signal. We mark its evidence generation invalid, then refresh and
validate official source content on the next resolver request. The signal is not
used as the replacement answer.

## Setup

This integration consumes an **existing** monitor. It does not automatically create
paid recurring work. Its query must match the reviewed query exactly:

```text
Watch changes to current European Union membership on european-union.europa.eu official member country listing.
```

The monitor must be active with `agent_state.status` set to `ready`, and expose the replayable agent change
stream. Confirm this is supported for the event endpoint and account before use.
Operator setup must bound any recurring monitor's lifetime and cost.

Start the MCP with its existing database/contracts arguments plus:

```sh
--eu-catalog data/eu.json --auto-refresh-evidence --telem-monitor-id MONITOR_ID
```

Use `TELEM_API_KEY` from the environment. Keep keys, monitor state and generated
catalogs out of Git. The monitor and fact catalog must share the same reviewed scope.
Changing the bound monitor ID requires an operator-reviewed state migration.

## Read path

1. Acquire a catalog-specific local file lock.
2. Read monitor metadata and verify ID, exact query, active status and ready agent state.
3. Read `/agent/changes` from the durable cursor, up to ten pages of 200 events.
4. `entity_added`, `value_changed`, `fact_status_changed`, `alert`, and `plan_changed`
   invalidate the evidence generation. A `run` event alone does not.
5. Atomically persist cursor and generation before attempting refresh.
6. Require both valid TTL and matching monitor generation before serving a cache hit.
7. If invalidated, refresh through Telem Search/Fetch and validate the complete source
   set before saving evidence with the new generation. Failure returns `unresolved`.

The first poll establishes a generation, so an older catalog without that binding
is refreshed rather than assumed to have incorporated earlier events. Duplicate
stream deliveries are handled by the cursor; the integration does not consume the
separate destructive `get_new_results` queue. There is no webhook endpoint.

## What this does not guarantee

Monitor schedules, provider coverage and outages can delay or miss changes. The
check happens when the resolver is called, not continuously inside the MCP. TTL is
still enforced, and polling failures fail closed. Even a successful poll cannot
prove that the source has not changed since that poll.

Every warm monitor-enabled query adds authenticated metadata/change-stream reads.
This overhead has not yet been measured in an end-to-end benchmark. Prior resolver
latency/token results exclude monitor polling and remain separate.

The EU validator deliberately requires the reviewed 27-member list. A real change
to membership will invalidate the cache, but a new list will require adapter review
before it can become a valid answer.
