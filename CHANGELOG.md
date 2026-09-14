# Changelog

All notable changes to this project are documented in this file. The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-09-14

First release.

### Added

- herdr plugin that marks Claude Code panes which sit at the prompt while a monitor or background shell they started is still running, a state herdr reports as `idle` (herdrdev/herdr#1217). It reads the footer below Claude Code's prompt box and publishes display tokens: `$bg` per agent (`⧗ 1 monitor, 2 shells`) and per space (`⧗ 3`), and `$cmd` per space with the detected agent names.
- Semantic state, waits and notifications stay with herdr; the tokens expire 15 seconds after the plugin stops refreshing them.
- One instance per herdr session, guarded by a lock file in `$XDG_RUNTIME_DIR` (or the temp directory) that must be a regular file owned by the current user.
- The poller keeps running through unexpected API responses and panes that close mid-poll, treats only `pane_not_found` / `workspace_not_found` as a vanished target, and exits after repeated connection failures.
- Requires herdr 0.9.0 or later and `python3` 3.10+ on Linux or macOS; standard library only.

[Unreleased]: https://github.com/netresearch/herdr-bg-activity/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/netresearch/herdr-bg-activity/releases/tag/v0.1.0
