import json
import os
import subprocess
import sys
import tempfile
import unittest

from fakes import screen

from herdr_bg_activity import (
    MAX_SNAPSHOT_BYTES,
    SESSION_KEYS,
    bridged_sessions,
    model_abbrev,
    read_snapshot,
    session_tokens,
    subagent_count,
)

SESSION = "297235f9-3c09-43cc-bee9-2aa0892653ca"


class ModelAbbrevTest(unittest.TestCase):
    def test_current_model_ids(self):
        for model_id, expected in [
            ("claude-opus-5", "O5"),
            ("claude-opus-5[1m]", "O5"),
            ("claude-sonnet-5", "S5"),
            ("claude-fable-5-1", "F51"),
            ("claude-haiku-4-5-20251001", "H45"),
        ]:
            with self.subTest(model_id=model_id):
                self.assertEqual(model_abbrev(model_id), expected)

    def test_unusable_ids_yield_none(self):
        for model_id in [None, 5, "", "claude-3-5-sonnet-20241022", "opus"]:
            with self.subTest(model_id=model_id):
                self.assertIsNone(model_abbrev(model_id))


class SubagentCountTest(unittest.TestCase):
    def test_counts_listed_subagents_but_not_main(self):
        text = screen(
            "  ⏵⏵ auto mode on · 1 shell · ← 1 agent",
            "",
            "  ● main",
            "  ◯ general-purpose  Reading PHPStan errors      2h 3m 34s · ↓ 477.8k tokens",
            "  ◯ general-purpose  Documenting ADR-003         21m 11s · ↓ 419.7k tokens",
        )
        self.assertEqual(subagent_count(text), 2)

    def test_hint_without_list_is_zero(self):
        text = screen("  ⏵⏵ auto mode on · /tasks to see subagents · ← 1 agent")
        self.assertEqual(subagent_count(text), 0)

    def test_transcript_above_the_prompt_is_ignored(self):
        text = screen(
            "  ⏵⏵ auto mode on",
            above="◯ general-purpose  Old run   1m · ↓ 1.0k tokens",
        )
        self.assertEqual(subagent_count(text), 0)


class ReadSnapshotTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)

    def write(self, name, content):
        with open(os.path.join(self.dir.name, name), "w", encoding="utf-8") as handle:
            handle.write(content)

    def test_reads_a_valid_snapshot(self):
        self.write(f"{SESSION}.json", json.dumps({"session_id": SESSION}))
        self.assertEqual(read_snapshot(self.dir.name, SESSION), {"session_id": SESSION})

    def test_rejects_session_ids_that_are_not_uuids(self):
        self.write("x.json", "{}")
        for session_id in ["x", "../x", None, f"{SESSION}/../x"]:
            with self.subTest(session_id=session_id):
                self.assertIsNone(read_snapshot(self.dir.name, session_id))

    def test_missing_garbage_oversized_and_non_object_files_yield_none(self):
        self.assertIsNone(read_snapshot(self.dir.name, SESSION))
        for content in ["not json", "[1, 2]", " " * (MAX_SNAPSHOT_BYTES + 1) + "{}"]:
            with self.subTest(content=content[:10]):
                self.write(f"{SESSION}.json", content)
                self.assertIsNone(read_snapshot(self.dir.name, SESSION))


class BridgedSessionsTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)

    def write(self, pid, **fields):
        with open(os.path.join(self.dir.name, f"{pid}.json"), "w") as handle:
            json.dump({"pid": pid, **fields}, handle)

    def test_only_live_processes_with_a_bridge_count(self):
        exited = subprocess.Popen([sys.executable, "-c", ""])
        exited.wait()
        self.write(os.getpid(), sessionId="live-bridged", bridgeSessionId="cse_1")
        self.write(os.getppid(), sessionId="live-plain")
        self.write(exited.pid, sessionId="exited-bridged", bridgeSessionId="cse_2")
        with open(os.path.join(self.dir.name, "broken.json"), "w") as handle:
            handle.write("not json")
        self.assertEqual(bridged_sessions(self.dir.name), {"live-bridged"})

    def test_missing_directory_is_empty(self):
        self.assertEqual(bridged_sessions(os.path.join(self.dir.name, "none")), set())


class SessionTokensTest(unittest.TestCase):
    def snapshot(self, percent=48.8, level="high"):
        return {
            "session_id": SESSION,
            "model": {"id": "claude-opus-5[1m]"},
            "effort": {"level": level},
            "context_window": {"used_percentage": percent},
        }

    def test_full_snapshot(self):
        self.assertEqual(
            session_tokens(self.snapshot(), 2, bridged=True),
            {
                "model": "O5",
                "effort": "▅",
                "agents": "↳2",
                "ctx": "49%",
                "ctx_warn": None,
                "ctx_crit": None,
                "rc": "⇄",
            },
        )

    def test_context_threshold_picks_exactly_one_key(self):
        for percent, key in [
            (69.4, "ctx"),
            (69.5, "ctx_warn"),
            (89, "ctx_warn"),
            (90, "ctx_crit"),
        ]:
            with self.subTest(percent=percent):
                tokens = session_tokens(self.snapshot(percent=percent), 0)
                set_keys = [k for k in ("ctx", "ctx_warn", "ctx_crit") if tokens[k]]
                self.assertEqual(set_keys, [key])

    def test_effort_levels_map_to_bars(self):
        bars = [
            session_tokens(self.snapshot(level=level), 0)["effort"]
            for level in ["low", "medium", "high", "xhigh", "max", "ultra", None]
        ]
        self.assertEqual(bars, ["▁", "▃", "▅", "▇", "█", None, None])

    def test_missing_fields_and_no_snapshot_leave_tokens_empty(self):
        empty = dict.fromkeys(SESSION_KEYS)
        self.assertEqual(session_tokens(None, 0), empty)
        self.assertEqual(session_tokens({"remote": False}, 0), empty)
        self.assertEqual(
            session_tokens({"context_window": {"used_percentage": True}}, 0), empty
        )
        self.assertEqual(session_tokens(None, 1)["agents"], "↳1")
        self.assertEqual(session_tokens(None, 0, bridged=True)["rc"], "⇄")


if __name__ == "__main__":
    unittest.main()
