# herdr-bg-activity

[![CI](https://github.com/netresearch/herdr-bg-activity/actions/workflows/ci.yml/badge.svg)](https://github.com/netresearch/herdr-bg-activity/actions/workflows/ci.yml) [![License: MIT](https://img.shields.io/github/license/netresearch/herdr-bg-activity)](LICENSE)

A [herdr](https://herdr.dev) plugin. herdr shows a Claude Code pane as `idle` as soon as its turn ends, even while a monitor or background shell it started is still running ([herdr#1217](https://github.com/herdrdev/herdr/issues/1217)). This plugin reads the footer Claude Code renders below its prompt box and publishes display metadata, so the sidebar can tell "ready, but background work running" from "nothing running".

The footer format (`⏵⏵ auto mode on · 1 monitor · ← 1 agent`) belongs to Claude Code and was captured on 2.1.270; if a Claude Code update renames it, the tokens simply stop appearing.

It changes presentation only. The state icon, waits and notifications still follow herdr's semantic state.

## Tokens

| Scope | Token | Example |
|-------|-------|---------|
| Agent row | `$bg` | `⧗ 1 monitor, 2 shells` |
| Space row | `$bg` | `⧗ 3` |
| Space row | `$cmd` | `claude` |
| Space row | `$icon` | `✻ π` symbols of the detected agents |
| Agent row | `$icon` | `✻` claude, `π` pi; other agents keep their name |
| Agent row | `$model` | `O5` (claude-opus-5), `F51`, `H45` |
| Agent row | `$effort` | `▁` low, `▃` medium, `▅` high, `▇` xhigh, `█` max |
| Agent row | `$agents` | `↳2` running subagents |
| Agent row | `$ctx`, `$ctx_warn`, `$ctx_crit` | `67%` context used; below 70 %, from 70 %, from 90 % |
| Agent row | `$rc` | `⇄` while the session is registered for Remote Control |

Values expire 15 s after the plugin stops refreshing them. `$agents` is read from the list of running subagents Claude Code shows below its footer. `$rc` comes from Claude Code's per-process files in `~/.claude/sessions/` (or `$CLAUDE_CONFIG_DIR/sessions/`): a live process whose file carries a `bridgeSessionId`. Whether that registration is currently connected is not recorded there. `$model`, `$effort` and the context tokens need the statusline snapshot described below; without it they stay empty.

### Claude Code statusline snapshot

Only the input of Claude Code's statusline command carries effort and context use, so the statusline has to hand them over. Add this to your statusline script, after it has read its input into `$input`. It needs Bash (`[[ =~ ]]`, here-strings) and `jq`; a POSIX `sh` script such as one run by dash rejects it:

```bash
sid=$(jq -r '.session_id // empty' <<<"$input")
if [[ "$sid" =~ ^[0-9a-fA-F-]{36}$ ]]; then
    snap="${XDG_CACHE_HOME:-$HOME/.cache}/herdr-bg-activity/sessions"
    if (umask 077 && mkdir -p "$snap") 2>/dev/null && tmp=$(mktemp "$snap/.$sid.XXXXXX" 2>/dev/null); then
        if jq -c '{session_id, model: {id: .model.id}, effort: {level: .effort.level},
                   context_window: {used_percentage: .context_window.used_percentage}}' <<<"$input" >"$tmp" 2>/dev/null; then
            mv -f "$tmp" "$snap/$sid.json"
        else
            rm -f "$tmp"
        fi
    fi
    find "$snap" -maxdepth 1 -name '*.json' -mtime +7 -delete 2>/dev/null
fi
```

The plugin reads `<session_id>.json` for each Claude Code pane, using the session id herdr reports for it. The statusline runs when Claude Code redraws it, so a snapshot is as fresh as the session's last activity.

## Requirements

- herdr 0.9.0 or later, Linux or macOS
- `python3` (3.10+) on the herdr server's `PATH`; standard library only

## Install

```sh
herdr plugin install netresearch/herdr-bg-activity
```

herdr starts plugins when the server restores a session, so the plugin runs after the next `herdr server stop` and restart.

Add the tokens to `~/.config/herdr/config.toml`:

```toml
[ui.sidebar.agents]
rows = [
  ["state_icon", "terminal_title_stripped"],
  [
    "$icon",
    "$model",
    # Effort colours follow Claude Code's /effort picker (dark theme); max has no
    # static colour there, so it gets Claude's accent colour.
    { token = "$effort", rules = [
      { equals = "▁", fg = "#ffc107" },
      { equals = "▃", fg = "#4eba65" },
      { equals = "▅", fg = "#b1b9f9" },
      { equals = "▇", fg = "#af87ff" },
      { equals = "█", fg = "#d77757" },
    ] },
    "$agents",
    "$ctx",
    { token = "$ctx_warn", fg = "#fabd2f" },
    { token = "$ctx_crit", fg = "#fb4934" },
    { token = "$rc", fg = "#b8bb26" },
    { token = "$bg", fg = "#fabd2f" },
  ],
]

[ui.sidebar.spaces]
rows = [
  ["state_icon", "workspace", "$icon", { token = "$bg", fg = "#fabd2f" }],
  ["branch", "git_status"],
]
```

A file lock in `$XDG_RUNTIME_DIR` — or, where that names no existing directory, in `${XDG_CACHE_HOME:-~/.cache}/herdr-bg-activity/` — keeps one instance per herdr session; a new instance waits until the previous one exits.

## Herdr app

The Herdr desktop app has no herdr plugins; it is extended with mods. `herdr-app/` holds the same features for it, plus links to the services your sessions start:

- **Agents list** (`agents-bg`, a copy of the shipped `agents` mod): a detail line under each agent with model, effort, subagents, context use, Remote Control and background work (`⧗ 1 shell`). An agent that waits at the prompt while it still owns background work is listed under **Background**, not **Done**.
- **Spaces list** (`spaces-bg`, a copy of the shipped `spaces` mod): agent symbols and the number of background tasks after each space name.
- **Service links** in both lists, opened in the browser on click:
  - a TCP listener whose process descends from a terminal's shell (below a coding agent only through a shell, so its MCP servers are left out), as `:5173` → `http://localhost:5173`;
  - a Docker container with a published port, placed by its compose working folder;
  - a running DDEV project, as its primary URL.

  A service without such a parent goes to a pane that works inside its project (git root, compose folder or DDEV root).

`agents-bg/collect.py` does the work: the mod runs it with `python3 -c` on each machine that holds agents, through herdr-core. It needs `python3`, `hc`, `ss`, and optionally `docker` and `ddev` there; it does not run on Windows. A WSL machine's ports open as `localhost` from an app on Windows (WSL's localhost forwarding). Model, effort and context need the statusline snapshot above.

Install, with the app's home at `~/.config/herdr-app` (on Windows `%USERPROFILE%\.config\herdr-app`):

```sh
cp -R herdr-app/mods/agents-bg herdr-app/mods/spaces-bg ~/.config/herdr-app/mods/
cp herdr-app/layouts/main-bg.json ~/.config/herdr-app/layouts/
herdr-app check ~/.config/herdr-app/mods/agents-bg
herdr-app check ~/.config/herdr-app/mods/spaces-bg
herdr-app do layout.switch '{"name":"main-bg"}'
```

`main-bg` is the shipped `main` layout with these two mods in place of `agents` and `spaces`; `ctrl-shift-l` switches back. The copies do not follow Herdr's updates of `agents`, `spaces` and `main`. They are taken from herdr-app 0.1.13 under the Apache License 2.0 (`herdr-app/LICENSE-APACHE`), and each `main.js` names what it changes.

Claude Code itself reports such an agent as `done` (its OSC 7501 status counts subagents and workflows as running work, not shells or monitors), so Herdr's sound, notification and tab status still say done; the mods change only what the lists show.

## Verify a release download

Each GitHub Release carries the tagged source archive, `SHA256SUMS.txt`, and SLSA build provenance for both:

```sh
gh attestation verify herdr-bg-activity-vX.Y.Z.tar.gz --repo netresearch/herdr-bg-activity
sha256sum --check SHA256SUMS.txt
```

## Development

```sh
herdr plugin link .
python3 -m unittest discover -s tests
ruff format --check . && ruff check .
```

To run a working copy against a live server without restarting it:

```sh
HERDR_SOCKET_PATH=~/.config/herdr/herdr.sock python3 herdr_bg_activity.py
```

## License

MIT, see [LICENSE](LICENSE).
