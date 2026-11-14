# Reproducing and extending the pilot

## Inputs

For a credential-free check, use `examples/create_demo.py`. It produces a small synthetic SQLite database and reviewed contract JSON under ignored `data/`.

For the original news domain, obtain the authorized benchmark database and knowledge JSONL separately, including their license and attribution. Start the server with `--database PATH --news-knowledge PATH`. The adapter intentionally rejects changed or unsupported knowledge records. Do not replace its fingerprints merely to bypass that check.

The original benchmark database, tasks, answer keys and raw model traces are not bundled here. This checkout alone does not reproduce the historical numerical results. The original data's CC-BY-SA requirements and the source benchmark's distribution restrictions must be checked before sharing any data archive.

## Client configuration

Configure an MCP client to launch this installed Python environment:

```json
{
  "mcpServers": {
    "lesser-tokenzz": {
      "command": "/absolute/path/to/python",
      "args": ["-m", "lesser_tokenzz.server", "--database", "/absolute/path/to/data/demo.sqlite", "--contracts", "/absolute/path/to/data/contracts.json", "--eu-catalog", "/absolute/path/to/data/eu.json"]
    }
  }
}
```

Client configuration formats vary; use your client's documented MCP setup. The server does not need a Telem key to read an already-built catalog. Only the explicit refresh command needs it.

## Fair comparison

Freeze task text, model, reasoning effort, database version, business definitions and grading before running either arm. Use fresh model sessions. Compare:

- **Native:** database catalog + live SQL + native web evidence.
- **Warm:** same database catalog + live SQL + fresh Telem catalog.

Select distinct questions whose external facts are within the catalog's declared scope. Publish the selection rule and every result, including failures. Keep build time and warm time separate. Record full answer time, actual search/fetch time where observable, input/cached-input/output tokens, tool calls, final answer and grading rationale. Do not label total answer time as search time.

The historical treatment explicitly instructed the agent to use `get_eu_membership_catalog`; native search was disabled in its CLI configuration. Verify actual traces for alternate tools rather than assuming a setting blocks every fallback.

No dollar figure is valid without the model's applicable input/cache/output rates and actual Telem charges. Repeated trials are needed to quantify timing variance.
