# Fixed-code end-to-end comparison

This is a fresh rerun after the initial integration audit. The real Codex client is given explicit per-tool approval for the resolver. Source code is frozen separately from the original audit. Warm evidence comes from genuine Telem retrieval; final answers are not cached.

## Result

| Metric | Native search | Warm resolver | Change |
|---|---:|---:|---:|
| Correct numeric tables | 6/6 | 6/6 | Same |
| Total time | 201.43 s | 168.73 s | 16.2% lower |
| Mean time per task | 33.57 s | 28.12 s | 16.2% lower |
| Total input tokens | 731,331 | 602,333 | 17.6% lower |
| Cached input (subset) | 564,736 | 493,824 | 12.6% lower |
| Uncached input | 166,595 | 108,509 | 34.9% lower |
| Output tokens | 3,996 | 3,667 | 8.2% lower |

Warm was faster on five of six pairs. Global ranking was slower and used more input tokens; it is retained below. Every warm session successfully called the new resolver, hit fresh evidence and made zero provider calls. These are new measurements on the fixed code, not numbers copied from the earlier prototype.

## Setup

Six existing EU-related tasks; one fresh session per arm per task; GPT-6.1 Sol, medium effort. Sequential execution, alternating arm order. Both arms use identical fixed database catalog and SQL tools. Native uses live web search; warm uses a genuine Telem-fetched full-list catalog from earlier today. Reference answers never enter the solver.

Model input totals include cached input. Provider costs are unknown, not zero. Warm build cost is excluded. Citation URLs are retained in raw answers; numeric match is not full evidence grading.

| Task | Arm | Numeric match | Seconds | Input | Cached input | Output |
|---|---|---:|---:|---:|---:|---:|
| more6_01 | native | True | 35.61 | 130126 | 92416 | 707 |
| more6_01 | warm | True | 27.77 | 109066 | 80128 | 662 |
| more6_06 | native | True | 36.81 | 147667 | 127104 | 690 |
| more6_06 | warm | True | 27.31 | 80085 | 60928 | 574 |
| eu_global_ranking | native | True | 25.39 | 76495 | 60032 | 567 |
| eu_global_ranking | warm | True | 27.06 | 103097 | 85632 | 556 |
| eu_subscription_quality | native | True | 35.62 | 144256 | 100864 | 707 |
| eu_subscription_quality | warm | True | 32.09 | 91978 | 83584 | 737 |
| eu_weighted_quality | native | True | 34.95 | 139010 | 110848 | 764 |
| eu_weighted_quality | warm | True | 25.60 | 109363 | 92032 | 613 |
| eu_sessions_users | native | True | 33.04 | 93777 | 73472 | 561 |
| eu_sessions_users | warm | True | 28.90 | 108744 | 91520 | 525 |

## Scope and limitations

- Six selected tasks all reuse current EU membership; this is not a broad claim of search generality.
- One run per arm. Latency is noisy; inspect each pair as well as totals.
- Both arms use the same fixed database catalog and SQL tools, isolating the external-evidence workflow within this solution comparison.
- Native search uses its built-in provider; the warm catalog was created through Telem. This is not provider-only causal isolation.
- Fresh evidence build/refresh is separate. The warm run does not measure first-use overhead.
- Initial failed audit is retained separately in refresh-e2e; no failed session is silently replaced.

## Reproduction and audit records

The full experiment workspace retains exact questions, grader-only references, prompts, raw events, answers, source hashes and per-run token counters. Private datasets and traces are deliberately not included in this shared code repository.

The Codex client approved only the already-authorized resolver tool for the isolated experiment:

```toml
[mcp_servers.metrics.tools.resolve_external_fact]
approval_mode = "approve"
```

`metrics` is the server name used in this experiment. Preserve the tool's side-effect annotation: a refresh can call a paid provider and update local evidence. This is not a global approval bypass.

The original failed integration audit is retained, not replaced. Before fixes, the missing UER definition affected both arms and the resolver was denied approval. Those sessions are not evidence of the new resolver's performance.
