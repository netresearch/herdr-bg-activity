# herdr-bg-activity

A local [herdr](https://herdr.dev) plugin. herdr shows a Claude Code pane as `idle` as soon as its turn ends, even while a monitor or background shell it started is still running ([herdr#1217](https://github.com/herdrdev/herdr/issues/1217)). This plugin reads the footer Claude Code renders below its prompt box and publishes display metadata, so the sidebar can tell "ready, but background work running" from "nothing running".

It changes presentation only. The state icon, waits and notifications still follow herdr's semantic state.

## Tokens

| Scope | Token | Example |
|-------|-------|---------|
| Agent row | `$bg` | `⧗ 1 monitor, 2 shells` |
| Space row | `$bg` | `⧗ 3` |
| Space row | `$cmd` | `claude` |

Values expire 15 s after the plugin stops refreshing them.

## Setup

```sh
herdr plugin link ~/p/herdr-bg-activity/main
```

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

herdr starts the plugin when the server restores a session. To start it without restarting the server:

```sh
cd ~/p/herdr-bg-activity/main
HERDR_SOCKET_PATH=~/.config/herdr/herdr.sock setsid /usr/bin/python3 herdr_bg_activity.py >/dev/null 2>&1 &
```

A file lock keeps a single instance; a later startup instance waits until the running one exits.

## Tests

```sh
/usr/bin/python3 -m unittest discover -s tests
```
