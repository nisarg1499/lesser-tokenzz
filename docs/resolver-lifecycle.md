# Live refresh through Codex

We deliberately aged the stored catalog timestamps beyond 24 hours, then ran two fresh Codex sessions sequentially. Both used the fixed resolver. This is a lifecycle check, not another six-case efficiency result.

| Metric | Stale catalog | Refreshed warm catalog |
|---|---:|---:|
| Correct numeric answer | Yes | Yes |
| Full agent time | 38.15 s | 28.82 s |
| Resolver time | 10.015 s | <0.001 s |
| Provider calls | 3 | 0 |
| Input tokens | 108,642 | 109,672 |
| Cached input subset | 91,648 | 92,416 |
| Output tokens | 632 | 630 |

The stale request invoked one real Telem search and two fetches, validated the complete official EU list, and published new evidence. The next agent session reused it with no provider call. Its token count was not lower: the main difference in this repeated-question lifecycle test was provider latency. Cost is unknown, not zero.

Exact prompts, raw events, answers and resolver results are retained in the private experiment workspace. The timestamp aging is synthetic; the subsequent Telem requests and returned fresh timestamps are real.
