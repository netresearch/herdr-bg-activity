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

Values expire 15 s after the plugin stops refreshing them.

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
  ["agent", { token = "$bg", fg = "#fabd2f" }],
]

[ui.sidebar.spaces]
rows = [
  ["state_icon", "workspace", "$cmd", { token = "$bg", fg = "#fabd2f" }],
  ["branch", "git_status"],
]
```

A file lock in `$XDG_RUNTIME_DIR` (or the temp directory) keeps one instance per herdr session; a new instance waits until the previous one exits.

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
