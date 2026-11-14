"""Synthetic monitor events; not evidence that Telem detected a real source change."""

from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

from lesser_tokenzz.monitor_invalidation import (
    MONITOR_QUERY,
    MonitorInvalidation,
    MonitorUnavailable,
    TelemMonitorClient,
)
import test_evidence_resolver as resolver_tests


class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "state.json"
        self.events = []
        self.metadata = {
            "id": "monitor-1",
            "query": MONITOR_QUERY,
            "status": "active",
            "agent_state": {"status": "ready"},
        }
        self.fail = False

        def transport(path):
            if self.fail:
                raise MonitorUnavailable("test outage")
            if "/agent/changes" not in path:
                return self.metadata
            cursor = int(path.split("cursor=")[1].split("&")[0])
            events = [e for e in self.events if e["seq"] > cursor]
            latest = max([e["seq"] for e in self.events], default=cursor)
            return {"changes": events, "next_cursor": latest, "watermark": latest}

        self.client = TelemMonitorClient("monitor-1", transport=transport)
        self.monitor = MonitorInvalidation(self.path, self.client)

    def event(self, seq, kind="value_changed"):
        self.events.append({"seq": seq, "kind": kind, "monitor_id": "monitor-1"})

    def test_restart_and_duplicate_poll_do_not_invalidate_twice(self):
        self.event(1)
        first = self.monitor.poll()
        restarted = MonitorInvalidation(self.path, self.client)
        self.assertEqual(first, restarted.poll())
        self.assertEqual(first["generation"], 2)

    def test_run_only_keeps_generation(self):
        self.event(1, "run")
        self.assertEqual(self.monitor.poll()["generation"], 1)

    def test_wrong_scope_fails_without_cursor(self):
        self.metadata["query"] = "unrelated"
        with self.assertRaises(MonitorUnavailable):
            self.monitor.poll()
        self.assertFalse(self.path.exists())

    def test_compiling_agent_is_not_healthy(self):
        self.metadata["agent_state"]["status"] = "compiling"
        with self.assertRaises(MonitorUnavailable):
            self.monitor.poll()

    def test_foreign_event_rejected(self):
        self.event(1)
        self.events[0]["monitor_id"] = "other"
        with self.assertRaises(MonitorUnavailable):
            self.monitor.poll()
        self.assertFalse(self.path.exists())

    def test_corrupt_state_fails_closed(self):
        self.path.write_text("{broken")
        with self.assertRaises(ValueError):
            self.monitor.poll()

    def test_rebinding_requires_operator_migration(self):
        self.monitor.poll()
        state = json.loads(self.path.read_text())
        state["monitor_id"] = "other"
        self.path.write_text(json.dumps(state))
        with self.assertRaises(MonitorUnavailable):
            self.monitor.poll()

    def test_invalid_monitor_path_rejected(self):
        with self.assertRaises(ValueError):
            TelemMonitorClient("../secrets")

    def test_changed_signal_refresh_and_outage(self):
        fixture = resolver_tests.Tests("test_refresh_then_hit")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        resolver = fixture.resolver
        resolver.monitor = self.monitor
        first = resolver.resolve(["France"])
        self.assertEqual(first["cache_state"], "refreshed")
        self.assertEqual(resolver.resolve(["France"])["cache_state"], "fresh_hit")
        self.event(1)
        second = resolver.resolve(["France"])
        self.assertEqual(second["cache_state"], "refreshed")
        self.assertEqual(second["monitor"]["generation"], 2)
        self.fail = True
        self.assertEqual(resolver.resolve(["France"])["reason"], "monitor_unavailable")

    def test_failed_refresh_does_not_clear_invalidation(self):
        fixture = resolver_tests.Tests("test_refresh_then_hit")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        resolver = fixture.resolver
        resolver.monitor = self.monitor
        resolver.resolve(["France"])
        self.event(1)
        fixture.partial = True
        self.assertEqual(resolver.resolve(["France"])["status"], "unresolved")
        self.assertEqual(resolver.resolve(["France"])["status"], "unresolved")
        fixture.partial = False
        self.assertEqual(resolver.resolve(["France"])["cache_state"], "refreshed")

    def test_cursor_cannot_advance_past_last_delivered_change(self):
        metadata = self.metadata

        def gap_transport(path):
            if "/agent/changes" not in path:
                return metadata
            return {
                "changes": [{"seq": 1, "kind": "run", "monitor_id": "monitor-1"}],
                "next_cursor": 5,
                "watermark": 5,
            }

        monitor = MonitorInvalidation(
            self.path, TelemMonitorClient("monitor-1", transport=gap_transport)
        )
        with self.assertRaises(MonitorUnavailable):
            monitor.poll()
        self.assertFalse(self.path.exists())

    def test_empty_cursor_gap_rejected(self):
        def transport(path):
            if "/agent/changes" not in path:
                return self.metadata
            return {"changes": [], "next_cursor": 5, "watermark": 5}

        monitor = MonitorInvalidation(
            self.path, TelemMonitorClient("monitor-1", transport=transport)
        )
        with self.assertRaises(MonitorUnavailable):
            monitor.poll()
        self.assertFalse(self.path.exists())

    def test_replayed_already_processed_event_does_not_increment(self):
        self.event(1)
        first = self.monitor.poll()

        def transport(path):
            if "/agent/changes" not in path:
                return self.metadata
            return {"changes": self.events, "next_cursor": 1, "watermark": 1}

        monitor = MonitorInvalidation(
            self.path, TelemMonitorClient("monitor-1", transport=transport)
        )
        self.assertEqual(monitor.poll(), first)

    def test_internal_sequence_gap_conservatively_invalidates(self):
        self.event(1, "run")
        self.event(5, "run")
        state = self.monitor.poll()
        self.assertEqual(state["generation"], 2)
        self.assertEqual(state["cursor"], 5)
