# Telem routing and inspectable source selection

This opt-in addition uses Telem's native accuracy routing within a bounded provider list:

```sh
python -m lesser_tokenzz.server \
  --database data/demo.sqlite --contracts data/contracts.json \
  --eu-catalog data/eu.json --auto-refresh-evidence \
  --search-provider brave,tavily --auto-routing accuracy --fetch-provider tavily
```

The routing service selects providers; it does not decide whether our saved facts are fresh. Our resolver still handles TTL, page completeness and membership validation.

## What happens on a miss

1. Codex expresses the supported public fact request as `eu_membership` and canonical country names. The MCP turns that into a fixed public list query. It never transmits the business question or database rows.
2. Telem routes the query within the explicit provider allowlist. Its normalized response identifies each provider and its result order.
3. Our deterministic selection deduplicates URLs within each provider, rejects pages outside the reviewed parser-compatible family, and computes reciprocal rank fusion (k=60). This is our simple ranking policy, not a learned Telem reranker.
4. The resolver fetches the supported official pages through Telem and validates the complete list. Search snippets alone cannot become facts.
5. The refresh response includes a discovery trace (warm responses omit it to avoid repeating context). It records chosen providers, source ranks, rejected result count and routing-unavailable warnings. The next related question can reuse the grounded facts.

## What this proves, and what it does not

The event endpoint accepted accuracy routing for the EU query in a live test, selected Brave and Tavily, and both returned the official list. This demonstrates a working native Telem integration, not better accuracy or lower latency than a pinned provider. The provider score is intentionally not interpreted as a probability.

The parser remains EU-specific and fetches a fixed reviewed page family. Ranking makes discovery auditable; it does not turn this into a general evidence research engine. Multiple providers finding the same URL is agreement about discovery, not independent factual corroboration.

The six-case performance report predates this optional routing addition. Do not attribute those improvements to routing or ranking. Cache construction and provider charges remain separate from warm-query results.

Reference: https://docs.telem.ai/resources/search-parameters/

`provider_calls` is the legacy count of Telem HTTP requests. The explicit `telem_request_count` counts requests; `provider_run_count` counts fan-out runs. One search request may run several providers and cost more than one pinned search. Neither number is an invoice total.

A full live refresh with routing succeeded in 10.854 seconds: one search request (two providers) plus two fetch requests, followed by a successful warm lookup without provider calls. This is a direct resolver smoke, not a new end-to-end model benchmark.
