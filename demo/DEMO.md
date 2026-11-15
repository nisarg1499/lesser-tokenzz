# Side-by-side judge demo

Two fresh Codex sessions answer the same frozen question against the same database
and business definitions.

| Arm | Label | External evidence |
|---|---|---|
| A | **Native web baseline** | Codex native live web search |
| B | **Our evidence MCP** | Warm EU resolver + Telem public-web fallback; native search off |

Both arms use the same MCP server for `get_metric_contracts` and `run_sql`. The
baseline is not "no MCP at all".

## Scope

This demo runs on the **synthetic three-row database** from `examples/create_demo.py`.
The original benchmark database, knowledge JSONL and questions were not found on this
machine, so the eight questions in `demo/questions.json` are new and do not reproduce
the historical results. Six need current EU membership; two need another public fact
(euro currency, G7 membership). With three countries the questions are easy; they show
the workflow and its cost, not accuracy at scale.

## Interactive prompt

```sh
python -m pip install rich          # demo-only dependency
python demo/ask.py                  # both arms at once, with a comparison table
python demo/ask.py evidence         # one arm, e.g. for a split-screen pane
```

Type a question or a number from the list. Each question starts fresh sessions.
To show the search cache warming up, ask question 7 twice in the evidence arm:
the first run reports `0/3 queries from cache, 1 Telem requests`, the second
`3/3 queries from cache, 0 Telem requests`. Delete `data/search-cache/` to start cold.

## Run

`TELEM_API_KEY` must be exported in the shell used for arm B. It is forwarded to the
MCP server by name and never printed.

```sh
# Warm cache build, reported separately from queries (may incur Telem charges; 24 h TTL)
python -m lesser_tokenzz.build_catalog --fetch-provider tavily --output data/eu.json

# One question, two panes
demo/run_arm.sh native   eu_avg_adjusted_bounce     # left pane
demo/run_arm.sh evidence eu_avg_adjusted_bounce     # right pane

# Everything, sequentially, alternating arm order
demo/run_all.sh --skip-existing

# Rebuild the comparison table and runs/comparison.csv
python demo/compare.py
```

Default model is `gpt-6.1-sol`, medium effort. Override both arms together with
`MODEL=... EFFORT=...`, and report any substitution.

## Configuration

- Profiles: `~/.codex/native.config.toml` and `~/.codex/evidence.config.toml`, selected
  with `codex exec -p <name>`. Arm A adds `--search`; arm B does not.
- Arm B sets `web_search = "disabled"`; leaving out `--search` alone still allowed
  native page opens. It also passes `--search-cache data/search-cache`.
- Both arms disable the shell tool, memories, plugins, apps and the `node_repl`
  server, and run in an empty directory outside the repo so this project's
  `AGENTS.md` is not loaded. Runs before this change are not comparable.
- Arm B approves only `resolve_external_fact` and `search_public_web`. There is no
  global approval bypass; the sandbox is read-only in both arms.
- Each run is a new `--ephemeral` session.
- Paid monitors and experimental source bookmarks are not enabled.

## What is measured

Read from raw Codex JSONL events in `runs/<question>/<arm>.events.jsonl`:

- **Tokens** from `turn.completed.usage`. `input_tokens` includes
  `cached_input_tokens`; uncached = input − cached.
- **Wall time** covers the whole `codex exec` process. **Turn time** is first to last event.
- **Web search time** (arm A) and **evidence tool time** (arm B) are the summed
  start-to-completion gaps of those tool events only. Total runtime is never called search time.
- **Cache state and Telem request count** come from the resolver's own response.
- **Correctness** is a numeric match against `demo/grader_only/references.json`,
  which is never given to a solver. Citation quality is not graded.

Provider cost is unknown, not zero. One run per arm per question; timing is noisy.
Earlier attempts are moved to `runs/<question>/previous-*`, not deleted.

## Limits

- The EU sources are preconfigured. Generic Telem fallback returns cited, unverified
  snippets; automatic promotion of arbitrary sources to validated bookmarks is not established.
- The search snippet cache matches keywords, not meaning, and serves unverified
  snippets up to 24 hours old. Model reasoning time dominates and is not cached.
