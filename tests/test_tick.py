import json
import os
import tempfile
import unittest

from fakes import RecordingHerdr, screen

from herdr_bg_activity import SESSION_KEYS, HerdrError, Publisher, tick

SESSION = "297235f9-3c09-43cc-bee9-2aa0892653ca"
NO_SESSION = dict.fromkeys(SESSION_KEYS)


def agent(pane, ws, status="idle", name="claude", session=None):
    entry = {"pane_id": pane, "workspace_id": ws, "agent_status": status, "agent": name}
    if session:
        entry["agent_session"] = {
            "source": "herdr:claude",
            "kind": "id",
            "value": session,
        }
    return entry


def pane_tokens(bg, **session):
    return {"bg": bg, **NO_SESSION, **session}


class TickTest(unittest.TestCase):
    def setUp(self):
        self.sessions = tempfile.TemporaryDirectory()
        self.addCleanup(self.sessions.cleanup)
        self.claude = tempfile.TemporaryDirectory()
        self.addCleanup(self.claude.cleanup)

    def run_tick(self, herdr, publisher=None):
        tick(
            herdr,
            publisher or Publisher(herdr),
            sessions=self.sessions.name,
            claude_sessions=self.claude.name,
        )

    def test_publishes_pane_and_workspace_tokens(self):
        herdr = RecordingHerdr(
            agents=[agent("w1:p1", "w1")],
            workspaces=["w1"],
            screens={"w1:p1": screen("  ⏵⏵ auto mode on · 1 monitor · ← 1 agent")},
        )
        self.run_tick(herdr)
        self.assertEqual(
            herdr.reported("pane.report_metadata", "w1:p1")[0]["tokens"],
            pane_tokens("⧗ 1 monitor"),
        )
        self.assertEqual(
            herdr.reported("workspace.report_metadata", "w1")[0]["tokens"],
            {"cmd": "claude", "bg": "⧗ 1"},
        )

    def test_publishes_session_tokens_from_snapshot_and_screen(self):
        with open(os.path.join(self.sessions.name, f"{SESSION}.json"), "w") as handle:
            json.dump(
                {
                    "session_id": SESSION,
                    "model": {"id": "claude-fable-5-1"},
                    "effort": {"level": "xhigh"},
                    "context_window": {"used_percentage": 91.2},
                },
                handle,
            )
        with open(os.path.join(self.claude.name, f"{os.getpid()}.json"), "w") as handle:
            json.dump(
                {"pid": os.getpid(), "sessionId": SESSION, "bridgeSessionId": "cse_1"},
                handle,
            )
        herdr = RecordingHerdr(
            agents=[agent("w1:p1", "w1", status="working", session=SESSION)],
            workspaces=["w1"],
            screens={
                "w1:p1": screen(
                    "  ⏵⏵ auto mode on · 1 shell · ← 1 agent",
                    "",
                    "  ● main",
                    "  ◯ general-purpose  Reading files   18s · ↓ 140.1k tokens",
                )
            },
        )
        self.run_tick(herdr)
        self.assertEqual(
            herdr.reported("pane.report_metadata", "w1:p1")[0]["tokens"],
            pane_tokens(
                None, model="F51", effort="▇", agents="↳1", ctx_crit="91%", rc="⇄"
            ),
        )

    def test_working_non_claude_agent_is_not_read(self):
        herdr = RecordingHerdr(
            agents=[agent("w1:p1", "w1", status="working", name="codex")],
            workspaces=["w1"],
        )
        self.run_tick(herdr)
        self.assertEqual(herdr.reported("pane.report_metadata", "w1:p1"), [])
        self.assertEqual(
            herdr.reported("workspace.report_metadata", "w1")[0]["tokens"],
            {"cmd": "codex", "bg": None},
        )

    def test_working_claude_agent_reports_no_background_work(self):
        herdr = RecordingHerdr(
            agents=[agent("w1:p1", "w1", status="working")],
            workspaces=["w1"],
            screens={"w1:p1": screen("  ⏵⏵ auto mode on · 1 shell")},
        )
        self.run_tick(herdr)
        self.assertEqual(herdr.reported("pane.report_metadata", "w1:p1"), [])
        self.assertEqual(
            herdr.reported("workspace.report_metadata", "w1")[0]["tokens"],
            {"cmd": "claude", "bg": None},
        )

    def test_pane_closed_during_tick_skips_only_that_pane(self):
        herdr = RecordingHerdr(
            agents=[agent("w1:p1", "w1"), agent("w2:p1", "w2")],
            workspaces=["w1", "w2"],
            screens={"w1:p1": screen("  ⏵⏵ auto mode on · 1 shell")},
            missing={"w2:p1"},
        )
        publisher = Publisher(herdr)
        publisher.sent[("pane", "w2:p1")] = (pane_tokens("⧗ 1 shell"), 0.0)
        publisher.sent[("workspace", "w2")] = ({"cmd": "claude", "bg": "⧗ 1"}, 0.0)

        self.run_tick(herdr, publisher)

        self.assertEqual(
            herdr.reported("pane.report_metadata", "w1:p1")[0]["tokens"],
            pane_tokens("⧗ 1 shell"),
        )
        self.assertEqual(herdr.reported("pane.report_metadata", "w2:p1"), [])
        self.assertEqual(herdr.reported("workspace.report_metadata", "w2"), [])

    def test_closed_pane_tokens_are_cleared(self):
        herdr = RecordingHerdr(agents=[], workspaces=["w1"])
        publisher = Publisher(herdr)
        publisher.sent[("pane", "w1:p9")] = (pane_tokens("⧗ 1 shell", model="O5"), 0.0)
        self.run_tick(herdr, publisher)
        self.assertEqual(
            herdr.reported("pane.report_metadata", "w1:p9")[0]["tokens"],
            pane_tokens(None),
        )

    def test_other_pane_read_error_is_not_mistaken_for_a_closed_pane(self):
        herdr = RecordingHerdr(
            agents=[agent("w1:p1", "w1")], workspaces=["w1"], broken={"w1:p1"}
        )
        with self.assertRaises(HerdrError) as caught:
            self.run_tick(herdr)
        self.assertEqual(caught.exception.code, "internal_error")


if __name__ == "__main__":
    unittest.main()
