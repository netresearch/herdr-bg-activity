import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from herdr_bg_activity import HerdrError

RULE = "─" * 60


def screen(*footer: str, above: str = "● done.") -> str:
    return "\n".join([above, RULE, "❯", RULE, *footer])


class RecordingHerdr:
    """Answers from fixed data and records every metadata report."""

    def __init__(self, agents=(), workspaces=(), screens=None, missing=()):
        self.agents = list(agents)
        self.workspaces = list(workspaces)
        self.screens = dict(screens or {})
        self.missing = set(missing)
        self.reports = []

    def call(self, method, params):
        if method == "agent.list":
            return {"agents": self.agents}
        if method == "workspace.list":
            return {"workspaces": [{"workspace_id": w} for w in self.workspaces]}
        if method == "pane.read":
            if params["pane_id"] in self.missing:
                raise HerdrError("pane.read: pane not found")
            return {"read": {"text": self.screens[params["pane_id"]]}}
        if method.endswith(".report_metadata"):
            target = params.get("pane_id") or params.get("workspace_id")
            if target in self.missing:
                raise HerdrError(f"{method}: not found")
            self.reports.append((method, target, params))
            return {}
        raise AssertionError(f"unexpected call {method}")

    def reported(self, method, target):
        return [p for m, t, p in self.reports if m == method and t == target]
