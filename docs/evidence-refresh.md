# Automatic public evidence refresh

The optional `resolve_external_fact` tool implements the supported EU-membership
path in the published design. It does not implement arbitrary research or
embedding similarity. The normal SQL and metric interfaces are unchanged.

## Flow

1. Reject unsupported predicates, noncanonical country names, historical dates,
   or a requested maximum age above the configured 24-hour policy.
2. Reuse a complete validated local catalog. No external calls on a covered hit.
3. If refresh is enabled, send one fixed public query to Telem, constrained to
   `european-union.europa.eu`, with at most three results from one configured provider.
4. Require discovery of the supported official listing. Fetch its two known
   pagination URLs using one configured provider. Each request times out after
   20 seconds; at most three provider requests occur per resolution.
5. Reject incomplete, conflicting-count, unexpected-membership, future-dated,
   unsupported-source or truncated evidence. The reviewed membership set is an
   explicit change-review guard, not a substitute for fetched source evidence.
6. Retain the previous file by revision hash and replace the current file atomically.
   Failed refreshes do not serve old evidence as current. A process-local lock
   avoids duplicate successful refreshes within one server process.
7. Return requested facts, passages, URLs, retrieval times, hashes and revision.
   No full provider response or private database row enters the answer context.

This source policy selects a single supported official source family; it is **not**
a general ranking engine. Accuracy auto-routing remains disabled and untested.
Provider redirect behavior cannot independently be inspected; returned canonical
URLs are validated, but this is not a complete provider-side SSRF audit.

Tavily reports capability gaps for several optional fields, including provider
cache state and upstream HTTP status. Those specific metadata gaps are retained;
other warnings fail validation. `no_cache` is requested, but missing provider cache
metadata means we do not claim an independently verified origin refresh. A recent
retrieval timestamp and TTL never establish that source content is correct.

## Live smoke, November 14, 2026 UTC

| Step | Outcome | Provider requests | Resolver wall time |
|---|---|---:|---:|
| Missing catalog: France / United Kingdom | Refreshed; true / false | 3 | 9.761 s |
| Related follow-up: Germany / Norway | Fresh hit; true / false | 0 | Below 1 ms |

Used the event endpoint `https://hack.telem.ai/api`, Brave search and Tavily fetch.
Both official pages were read and all 27 members validated. An earlier attempt
failed closed after 8.533 seconds because it treated all metadata-gap warnings as
content failures. One diagnostic fetch identified the documented optional-field
gaps; the resolver now accepts only that narrow warning class.

This is a functional smoke test, not a new matched agent benchmark. It does not
measure end-to-end agent tokens, model time, accuracy rate, or total dollar savings.
Provider charges are unknown, not zero. Prior published benchmark numbers are
unchanged and belong to the earlier experiment.

Offline tests cover refresh/hit, unsupported inputs, disabled refresh, TTL/future
validation, partial pages, conflicting count, metadata warning policy and atomic
write failure. The actual MCP stdio test also invokes the new resolver tool.

### Review hardening and repeat smoke

Independent review identified a validation mismatch: the provider's normalized
hits omit failed runs, while the original parser consumed raw response pages.
Validation now checks the exact raw runs and pages consumed by the parser, in both
the legacy CLI builder and automatic resolver. Extra runs, duplicate/wrong pages,
provider errors and unsafe warnings are rejected. Raw network responses are capped
at 256 KiB before JSON parsing, in addition to the per-page text limit.

After these fixes, a second live missing-catalog refresh succeeded in **7.319 s**
with three calls; the related fresh hit again made zero calls and took below 1 ms.
The complete offline suite now has **55 passing tests**, including regression tests
for the review findings. This repeat is still a functional smoke, not a matched
end-to-end agent experiment.
