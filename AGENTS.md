# AGENTS.md

herdr plugin, see `README.md`.

- Single file `herdr_bg_activity.py`, standard library only, started by herdr as `python3 herdr_bg_activity.py` (`herdr-plugin.toml`).
- Talks to the herdr socket API directly (one request per connection); CLI calls cost ~140 ms each and would dominate the 2 s poll. Polling instead of `events.subscribe` is deliberate: subscriptions can silently stop receiving (herdr#3124), and footer changes emit no event anyway.
- Footer parsing only looks below the last horizontal rule. `← N agent` is the agent-view hint present in every pane, not background work.
- Tests: `python3 -m unittest discover -s tests`. Format and lint: `ruff format . && ruff check .`. CI runs both via `.github/workflows/ci.yml`.
- Commits need `git commit -s` (DCO check in CI).
