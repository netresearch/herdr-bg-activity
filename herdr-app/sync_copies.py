"""Rebuild the agents-bg and spaces-bg copies from the Herdr app's shipped mods.

Run it after a herdr-app update, with the app's mods folder and its version:

    python3 herdr-app/sync_copies.py ~/.config/herdr-app/mods 0.1.14

It reads the shipped `agents/main.js` and `spaces/main.js`, normalises CRLF, applies
the bg-activity hunks below and writes `herdr-app/mods/*-bg/main.js`. Each hunk must
match exactly once; when Herdr changed the code around one, the run stops and names
the anchor, and the hunk is updated by hand.
"""

import sys
from pathlib import Path

APP = Path(sys.argv[1]).expanduser()
REPO = Path(__file__).resolve().parent / "mods"
VERSION = sys.argv[2]
MAIN = "main.js"


def apply(text, hunks):
    """Replace each anchor, which must occur exactly once."""
    for old, new in hunks:
        count = text.count(old)
        if count != 1:
            raise SystemExit(f"anchor matched {count} times: {old[:80]!r}")
        text = text.replace(old, new)
    return text


agents = (APP / "agents" / MAIN).read_text(encoding="utf-8").replace("\r\n", "\n")
agents = apply(
    agents,
    [
        (
            "// Agents in grouped or priority views;",
            "// Copy of the Herdr app's shipped `agents` mod (herdr-app "
            + VERSION
            + ", Apache License 2.0,\n"
            "// see herdr-app/LICENSE-APACHE). Changed by netresearch/herdr-bg-activity: every\n"
            "// change is marked `bg-activity` - polling and detail lines from ./bg.js, and a\n"
            "// Background section for agents waiting on background work.\n"
            "// Agents in grouped or priority views;",
        ),
        (
            'props, window, layout } from "herdr";\n',
            (
                'props, window, layout } from "herdr";\n'
                "// bg-activity: details under each agent, and agents waiting on background work in their own section.\n"
                'import { startPolling, detailLine, infoOf } from "./bg.js";\n'
            ),
        ),
        (
            (
                'const SECTION = { 4: "Needs you", 3: "Done", 2: "Working", 1: "Idle" };\n'
                'const SECTION_STATUS = { 4: "blocked", 3: "done", 2: "working" };\n'
            ),
            (
                "// bg-activity: at the prompt (idle or done) but still owning monitors or background\n"
                "// shells. That is not finished work, so it sits between Working and Idle.\n"
                "const RANK_BG = 1.5;\n"
                'const waitsOnBackground = (a) => (a.status === "idle" || a.status === "done") && Boolean(infoOf(a.address)?.bg);\n'
                'const SECTION = { 4: "Needs you", 3: "Done", 2: "Working", [RANK_BG]: "Background", 1: "Idle" }; // bg-activity\n'
                'const SECTION_STATUS = { 4: "blocked", 3: "done", 2: "working", [RANK_BG]: "background" }; // bg-activity\n'
            ),
        ),
        (
            "    if (props()?.sortMenu) return;\n",
            "    if (props()?.sortMenu) return;\n    startPolling(this, cx); // bg-activity\n",
        ),
        (
            "  rank(a) {\n",
            "  rank(a) {\n    if (waitsOnBackground(a)) return RANK_BG; // bg-activity\n",
        ),
        (
            "    const st = kidStatus(k, this.listed);\n",
            (
                "    const raw = kidStatus(k, this.listed);\n"
                "    // bg-activity: a waiting sub-agent that still owns background work.\n"
                '    const st = raw === "idle" && infoOf(k.address)?.bg ? "background" : raw;\n'
            ),
        ),
        (
            "  status(t, a, compact = false) {\n",
            (
                "  status(t, a, compact = false) {\n"
                "    // bg-activity: an hourglass for an agent waiting on background work.\n"
                '    if (a.status === "background" || (a.address && waitsOnBackground(a))) return div().w(14).flex_none().text_center().text_size(11).text_color(t.ansi3).child("⧗");\n'
            ),
        ),
        (
            (
                "      if (this.folded.has(a.address)) return [r];\n"
                "      return [r, ...subs.map((s) => this.subRow(t, s, shown, byPriority))];\n"
            ),
            (
                "      // bg-activity: the detail line under the row, aligned with the name (padding 8 + icon 16 + gap 9).\n"
                "      const d = collapsed ? null : detailLine(t, a, 33);\n"
                "      const head = d ? [r, d] : [r];\n"
                "      if (this.folded.has(a.address)) return head;\n"
                "      return [...head, ...subs.map((s) => this.subRow(t, s, shown, byPriority))];\n"
            ),
        ),
        (
            ".child(div().truncate().text_color(t[g.status] ?? t.dim).child(g.label))",
            '.child(div().truncate().text_color(g.status === "background" ? t.ansi3 : t[g.status] ?? t.dim).child(g.label)) // bg-activity',
        ),
        (
            '.on_click(() => openOverlay({ mod: "agents", kind: "popup", width: 200, height: 140, props: { sortMenu: true } }))',
            '.on_click(() => openOverlay({ mod: "agents-bg", kind: "popup", width: 200, height: 140, props: { sortMenu: true } })) // bg-activity: the copy\'s own name',
        ),
    ],
)
(REPO / "agents-bg" / MAIN).write_text(agents, encoding="utf-8")

spaces = (APP / "spaces" / MAIN).read_text(encoding="utf-8").replace("\r\n", "\n")
first = spaces.splitlines()[0]
spaces = apply(
    spaces,
    [
        (
            first + "\n",
            "// Copy of the Herdr app's shipped `spaces` mod (herdr-app "
            + VERSION
            + ", Apache License 2.0,\n"
            "// see herdr-app/LICENSE-APACHE). Changed by netresearch/herdr-bg-activity: every\n"
            "// change is marked `bg-activity` - service links, agent symbols and the background\n"
            "// count after each space name, from ./bg.js.\n" + first + "\n",
        ),
        (
            'watchFolder, window, layout } from "herdr";\n',
            (
                'watchFolder, window, layout } from "herdr";\n'
                'import { spaceTail } from "./bg.js"; // bg-activity\n'
            ),
        ),
        (
            '    const fill = color.startsWith("#") ? color : (MARK[color] ?? t[color]);\n    return v_flex()',
            (
                '    const fill = color.startsWith("#") ? color : (MARK[color] ?? t[color]);\n'
                "    const tail = spaceTail(t, w.id); // bg-activity\n    return v_flex()"
            ),
        ),
        (
            "          .child(g ? this.gitTail(g, tree, w.name, t) : div().flex_1()),\n",
            (
                "          .child(g ? this.gitTail(g, tree, w.name, t) : div().flex_1())\n"
                "          // bg-activity: service links, agent symbols and background tasks of this space.\n"
                "          .when(Boolean(tail), (el) => el.child(tail)),\n"
            ),
        ),
    ],
)
(REPO / "spaces-bg" / MAIN).write_text(spaces, encoding="utf-8")
print("rebuilt from", VERSION)
