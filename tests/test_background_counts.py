import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from herdr_bg_activity import background_counts, describe

RULE = "─" * 60


def screen(*footer: str, above: str = "● done.") -> str:
    return "\n".join([above, RULE, "❯", RULE, *footer])


class BackgroundCountsTest(unittest.TestCase):
    def test_monitor_next_to_agent_view_hint(self):
        text = screen(
            "  ~/p/t3x-nr-vault (dev)  │ ctx 423k · ↻ 388.1M · $913.47",
            "  ⏵⏵ auto mode on · 1 monitor · ← 1 agent",
        )
        self.assertEqual(background_counts(text), {"monitor": 1})

    def test_shell(self):
        text = screen("  ~/p (dev)", "  ⏵⏵ auto mode on · 1 shell · ← 1 agent")
        self.assertEqual(background_counts(text), {"shell": 1})

    def test_plural_comma_joined(self):
        text = screen("  ⏵⏵ bypass permissions on · 2 shells, 1 monitor")
        self.assertEqual(background_counts(text), {"shell": 2, "monitor": 1})

    def test_agent_view_hint_alone_is_not_background_work(self):
        text = screen("  ⏵⏵ auto mode on (shift+tab to cycle) · ← 1 agent")
        self.assertEqual(background_counts(text), {})

    def test_transcript_above_prompt_box_is_ignored(self):
        text = screen(
            "  ⏵⏵ auto mode on · ← 1 agent",
            above="❯ list what runs · 2 shells, 1 monitor · then stop",
        )
        self.assertEqual(background_counts(text), {})

    def test_no_prompt_box(self):
        self.assertEqual(background_counts("plain shell output · 1 shell"), {})


class DescribeTest(unittest.TestCase):
    def test_empty(self):
        self.assertIsNone(describe({}))

    def test_pluralises_and_sorts(self):
        self.assertEqual(describe({"shell": 2, "monitor": 1}), "⧗ 1 monitor, 2 shells")


if __name__ == "__main__":
    unittest.main()
