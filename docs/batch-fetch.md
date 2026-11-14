# Batch Fetch: fewer refresh round trips

The resolver and standalone builder now send the two required official EU URLs
in one native Telem Fetch request. There was already no LLM turn between the two
reads. This removes one HTTP request, not one model turn.

## Validation

Results are matched by exact URL, not response order. Both distinct pages must be
present and pass the existing error, warning, truncation, source and completeness
checks. An explicit non-2xx page HTTP status or 206 Partial Content also rejects the batch. A partial
batch does not replace the previous catalog. The reviewed membership check,
response byte cap, no-cache provider option, and monitor generation checks remain.

The provider adapter accepts one to five distinct URLs. The current EU resolver
uses exactly two; it does not broaden the reviewed source family.

## Small live measurement

On November 14, 2026, we used the hackathon endpoint, Tavily Fetch, the same two
URLs, `no_cache=true`, text output and the same per-page validation. We ran in
order: sequential, batch, batch, sequential. These were direct provider calls,
not end-to-end Codex runs. Each produced a validated 27-member catalog.

| Run | Fetch mode | Time | Fetch HTTP requests | Fetched URLs |
|---|---|---:|---:|---:|
| 1 | Sequential | 6.487 s | 2 | 2 |
| 2 | Batch | 2.605 s | 1 | 2 |
| 3 | Batch | 2.488 s | 1 | 2 |
| 4 | Sequential | 5.709 s | 2 | 2 |

The averages were 6.098 s sequential and 2.547 s batch. This small sample suggests
lower fetch latency, not a stable performance guarantee. Provider load and caches
outside our control can affect timings. We did not measure agent token savings.
Both modes fetch two billable URLs; fewer HTTP requests does not establish lower
charges. Dollar cost was not returned/reconciled and remains unknown.

A separate full resolver smoke succeeded in 8.053 s with one search and one batch
fetch. A subsequent warm lookup used no search/fetch calls. Monitor mode was off;
its polling overhead is separate. These numbers do not replace the earlier
six-case agent benchmark.

## Verification

78 offline tests passed. Batch tests cover unordered responses, missing pages,
duplicates, unknown URLs, second-page failure, non-2xx/206 status, truncation, and
input bounds. Black formatting passed. Live testing is a smoke check on this
source family, not evidence of broader-domain coverage.

[Telem Fetch documentation](https://docs.telem.ai/resources/fetch-best-practices/)
