# Recorded pilot results

These measurements came from the earlier experimental implementation on November 14, 2026. They are not new runs of this cleaned package. Refactoring passed offline tests; live performance must be revalidated before claiming identical behavior.

The strongest Telem result uses a prebuilt, complete EU membership catalog across six related business questions. Both arms received the same database catalog. The baseline used native live web search; the treatment used the Telem-built public catalog. Each case ran once per arm.

| Measure | Native web search | Warm Telem catalog | Change |
| --- | ---: | ---: | ---: |
| Correct answers | 6/6 | 6/6 | No accuracy gain measured |
| Total answer time | 207.76 s | 169.70 s | 18.3% lower |
| Input tokens | 1,180,860 | 612,846 | 48.1% fewer |
| Cached-input tokens | 1,027,072 | 539,008 | Reported separately |
| Output tokens | 3,948 | 3,544 | 10.2% fewer |

Building the public catalog took 16.44 seconds and fetched two official pages through Telem. Adding that one-time build to the six warm queries gives 186.14 seconds, about 10.4% below the native total. Provider charges are unreconciled, so this is not a verified dollar-cost comparison.

Five cases were faster; one global-ranking case slowed from 21.89 to 25.94 seconds. Six covered cases do not establish a general improvement across all hybrid research tasks. The prompts explicitly directed each arm to its respective evidence tool. The treatment traces showed no alternate web fallback on these six cases.

## What did not establish an improvement

- Per-country cold Telem lookups were slow and sometimes incomplete: one early case took 115.30 seconds and failed, versus a correct 33.50-second native run.
- Projecting only relevant country evidence reduced response characters, but did not establish an incremental speed improvement over the full catalog.
- A task needing OECD facts was outside the EU catalog's coverage and fell back to web search. It is not included in the six-case EU result.
- This does not demonstrate embedding-based semantic cache hits. It demonstrates reuse of a complete sourced fact dimension across related questions.

The broader experimental archive remains separate. Do not present the synthetic example in this repository as a benchmark result.
