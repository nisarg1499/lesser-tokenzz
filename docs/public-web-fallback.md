# Public web fallback

The EU resolver is deliberately narrow. An agent can now use a separate,
opt-in public search tool when it needs another external fact, such as a country's
currency. This does not replace the reviewed EU bookmarks, expand their predicate,
or automatically cache general search results.

## Query path

```mermaid
flowchart TD
    A[Agent separates public fact from private business question] --> R{Supported EU fact?}
    R -- Yes --> EU[Existing reviewed EU resolver and freshness checks]
    R -- No --> Q[search_public_web: 1 to 3 independent public queries]
    Q --> V[Validate query and provider bounds]
    V --> T[One Telem native batch Search request]
    T --> G[Group by explicit batch_index and provider status]
    G --> F[Filter unsafe URLs, deduplicate and cap snippets]
    F --> E[Cited untrusted evidence or unresolved per query]
    E --> A
    EU --> A
    A --> O[Answer with citations and explicit uncertainty]
```

Enable with `--web-fallback`. The tool accepts `public_queries` (one to three
strings, at most 500 characters each) and `max_results` (one to five per query).
Use `--search-provider brave` or at most two explicitly configured providers.
Telem receives a list of `{query: ...}` in `user_input` in one `/v1/search` call.
This is native batch search, not a Python loop of separate HTTP calls. Search
routing remains optional. Each returned group retains its query index, query,
provider status, and source URL. A failed query does not erase healthy siblings.
Missing batch attribution is discarded, not guessed.

## Safety and limitations

- The tool sends queries to Telem. The agent must remove DB rows, private customer
  facts, credentials and full business questions. Basic input screening is not DLP.
  Administrators can leave the tool disabled; the annotation is open-world and
  not marked read-only to avoid implying safe automatic transmission.
- The search_public_web tool exposes no arbitrary URL fetching. Local/private IP citations, local hosts,
  credential-bearing URLs and non-HTTP(S) links are dropped. This is URL syntax
  screening, not a DNS security guarantee; the search tool does not fetch these links (the separate opt-in bookmark tool below does).
- Snippets are explicitly untrusted data, never instructions. This labeling does
  not eliminate prompt injection; the calling agent must respect that boundary.
- At most 15 snippets are returned, each at most 1,200 characters. Truncation is
  explicit. Search snippets may be stale, irrelevant or incomplete. A retrieval
  timestamp is not a publication date or proof of freshness.
- Results say `answer_verified: false`. There is no generic correctness guarantee,
  no automatic answer cache, and no claim that fallback matches warm EU savings.
- One request has a 20-second timeout and a 256 KiB response cap, with no retries.
  Costs remain unknown until billing is reconciled. Batch latency is shared;
  there is no invented per-query timing or zero-cost assumption.

## Verification

The mock suite covers batch payload shape, per-query attribution, partial provider
failure, malformed sibling runs, input limits, credential screening, unsafe links,
deduplication, snippet bounds and untrusted-content labeling. The actual stdio MCP
handshake checks opt-in tool discovery and schema bounds.

A live event-endpoint smoke on November 14, 2026 sent two independent public
currency queries in a single request. Both query indices returned evidence;
the request took 5.83 seconds.
This is connectivity/attribution evidence, not an accuracy or speed benchmark.
Provider charges were not reported.

An actual fresh Codex session (`gpt-6.1-sol`, medium, native search and shell
disabled) discovered and called `search_public_web` through stdio MCP. It batched
the two currency questions into one tool call. That tool took 4.27 seconds and
returned both groups. Codex cited returned sources and explicitly warned that the
central-bank snippets alone did not fully establish both claims. This validates
tool wiring and uncertainty handling, not general answer accuracy. The tool was
explicitly approved for this public-only smoke; normal client approval policies
still apply. No private database data entered either request.

## Experimental source bookmarks (separate opt-in)

`--source-bookmarks data/source-bookmarks --trusted-source-domain HOST` enables
`bookmark_public_evidence` and `lookup_public_bookmarks`. Repeat the hostname flag
for each operator-vetted **exact hostname**, with at most ten. The agent selects
two discovered URLs and an exact passage; the server performs the checks and save
without a human review step. It requires two distinct trusted hosts, successful
HTTP 200 fetches, explicit non-truncation, explicit unchanged final URLs, and the
same exact whitespace-normalized passage in both fetched texts. Unknown metadata,
partial pages, redirects, absent quotes and ambiguous duplicate results fail
closed. Two results from the same URL/host do not count as corroboration.

This is deliberately a **source-provenance tier, not a generic fact validator**.
Literal agreement does not establish truth, independent authorship, applicability,
or absence of semantic contradictions. Entries are marked
`source_checked_claim_unverified`, `answer_verified: false`, and
`semantic_conflicts_checked: false`. The agent must leave a claim unresolved when
these concerns remain. No LLM assertion promotes a claim to a verified fact. The
existing typed EU validator is unchanged.

The bookmark response reports `telem_elapsed_s` for retrieval only, not total
validation/persistence latency. Entries contain the public query, exact passage, both URLs, fetch timestamps,
content hashes and creation time. Atomic per-entry writes avoid losing unrelated
concurrent updates. Lookup returns at most three entries for the **exact query**
within 24 hours and the current hostname policy. This is not semantic retrieval,
and these entries are not integrated with Telem Monitor. Expired entries are not
served as current. Do not place this generated directory in version control.

The two-source exact-text requirement has low recall, especially across independent
publishers. If Telem omits final-URL or completeness metadata, source bookmarking
is unavailable rather than pretending to have validated a page. Unit tests verify
positive synthetic persistence/reuse and fail-closed negative paths. No live
bookmark success or generic conflict/accuracy improvement is claimed.

The final-URL check happens after Telem's fetch. It rejects redirected content
from persistence; it does not prevent Telem itself from following redirects or
constitute an SSRF guarantee. Distinct hostnames can share an owner or copy text,
so this rule is not a proof of independent corroboration.

### Live bookmark limitation

A targeted non-EU source-bookmark attempt against ECB and Consilium pages failed
closed in 2.86 seconds. The batch returned only the ECB page and omitted HTTP
status/final-URL metadata needed by this tier. Lookup remained empty. Accordingly,
automated live source promotion/reuse has **not** been demonstrated with the
current event provider; synthetic persistence tests do not establish that it
works in production. Do not present this experimental tier as a working generic
fact-validation system.

The live Tavily-backed result explicitly reported a `capability_gap` for
`http_status`: its extraction response provides success/failure by array
membership, not the upstream HTTP code. It exposed `canonical_url`, not a verified
final URL or redirect chain. The event OpenAPI fetch options do not offer a
redirect-verification flag. Canonical URL is not treated as equivalent to final
URL. Meeting the stronger source-check contract requires another verified fetch
capability with explicit safe URL-integrity guarantees.
