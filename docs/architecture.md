# How it works

1. The database catalog tells the agent what fields and business metrics mean. It includes units, dependencies, source fingerprints, and the population over which ranks must be calculated.
2. The Telem builder fetches both pages of an official EU member list. Deterministic parsing checks the page set and member count before saving a catalog.
3. A follow-up question reuses that catalog, then queries the business database live. No extra model summarizes each cache hit.

This is structured fact reuse, not embedding similarity matching or a cache of final answers. Related questions can reuse the same membership dimension even if their SQL, grouping, filters and outputs differ.

## Code map

| Module | Responsibility |
| --- | --- |
| `server.py` | MCP tools and command-line configuration |
| `metric_contract.py` | Reviewed metric expressions, dependencies and original news adapter |
| `metric_executor.py` | Tested structured metric execution helper |
| `metric_executor_compact.py` | Schema-aware compact catalog and optional query inspection helper |
| `sql.py` | Agent-authored read-only SQL with bounded output |
| `telem_provider.py` | Explicit provider selection, authenticated search/fetch, timing and raw provider metadata |
| `search_provider.py` | Provider-neutral response types |
| `eu_catalog.py` | Complete-list parsing, source hashes and 24-hour expiry |
| `catalog_projection.py` | Optional relevant-country evidence projection |
| `build_catalog.py` | Explicit, paid catalog refresh command |

The server uses the metric helpers to describe definitions; it does not expose their compiler as a tool. The agent remains responsible for translating those definitions into correct SQL. This preserves the distinction between providing business context and mechanically enforcing it.

## Trust boundaries

- SQLite opens read-only. The SQL authorizer blocks writes, ATTACH, PRAGMA changes and file/extension functions. Execution has a 10-second progress deadline; row and string previews report truncation.
- Only public official page URLs are sent by the catalog builder. Business rows stay local.
- Credentials come from the environment. The adapter accepts only known Telem base URLs and does not log keys.
- EU evidence has a 24-hour TTL. A stale catalog is not served as current. The parser is intentionally specific to the two official listing pages and fails when the expected shape changes.
- Name projection is case-insensitive exact matching, not entity resolution. An unmatched alias does not prove non-membership.
- The original news adapter pins four reviewed knowledge records and schema fingerprints. Generic JSON contracts are operator-reviewed inputs, not automatically verified business truth.

## Deliberate omissions

No experiment orchestration maze, old candidate approaches, secrets, full benchmark data, raw model traces, or claims of a universal semantic cache. Add a new source adapter only when a concrete use case needs it.
