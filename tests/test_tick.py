import unittest

from fakes import RecordingHerdr, screen

from herdr_bg_activity import HerdrError, Publisher, tick


def agent(pane, ws, status="idle", name="claude"):
    return {"pane_id": pane, "workspace_id": ws, "agent_status": status, "agent": name}


class TickTest(unittest.TestCase):
    def test_publishes_pane_and_workspace_tokens(self):
        herdr = RecordingHerdr(
            agents=[agent("w1:p1", "w1")],
            workspaces=["w1"],
            screens={"w1:p1": screen("  ⏵⏵ auto mode on · 1 monitor · ← 1 agent")},
        )
        tick(herdr, Publisher(herdr))
        self.assertEqual(
            herdr.reported("pane.report_metadata", "w1:p1")[0]["tokens"],
            {"bg": "⧗ 1 monitor"},
        )
        self.assertEqual(
            herdr.reported("workspace.report_metadata", "w1")[0]["tokens"],
            {"cmd": "claude", "bg": "⧗ 1"},
        )

    def test_working_agent_is_not_read(self):
        herdr = RecordingHerdr(
            agents=[agent("w1:p1", "w1", status="working")], workspaces=["w1"]
        )
        tick(herdr, Publisher(herdr))
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
        publisher.sent[("pane", "w2:p1")] = ({"bg": "⧗ 1 shell"}, 0.0)
        publisher.sent[("workspace", "w2")] = ({"cmd": "claude", "bg": "⧗ 1"}, 0.0)

        tick(herdr, publisher)

        self.assertEqual(
            herdr.reported("pane.report_metadata", "w1:p1")[0]["tokens"],
            {"bg": "⧗ 1 shell"},
        )
        self.assertEqual(herdr.reported("pane.report_metadata", "w2:p1"), [])
        self.assertEqual(herdr.reported("workspace.report_metadata", "w2"), [])

    def test_closed_pane_tokens_are_cleared(self):
        herdr = RecordingHerdr(agents=[], workspaces=["w1"])
        publisher = Publisher(herdr)
        publisher.sent[("pane", "w1:p9")] = ({"bg": "⧗ 1 shell"}, 0.0)
        tick(herdr, publisher)
        self.assertEqual(
            herdr.reported("pane.report_metadata", "w1:p9")[0]["tokens"], {"bg": None}
        )

    def test_other_pane_read_error_is_not_mistaken_for_a_closed_pane(self):
        herdr = RecordingHerdr(
            agents=[agent("w1:p1", "w1")], workspaces=["w1"], broken={"w1:p1"}
        )
        with self.assertRaises(HerdrError) as caught:
            tick(herdr, Publisher(herdr))
        self.assertEqual(caught.exception.code, "internal_error")


if __name__ == "__main__":
    unittest.main()
