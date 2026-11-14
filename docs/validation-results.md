# Regression and fallback checks — November 14, 2026

## What this establishes

- Six existing EU + database tasks returned the expected numeric tables.
- Two new G7/OECD + database tasks used fresh Telem searches and returned the expected numeric tables.
- Automatic source-bookmark learning did **not** succeed in the separate live check. The validator rejected incomplete evidence and saved nothing.

These were development snapshots immediately before commit `23daaa9`, not a rerun of that exact commit. The EU resolver and public-search modules match the published code. The later source-bookmark hardening and removal of an unused optional direct verifier were not exercised by the successful agent runs. Each task ran once with GPT-6.1 Sol, medium reasoning, in a fresh Codex session. This is a small regression check, not a general accuracy benchmark.

## Six warm EU tasks

Both business definitions and live SQL came from the existing news database setup. The server exposed public-web fallback, but all six tasks were covered by the prebuilt EU membership catalog. No final answers were cached. Numeric columns and rows were checked against existing independent SQL references, with a tolerance of 1e-6.

| Task | Numeric check | Total time | Input tokens | Cached input | Output tokens | SQL calls |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Hourly adjusted bounce | Pass | 33.34 s | 113,855 | 87,168 | 681 | 1 |
| User engagement rate | Pass | 26.60 s | 91,089 | 65,280 | 621 | 1 |
| Global ranking, then EU filter | Pass | 21.95 s | 55,816 | 46,464 | 554 | 1 |
| Subscription quality | Pass | 32.59 s | 137,592 | 101,760 | 753 | 4 |
| Session- vs. country-weighted quality | Pass | 33.12 s | 72,180 | 64,384 | 709 | 1 |
| Sessions and distinct users | Pass | 24.05 s | 113,521 | 84,992 | 578 | 1 |
| **Total** | **6/6** | **171.64 s** | **584,053** | **450,048** | **3,896** | **9** |

Cached input is included in input tokens, not added to it. Uncached input totaled 134,005. Each task called `get_metric_contracts` once and `resolve_external_fact` once. Every resolver response was a fresh cache hit. No public-web fallback or bookmark promotion ran in this cohort.

### Historical comparison, not a fresh paired test

A separate earlier native-search run of these six tasks totaled 201.43 seconds, 731,331 input tokens and 3,996 output tokens. Relative to that historical run, the new measurements are 14.8% lower in time, 20.1% lower in input tokens and 2.5% lower in output tokens. Different run times and cache conditions mean these percentages are descriptive, not a controlled causal estimate. Cache build time is excluded. Provider charges were unavailable; no dollar savings are claimed.

## Two fresh non-EU + database tasks

For both tasks, the candidate countries were Australia, Brazil, Canada, France, Germany, India, Japan and South Africa. The question asked for session counts and distinct-user counts by country, selecting countries using current **G7** or **OECD** membership. This requires both external research and the existing database, rather than standalone web trivia.

Native search was disabled. The source-bookmark store started empty, the existing EU catalog remained available, and the prompt instructed the agent to use fresh official evidence for non-EU membership. Independent SQL references were prepared before the runs; membership was also checked against official sources separately.

| Task | Numeric check | Total time | Telem search time | Input tokens | Cached input | Output tokens | Successful search calls / queries |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| G7 + session/user counts | Pass | 52.20 s | 12.51 s | 162,575 | 143,488 | 714 | 2 / 3 |
| OECD + session/user counts | Pass | 38.81 s | 6.22 s | 161,017 | 132,480 | 686 | 2 / 4 |

Each trace shows one contract lookup, one empty bookmark lookup, fresh Telem searches and one SQL query. Neither called the EU resolver. The G7 run selected Canada, France, Germany and Japan; the OECD run also selected Australia. Official-source snippets supported these classifications. An independent read of the [OECD membership page](https://www.oecd.org/en/about/members-partners.html) confirmed the distinction between members and partners. The tested agents themselves used search snippets, not full-page extraction.

The G7 run made one single-query call followed by a two-query batch. The OECD run made two successful two-query batches. It also made one rejected call with `max_results=6`, then corrected it to the supported maximum of 5. The rejected call did not reach Telem. Search time is the sum of provider elapsed times reported by successful search tool responses; total time also includes model reasoning and other tools.

Neither agent invoked `bookmark_public_evidence` or saved a bookmark. These runs demonstrate fresh fallback + SQL, not warm-cache savings or automatic learning. There is no matched baseline for these two tasks, so no speedup is claimed.

## Live bookmark validation: rejected, not learned

A separate batch search for Bulgaria's euro-area accession returned official ECB and Consilium evidence in 3.87 seconds. A subsequent attempt to bookmark a passage using those two sources returned `unresolved` in 2.86 seconds. Only the ECB fetch result was returned, with null `http_status` and no `final_url`. No bookmark was written; a lookup remained empty.

This is evidence that the validator fails closed. It is **not** evidence of successful automatic promotion. The current tier requires the same exact passage in two distinct trusted hosts, complete fetch metadata and a fresh timestamp. Even successful promotion records source evidence, not proof of claim truth. Lookup is exact-query matching, not semantic matching. Generic claim verification and semantic-conflict detection remain outside this result.

## Audit boundary

The internal run archive retains exact prompts, reference tables, event traces, answers, token counts and tested-module hashes. This repository report deliberately excludes database rows, raw traces, credentials and generated catalogs. Numeric agreement is narrower than complete answer or citation-quality adjudication. The results should not be presented as a broad production accuracy guarantee.
