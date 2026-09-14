# AGENTS.md

Local herdr plugin, see `README.md`.

- Single file `herdr_bg_activity.py`, stdlib only, run with `/usr/bin/python3`.
- Talks to the herdr socket API directly (one request per connection); CLI calls cost ~140 ms each and would dominate the 2 s poll.
- Footer parsing only looks below the last horizontal rule. `← N agent` is the agent-view hint present in every pane, not background work.
- Tests: `/usr/bin/python3 -m unittest discover -s tests`. Format: `ruff format . && ruff check .`.
