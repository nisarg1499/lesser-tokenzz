"""Authenticated monitor polling. A change is an invalidation signal, not evidence."""

from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import tempfile
from urllib.request import Request, build_opener
from urllib.error import HTTPError, URLError

from .telem_provider import _NoRedirect, read_response, TelemRequestError

MONITOR_QUERY = "Watch changes to current European Union membership on european-union.europa.eu official member country listing."
CHANGE_KINDS = {
    "entity_added",
    "value_changed",
    "fact_status_changed",
    "alert",
    "plan_changed",
}


class MonitorUnavailable(RuntimeError):
    pass


@contextmanager
def catalog_lock(path):
    """Serialize refresh and cursor publication across local server processes."""
    lock_path = Path(str(path) + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", dir=path.parent, delete=False
        ) as handle:
            temporary = Path(handle.name)
            json.dump(data, handle)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()


class TelemMonitorClient:
    """Read only a configured monitor; never creates recurring paid work implicitly."""

    def __init__(self, monitor_id, *, timeout_s=10, transport=None):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", monitor_id):
            raise ValueError("Invalid monitor ID")
        self.monitor_id = monitor_id
        self.timeout_s = timeout_s
        self.transport = transport

    def get(self, suffix=""):
        path = "/v1/monitors/" + self.monitor_id + suffix
        if self.transport:
            return self.transport(path)
        base = os.environ.get("TELEM_BASE_URL", "https://hack.telem.ai/api").rstrip("/")
        if base not in (
            "https://hack.telem.ai/api",
            "https://hack.telem.ai/api/router",
            "https://router.telem.ai",
        ):
            raise MonitorUnavailable("Unapproved monitor origin")
        key = os.environ.get("TELEM_API_KEY")
        if not key:
            raise MonitorUnavailable("Missing monitor credentials")
        request = Request(base + path, headers={"Authorization": "Bearer " + key})
        try:
            with build_opener(_NoRedirect()).open(
                request, timeout=self.timeout_s
            ) as response:
                return read_response(response)
        except (HTTPError, URLError, TimeoutError, ValueError, TelemRequestError):
            raise MonitorUnavailable("Monitor request failed") from None


class MonitorInvalidation:
    """Caller holds catalog_lock. Cursor and generation survive crashes/restarts."""

    def __init__(self, state_path, client):
        self.path = Path(state_path)
        self.client = client

    def poll(self):
        # Verify the operator bound the intended monitor, not an unrelated stream.
        monitor = self.client.get()
        if (
            monitor.get("id") != self.client.monitor_id
            or monitor.get("query") != MONITOR_QUERY
            or monitor.get("status") != "active"
            or not isinstance(monitor.get("agent_state"), dict)
            or monitor["agent_state"].get("status") != "ready"
        ):
            raise MonitorUnavailable("Monitor inactive or outside reviewed scope")
        if self.path.exists():
            state = json.loads(self.path.read_text())
            if state.get("monitor_id") != self.client.monitor_id:
                raise MonitorUnavailable(
                    "Monitor binding changed; operator migration required"
                )
            if type(state.get("cursor")) is not int or state["cursor"] < 0:
                raise MonitorUnavailable("Invalid monitor cursor")
            if type(state.get("generation")) is not int or state["generation"] < 1:
                raise MonitorUnavailable("Invalid monitor generation")
        else:
            state = {"monitor_id": self.client.monitor_id, "cursor": 0, "generation": 1}
        for _ in range(10):
            page = self.client.get(f'/agent/changes?cursor={state["cursor"]}&limit=200')
            changes, cursor, watermark = (
                page.get("changes"),
                page.get("next_cursor"),
                page.get("watermark"),
            )
            if (
                not isinstance(changes, list)
                or type(cursor) is not int
                or type(watermark) is not int
                or not state["cursor"] <= cursor <= watermark
            ):
                raise MonitorUnavailable("Invalid monitor page")
            previous = state["cursor"]
            changed = False
            for event in changes:
                seq = event.get("seq")
                if (
                    event.get("monitor_id") != self.client.monitor_id
                    or type(seq) is not int
                    or not 0 < seq <= cursor
                    or event.get("kind") not in CHANGE_KINDS | {"run"}
                ):
                    raise MonitorUnavailable("Invalid monitor change")
                if seq <= state["cursor"]:
                    continue
                if seq <= previous:
                    raise MonitorUnavailable("Unordered monitor change")
                # Sequence numbers are monotonic, not documented as contiguous.
                # A gap may hide a change, so conservatively require a refresh.
                changed |= seq > previous + 1
                previous = seq
                changed |= event["kind"] in CHANGE_KINDS
            if cursor > state["cursor"] and previous != cursor:
                raise MonitorUnavailable("Unexplained monitor cursor gap")
            if changed:
                state["generation"] += 1
            state["cursor"] = cursor
            # Save invalidation before any subsequent refresh; a crash remains stale.
            atomic_json(self.path, state)
            if cursor == watermark:
                return dict(state)
            if not changes:
                raise MonitorUnavailable("Monitor pagination stalled")
        raise MonitorUnavailable("Monitor backlog exceeds bounded poll")
