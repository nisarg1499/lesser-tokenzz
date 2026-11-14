# Source and packaging notes

This focused export was prepared from the existing SearchHack implementation at local revision `b23bd4093985be80b77d47593ccf7268a498c547` on November 14, 2026.

Preserved core: metric contract/compiler helpers and their synthetic tests; Telem request/response handling; complete EU list validation and projection. Packaging changes: importable Python package, explicit CLI inputs, a small standalone MCP server, bounded read-only SQL, synthetic example, offline protocol test, and focused documentation. The Telem adapter also refuses HTTP redirects so credentials cannot follow a redirected request.

No prior repository history, `.env`, runtime credentials, paid API responses, benchmark database, original benchmark task set, answer keys or raw agent traces were copied. The news adapter retains reviewed source fingerprints, not the source records themselves. All test data here is synthetic.

No new project-wide software license is chosen here. The repository owner should select one before general redistribution. External benchmark material remains subject to its own terms and is not covered by any future code license.
