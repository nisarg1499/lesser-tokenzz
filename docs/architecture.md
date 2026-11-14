# Architecture

Codex plans the work and writes SQL. The MCP supplies reviewed business definitions,
live read-only database access, and reusable public evidence. There is no hidden
manager LLM and no cache of final answers.

## Complete request path

```mermaid
flowchart TD
    U[Business question] --> A[Codex: plan and write SQL]
    A --> B[get_metric_contracts]
    B --> BC[(Reviewed business definitions and schema)]
    BC --> A
    A --> Q[run_sql: bounded read-only execution]
    Q --> DB[(Live business database)]
    DB --> A
    A --> R[resolve_external_fact: supported EU request]
    R --> L[Acquire local catalog lock]
    L --> M{Monitor configured?}
    M -- No --> C{Complete catalog within TTL?}
    M -- Yes --> P[Authenticated poll of configured Telem monitor]
    P --> V{Valid binding and readable change stream?}
    V -- No --> X[Unresolved: do not serve cached evidence]
    V -- Yes --> G[Persist cursor and invalidation generation]
    G --> C
    C -- Fresh and generation matches --> H[Project requested facts and citations]
    C -- Missing, expired, or invalidated --> S[Telem Search: bounded provider policy]
    S --> RT[Optional Telem accuracy provider routing]
    RT --> D[Reviewed-source discovery audit]
    D --> F[Telem batch Fetch: two official pages in one request]
    F --> E{Complete and valid evidence?}
    E -- No --> X
    E -- Yes --> W[Atomically save catalog with monitor generation]
    W --> H
    H --> A
    X --> A
    A --> PS[Optional search_public_web: unsupported public facts]
    PS --> BS[Telem batch Search: 1 to 3 public queries]
    BS --> US[Bounded untrusted snippets with per-query citations or unresolved]
    US --> A
    A --> SB[Optional source bookmark: two vetted fetched sources]
    SB --> SC{Complete metadata and exact shared passage?}
    SC -- No --> SU[Unresolved: no save]
    SC -- Yes --> SP[(Atomic source passage record: claim unverified)]
    SP --> SL[Exact-query lookup within 24 hours]
    SL --> A
    A --> O[Answer using live data and source-backed facts]
    TM[Telem scheduled monitor] --> CS[(Telem change stream)]
    CS --> P
```

The diagram shows the optional monitor path. Without a configured monitor, TTL is
the freshness gate. With a monitor, each supported resolver request polls it before
reading cached evidence. This is **poll-on-access**, not an incoming webhook or a
background worker inside the MCP.

## What happens in each component

1. **Business catalog:** returns formulas, units, dependencies and population rules.
   It does not fetch business rows or prove that the agent's SQL follows those rules.
2. **Database tool:** executes agent-authored read-only SQLite SQL with a timeout,
   bounded rows and explicit truncation. Business data remains live.
3. **Evidence resolver:** accepts current EU membership and reviewed country names.
   A valid warm entry returns only requested facts, passages and provenance.
4. **Telem retrieval:** refresh uses a public query and fixed official source family.
   Optional accuracy routing lets Telem select within the provider allowlist.
   Candidate RRF is audit metadata; it does not choose which pages are fetched.
5. **Validation and persistence:** both complete official listing pages and the
   reviewed 27-member set are required. Valid evidence is saved atomically, with a
   revision hash and retrieval time. A changed member set requires review.
6. **Monitor invalidation:** a configured monitor supplies a change signal, not new
   fact evidence. Relevant stream events advance a durable generation. Evidence
   saved under an older generation is unusable until refreshed and validated.

## Monitor state and failure handling

```mermaid
stateDiagram-v2
    [*] --> Unbound
    Unbound --> NeedsRefresh: First valid monitor poll
    Current --> NeedsRefresh: New semantic event or TTL expiry
    Current --> Current: Successful poll with no new semantic event
    NeedsRefresh --> Current: Official-source refresh validates and saves generation
    NeedsRefresh --> Unresolved: Refresh or validation fails
    Current --> Unresolved: Monitor poll fails
    Unresolved --> NeedsRefresh: Next poll succeeds but evidence is expired or invalidated
    Unresolved --> Current: Next poll succeeds and evidence remains valid
```

The local `.monitor.json` sidecar stores monitor ID, cursor and generation. Cursor
updates are persisted before refresh. Replayed old events do not invalidate again.
A shared file lock serializes polling and refresh among cooperating local server
processes. This is not a distributed lock across independent hosts or filesystems.

Monitor mode hides the legacy full-list and projection tools so an agent cannot
bypass the monitor gate. An inactive or mismatched monitor, malformed stream,
excessive backlog, or polling outage returns `unresolved`. It does not fall back to
serving a cached fact merely because its TTL has not expired.

## Trust boundaries and limits

- Telem receives the fixed public query and official URLs, not private business rows
  or the user's full question. Credentials come from the environment and are not logged.
- Monitor requests authenticate to an approved Telem origin. No public webhook
  endpoint is exposed in this implementation.
- TTL remains a backup when a monitor misses a change. A monitor notification is
  not proof a fact changed, and an absence of notifications is not proof it did not.
- Detection is delayed by the monitor schedule and polling. A change can occur
  after a poll. Neither this feature nor a fresh retrieval guarantees zero stale data.
- Current external-fact coverage is EU membership only. The cache is trusted local
  operator state, not a tenant-isolated enterprise store.
- Monitor polling adds API calls even on warm hits. Earlier zero-call warm results
  measured monitor-disabled operation; do not reuse them as monitor-mode results.

## Implementation map

| Module | Role |
| --- | --- |
| `server.py` | MCP tools and opt-in configuration |
| `metric_contract.py` | Reviewed metric definitions and original-source checks |
| `sql.py` | Read-only SQL execution and result limits |
| `evidence_resolver.py` | Freshness, refresh, validation and evidence projection |
| `monitor_invalidation.py` | Authenticated polling, durable cursor/generation, local file lock |
| `telem_provider.py` | Bounded Telem search/fetch and optional provider routing |
| `discovery_audit.py` | Candidate deduplication, provenance and audit-only RRF |
| `eu_catalog.py` | Official-page parsing, source hashes and TTL |

See [monitor setup and verification](monitor-invalidation.md),
[measured resolver results](resolver-results.md), and [routing guide](telem-routing.md).

## Unsupported public facts

The opt-in [public web fallback](public-web-fallback.md) is agent-driven, not an
automatic widening of the EU resolver. It batches independent public queries and
returns unverified source snippets. It never writes into the reviewed EU cache.
