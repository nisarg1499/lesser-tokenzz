# lesser-tokenzz

Give a coding agent the business definitions and public facts it needs, without making it rediscover them for every question.

The MCP server combines a reviewed database catalog with a fresh, source-backed public fact catalog built through **Telem**. The agent still writes SQL and queries live business data. We reuse definitions and facts, not final answers.

## Run locally

Python 3.11+ is required.

```sh
python -m pip install -e '.[dev]'
python examples/create_demo.py
python -m lesser_tokenzz.server --database data/demo.sqlite --contracts data/contracts.json
```

The server uses MCP over stdio; connect it from your MCP client rather than typing into the terminal. The demo data is synthetic and requires no credentials.

To add current EU membership, set `TELEM_API_KEY` in your shell. Do not put a real key in a command committed to Git. Then run:

```sh
python -m lesser_tokenzz.build_catalog --fetch-provider tavily --output data/eu.json
python -m lesser_tokenzz.server --database data/demo.sqlite --contracts data/contracts.json --eu-catalog data/eu.json
```

The fetch provider must be enabled for your Telem account. Fetches may incur charges. The default endpoint is `https://hack.telem.ai/api`; `.env` files are not loaded automatically. Catalogs expire after 24 hours and must be rebuilt.

## Tools

- `get_metric_contracts`: schema, metric formulas, dependencies, units and population rules.
- `run_sql`: read-only live SQLite queries with a timeout and explicit result limits.
- `get_eu_membership_catalog`: complete current EU membership, source passages and freshness.
- Optional `--projected-catalog` replaces the full-list tool with `lookup_eu_membership`.

## Development

```sh
python -m unittest discover -s tests -v
python -m black --check lesser_tokenzz tests examples
```

See [algorithm](algo.md), [architecture](docs/architecture.md), [results](docs/results.md), and [reproduction](docs/reproduction.md). This is a focused hackathon implementation, not a general search engine. No benchmark database, credentials, or private traces are included.
