# Working on lesser-tokenzz

- Keep code and documentation in English. Prefer small modules, explicit names and short comments explaining why.
- Read README.md and docs/architecture.md first. Keep the original evidence and claim boundaries in docs/results.md.
- Never commit credentials, local databases, private traces or generated catalogs. Use synthetic fixtures for tests.
- Never disable freshness/completeness checks to make a demo pass. Unknown or stale evidence must remain unknown or stale.
- Run `python -m unittest discover -s tests -v` and `python -m black --check lesser_tokenzz tests examples` after edits.
- Live Telem and model runs consume usage. Offline tests use fake responses and do not establish provider availability or performance.
- Preserve source URLs, timestamps, content hashes and measured costs. Unknown cost is not zero.
- Separate cache build time from warm-query time. Report regressions and case selection, not only winning examples.
- Do not change approved metric definitions or population scope without reviewing their source. New business domains need their own reviewed mapping.
