# Changelog

All notable changes to this project are documented in this file. The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- The instance lock treats an `XDG_RUNTIME_DIR` that names no existing directory like an unset one, instead of failing. WSL exports the variable without systemd-logind ever creating the directory, so opening the lock raised `FileNotFoundError` and herdr recorded the plugin as `startup … failed` before a single token was published.

### Changed

- The fallback lock directory is `${XDG_CACHE_HOME:-~/.cache}/herdr-bg-activity/`, created with mode 0700, rather than the shared temp directory. A predictable name in a world-writable directory can be planted by another local user, and `acquire_lock` then refuses the file and the plugin never starts (CWE-377).

## [0.2.0] - 2026-09-14

### Added

- Session details for Claude Code panes as agent-row tokens: `$model` (model abbreviation such as `O5`, `F51`, `H45`), `$effort` (a bar per effort level, `▁` low to `█` max), `$agents` (running subagents listed below Claude Code's footer, `↳2`), `$ctx` / `$ctx_warn` / `$ctx_crit` (context use, one key per threshold at 70 % and 90 %, so each can carry its own colour) and `$rc` (`⇄` while a live Claude Code process of the session is registered for Remote Control).
- Model, effort and context use come from a per-session snapshot the Claude Code statusline command writes to `${XDG_CACHE_HOME:-~/.cache}/herdr-bg-activity/sessions/<session_id>.json`; the README documents the Bash snippet and a sidebar configuration with colours. Without the snapshot those tokens stay empty.

### Changed

- Claude Code panes are read in every agent state, because the subagent list is shown while the agent works. The `$bg` marker is still computed only for idle and done panes.

## [0.1.0] - 2026-09-14

First release.

### Added

- herdr plugin that marks Claude Code panes which sit at the prompt while a monitor or background shell they started is still running, a state herdr reports as `idle` (herdrdev/herdr#1217). It reads the footer below Claude Code's prompt box and publishes display tokens: `$bg` per agent (`⧗ 1 monitor, 2 shells`) and per space (`⧗ 3`), and `$cmd` per space with the detected agent names.
- Semantic state, waits and notifications stay with herdr; the tokens expire 15 seconds after the plugin stops refreshing them.
- One instance per herdr session, guarded by a lock file in `$XDG_RUNTIME_DIR` (or the temp directory) that must be a regular file owned by the current user.
- The poller keeps running through unexpected API responses and panes that close mid-poll, treats only `pane_not_found` / `workspace_not_found` as a vanished target, and exits after repeated connection failures.
- Requires herdr 0.9.0 or later and `python3` 3.10+ on Linux or macOS; standard library only.

[Unreleased]: https://github.com/netresearch/herdr-bg-activity/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/netresearch/herdr-bg-activity/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/netresearch/herdr-bg-activity/releases/tag/v0.1.0
