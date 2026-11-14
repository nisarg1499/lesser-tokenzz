"""Create a tiny synthetic database and reviewed contract; no API calls."""

import json
from pathlib import Path
import sqlite3

root = Path("data")
root.mkdir(exist_ok=True)
db = root / "demo.sqlite"
if db.exists():
    raise SystemExit("data/demo.sqlite already exists; refusing to overwrite it")
with sqlite3.connect(db) as conn:
    conn.execute(
        "CREATE TABLE sessions (id INTEGER, country TEXT, bounce REAL, ctr REAL)"
    )
    conn.executemany(
        "INSERT INTO sessions VALUES (?, ?, ?, ?)",
        [(1, "France", 20, 10), (2, "Germany", 40, 20), (3, "Canada", 60, 30)],
    )
contract = {
    "table": "sessions",
    "grain": "id",
    "columns": ["id", "country", "bounce", "ctr"],
    "source": {"kind": "synthetic demo", "revision": 1},
    "semantics": [
        "Rates use percentage points. Rank over all sessions before country filters."
    ],
    "metrics": {
        "adjusted_bounce": {
            "unit": "percentage_points",
            "expression": {
                "op": "mul",
                "args": [
                    {"field": "bounce"},
                    {
                        "op": "sub",
                        "args": [1, {"op": "div", "args": [{"field": "ctr"}, 100.0]}],
                    },
                ],
            },
        },
        "bounce_percentile": {
            "unit": "fraction_0_to_1",
            "expression": {
                "op": "percent_rank_asc",
                "args": [{"metric": "adjusted_bounce"}],
            },
        },
    },
}
(root / "contracts.json").write_text(json.dumps(contract, indent=2) + "\n")
print("Created data/demo.sqlite and data/contracts.json (synthetic data).")
