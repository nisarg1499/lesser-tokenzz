"""Interactive demo prompt: type a question, get answers from fresh Codex sessions.

Usage:
    python demo/ask.py            # both arms at once, with a comparison table
    python demo/ask.py native     # Native web baseline only (e.g. left pane)
    python demo/ask.py evidence   # Our evidence MCP only (e.g. right pane)

Every question starts a new session; no history is shared between questions or arms.
Raw events are saved under runs/interactive/. Type a number to use a frozen question.
Needs the `rich` package for terminal rendering (demo-only dependency).
"""

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from rich import box
from rich.console import Console, Group
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text

ROOT = Path(__file__).resolve().parent.parent
MODEL = os.environ.get("MODEL", "gpt-6.1-sol")
EFFORT = os.environ.get("EFFORT", "medium")
LABELS = {"native": "Native web baseline", "evidence": "Our evidence MCP"}
STYLES = {"native": "yellow", "evidence": "cyan"}
console = Console()


class ArmRun:
    """State of one fresh Codex session, updated from its event stream."""

    def __init__(self, arm):
        self.arm = arm
        self.steps = []
        self.usage = {}
        self.tools = []
        self.errors = 0
        self.answer = ""
        self.cache = None
        self.telem_requests = 0
        self.search_hits = 0
        self.search_queries = 0
        self.started = time.time()
        self.finished = None

    @property
    def seconds(self):
        return (self.finished or time.time()) - self.started

    def run(self, prompt, out_dir):
        # Outside the repo, so sessions do not load this project's AGENTS.md or docs.
        work = Path.home() / ".cache" / "lesser-tokenzz-demo" / "solver-workdir"
        work.mkdir(parents=True, exist_ok=True)
        answer_file = out_dir / f"{self.arm}.answer.txt"
        command = ["codex"] + (["--search"] if self.arm == "native" else [])
        command += ["exec", "-p", self.arm, "-m", MODEL]
        command += ["-c", f'model_reasoning_effort="{EFFORT}"', "-s", "read-only"]
        command += ["-C", str(work), "--skip-git-repo-check", "--ephemeral", "--json"]
        command += ["-o", str(answer_file), prompt]
        with (
            (out_dir / f"{self.arm}.events.jsonl").open("w") as log,
            (out_dir / f"{self.arm}.stderr.log").open("w") as err,
        ):
            process = subprocess.Popen(
                command, stdout=subprocess.PIPE, stderr=err, text=True
            )
            for line in process.stdout:
                line = line.strip()
                if not line:
                    continue
                # Stamp arrival time so tool durations stay readable from the trace.
                log.write(json.dumps({"received_at": time.time(), "raw": line}) + "\n")
                try:
                    self.handle(json.loads(line))
                except ValueError:
                    continue
            process.wait()
        if process.returncode:
            self.errors += 1
        if answer_file.exists():
            self.answer = answer_file.read_text().strip()
        self.finished = time.time()

    def handle(self, event):
        item = event.get("item") or {}
        if event.get("type") == "turn.completed":
            self.usage = event.get("usage", {})
        elif event.get("type") in ("turn.failed", "error"):
            self.errors += 1
            self.steps.append(("error", json.dumps(event)[:120]))
        elif event.get("type") == "item.completed":
            if item.get("type") == "web_search":
                self.tools.append("web_search")
                self.steps.append(("web search", str(item.get("query") or "")[:70]))
            elif item.get("type") == "mcp_tool_call":
                tool = item.get("tool")
                self.tools.append(tool)
                note = ""
                if item.get("error") or item.get("status") != "completed":
                    self.errors += 1
                    note = "failed"
                try:
                    result = json.loads(item["result"]["content"][0]["text"])
                except (KeyError, TypeError, ValueError, IndexError):
                    result = {}
                if tool == "resolve_external_fact":
                    self.cache = result.get("cache_state")
                    self.telem_requests += result.get("telem_request_count") or 0
                    note = f"cache {self.cache}"
                elif tool == "search_public_web":
                    # The server reports its own request count; a full hit sends none.
                    requests = result.get("telem_request_count")
                    self.telem_requests += 1 if requests is None else requests
                    hits = result.get("cache_hits") or 0
                    total = len(result.get("results") or [])
                    self.search_hits += hits
                    self.search_queries += total
                    note = (
                        f"{hits}/{total} queries from cache, {requests} Telem requests"
                    )
                elif tool == "run_sql":
                    sql = " ".join(
                        str(item.get("arguments", {}).get("sql", "")).split()
                    )
                    note = sql[:70]
                self.steps.append((tool, note))


def progress_view(runs):
    """Live panel per arm: spinner while working, steps as they complete."""
    panels = []
    for run in runs:
        style = STYLES[run.arm]
        lines = []
        for name, note in run.steps[-6:]:
            lines.append(
                Text.assemble(("  ✓ ", "green"), (name, "bold"), ("  " + note, "dim"))
            )
        if run.finished:
            lines.append(Text(f"  done in {run.seconds:.1f}s", style="green"))
        else:
            lines.append(
                Spinner("dots", text=Text(f" working… {run.seconds:.0f}s", style="dim"))
            )
        panels.append(
            Panel(
                Group(*lines),
                title=LABELS[run.arm],
                title_align="left",
                border_style=style,
            )
        )
    return Group(*panels)


def number(value):
    return f"{value:,}" if isinstance(value, int) else "unknown"


def comparison(runs):
    table = Table(
        box=box.SIMPLE_HEAVY, title="Measured from Codex events", title_style="bold"
    )
    table.add_column("")
    for run in runs:
        table.add_column(LABELS[run.arm], justify="right", style=STYLES[run.arm])
    rows = [
        ("Total time", lambda r: f"{r.seconds:.1f} s"),
        ("Input tokens (incl. cached)", lambda r: number(r.usage.get("input_tokens"))),
        ("Cached input", lambda r: number(r.usage.get("cached_input_tokens"))),
        # Unknown stays unknown; never subtract when a counter is missing.
        (
            "Uncached input",
            lambda r: (
                number(r.usage["input_tokens"] - r.usage["cached_input_tokens"])
                if "input_tokens" in r.usage and "cached_input_tokens" in r.usage
                else "unknown"
            ),
        ),
        ("Output tokens", lambda r: number(r.usage.get("output_tokens"))),
        ("Native web searches", lambda r: str(r.tools.count("web_search"))),
        (
            "MCP tool calls",
            lambda r: str(len([t for t in r.tools if t != "web_search"])),
        ),
        ("EU evidence cache", lambda r: r.cache or "—"),
        (
            "Web-search cache hits",
            lambda r: (
                f"{r.search_hits}/{r.search_queries}" if r.search_queries else "—"
            ),
        ),
        (
            "Telem requests",
            lambda r: str(r.telem_requests) if r.arm == "evidence" else "—",
        ),
        ("Errors", lambda r: str(r.errors)),
    ]
    for label, getter in rows:
        table.add_row(label, *(getter(run) for run in runs))
    return table


def show_questions(questions):
    table = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
    table.add_column(style="bold", justify="right")
    table.add_column()
    table.add_column(style="dim")
    for index, question in enumerate(questions, 1):
        tag = "EU cache" if question["kind"] == "eu" else "web fallback"
        table.add_row(str(index), question["text"], tag)
    console.print(table)


def main():
    arms = sys.argv[1:] or ["native", "evidence"]
    if any(arm not in LABELS for arm in arms):
        sys.exit(__doc__)
    if "evidence" in arms and not os.environ.get("TELEM_API_KEY"):
        sys.exit(
            "TELEM_API_KEY is not exported in this shell (needed for the evidence arm)."
        )

    frozen = json.loads((ROOT / "demo" / "questions.json").read_text())
    questions = frozen["questions"]
    arm_names = "  vs  ".join(f"[{STYLES[a]}]{LABELS[a]}[/]" for a in arms)
    console.print(
        Panel(
            f"[bold]lesser-tokenzz[/]  ·  {arm_names}\n"
            f"[dim]{MODEL} · {EFFORT} effort · fresh session per question · synthetic demo data[/]",
            border_style="bright_black",
        )
    )
    show_questions(questions)
    console.print("[dim]Type a question, a number, 'list', or 'quit'.[/]")

    while True:
        try:
            text = Prompt.ask("\n[bold green]question[/]").strip()
        except (EOFError, KeyboardInterrupt):
            console.print()
            return
        if text in ("quit", "exit", "q"):
            return
        if not text:
            continue
        if text == "list":
            show_questions(questions)
            continue
        if text.isdigit() and 1 <= int(text) <= len(questions):
            text = questions[int(text) - 1]["text"]
        console.print(
            Panel(text, title="Question", title_align="left", border_style="green")
        )
        # Same suffix as the frozen runs, identical for both arms.
        prompt = text + "\n\n" + frozen["prompt_suffix"]

        out_dir = ROOT / "runs" / "interactive" / time.strftime("%Y%m%dT%H%M%S")
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "question.txt").write_text(prompt + "\n")
        runs = [ArmRun(arm) for arm in arms]
        threads = [
            threading.Thread(target=run.run, args=(prompt, out_dir)) for run in runs
        ]
        for thread in threads:
            thread.start()
        with Live(progress_view(runs), console=console, refresh_per_second=8) as live:
            while any(thread.is_alive() for thread in threads):
                live.update(progress_view(runs))
                time.sleep(0.12)
            live.update(progress_view(runs))

        for run in runs:
            body = (
                Markdown(run.answer)
                if run.answer
                else Text("No answer; see the stderr log.", style="red")
            )
            console.print(
                Panel(
                    body,
                    title=f"Answer · {LABELS[run.arm]}",
                    title_align="left",
                    subtitle=f"{run.seconds:.1f}s",
                    subtitle_align="right",
                    border_style=STYLES[run.arm],
                    padding=(1, 2),
                )
            )
        console.print(comparison(runs))
        console.print(
            f"[dim]One run per arm; timing is noisy. Raw events: {out_dir}[/]"
        )


if __name__ == "__main__":
    main()
