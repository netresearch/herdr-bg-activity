# AGENTS.md

Last updated: 2026-09-14

## Overview

A herdr plugin that marks agent panes idle at the prompt while a monitor or background shell still runs (herdrdev/herdr#1217). For installation, tokens and sidebar configuration see `README.md`.

## Setup

- `python3` 3.10+ (standard library only), herdr 0.9.0+ for a live run.
- Hooks: `pre-commit install --install-hooks` (ruff, whitespace, TOML/YAML checks).
- Link a working copy into herdr with `herdr plugin link .`.

## Architecture

- Single file `herdr_bg_activity.py`, started by herdr as `python3 herdr_bg_activity.py` (`herdr-plugin.toml`, `[[startup]]`).
- Talks to the herdr socket API directly (one request per connection); CLI calls cost ~140 ms each and would dominate the 2 s poll. Polling instead of `events.subscribe` is deliberate: subscriptions can silently stop receiving (herdrdev/herdr#3124), and footer changes emit no event anyway.
- Footer parsing only looks below the last horizontal rule. `← N agent` is the agent-view hint present in every pane, not background work. Running subagents are the lines below the footer ending in `· ↓ <n> tokens`; the `● main` line is not counted.
- Model, effort and context use come from `${XDG_CACHE_HOME:-~/.cache}/herdr-bg-activity/sessions/<session_id>.json`, written by the user's Claude Code statusline command (contract in `README.md`); the session id comes from `agent.list[].agent_session`. The file name is only used when the id looks like a UUID, and files over 64 KiB are ignored.
- Remote Control comes from Claude Code's `~/.claude/sessions/<pid>.json` (`bridgeSessionId` set, pid alive). The statusline input's `remote` field is not Remote Control: it stayed unset in a session registered for it (measured on Claude Code 2.1.270).
- Context use is published under one of three keys (`ctx`, `ctx_warn`, `ctx_crit`) because herdr's numeric sidebar rules parse the whole value and `67%` is not a number.
- Only `pane_not_found` / `workspace_not_found` count as a vanished target; every other error reaches `run()`, which logs it and keeps polling.

## Commands

```bash
python3 -m unittest discover -s tests   # tests
ruff format --check . && ruff check .   # format and lint, as CI runs them
pre-commit run --all-files              # all local hooks
HERDR_SOCKET_PATH=~/.config/herdr/herdr.sock python3 herdr_bg_activity.py  # run against a live server
```

## Testing

Tests live in `tests/` and use `unittest` with fakes from `tests/fakes.py`; no network or herdr server needed. CI (`.github/workflows/ci.yml`) runs them on Python 3.10 and 3.14, Linux and macOS.

## Development Workflow

- Branch, pull request, merge commit; `main` requires the CI checks and resolved threads.
- Commits need `git commit -s` (DCO check in CI).
- Releases: bump `version` in `herdr-plugin.toml`, add a `CHANGELOG.md` section, merge, then push a signed `vX.Y.Z` tag on `main`; `.github/workflows/release.yml` publishes the GitHub Release.
