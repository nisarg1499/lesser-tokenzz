# Agent integration fixes

The first end-to-end run found gaps that unit smoke tests did not cover. Keep those failed traces: they are not measurements of a successfully invoked new resolver.

- `resolve_external_fact.predicate` now advertises the only supported value, `eu_membership`, as a JSON Schema constant. Other predicates remain unsupported.
- `run_sql.max_rows` now advertises its existing 1–1000 bound. The runtime limit is unchanged.
- `max_age_hours` advertises its existing greater-than-zero, at-most-24 range.
- Brazil and South Africa are accepted as canonical public country names. This does not loosen source completeness or freshness validation.
- The news adapter restores User Engagement Rate from original knowledge record 0: `seshviews * engscore / seshdur`. The original record hash is pinned alongside the previous four records. Floating-point division preserves fractional rates; SQLite returns NULL for zero duration. No alternative business rule is invented.

The resolver remains annotated as potentially mutating and open-world because refresh can call a paid provider and update local evidence. Do not mark it read-only merely to avoid client approval. Configure the client to approve the specific authorized tool through its supported approval mechanism.

Validation: 57 unit/integration tests and Black formatting checks passed. A local check against the original KB and database confirmed the UER mapping. These checks do not establish agent-level latency or token savings; use a separate matched rerun for that.

The actual client rerun used targeted per-tool approval and successfully invoked the resolver in all six warm cases. See [results](resolver-results.md) and [live lifecycle](resolver-lifecycle.md).
