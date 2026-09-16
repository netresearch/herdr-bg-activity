"""Mark herdr agents that sit at the prompt while background work still runs.

herdr knows five agent states. A Claude Code pane whose turn has ended but
which still owns a running monitor or background shell reads as `idle`, the
same as a pane with nothing left to do. This process reads the footer Claude
Code renders below its prompt box ("1 monitor", "2 shells") and publishes it
as display metadata:

- pane token `bg`        e.g. "⧗ 1 monitor, 2 shells"  (Agent rows: `$bg`)
- workspace token `bg`   e.g. "⧗ 3"                     (Space rows: `$bg`)
- workspace token `cmd`  detected agent names, e.g. "claude" (Space rows: `$cmd`)

For Claude Code panes it also publishes session details:

- `model`   model abbreviation, e.g. "O5" for claude-opus-5
- `effort`  effort level as a bar, "▁" low … "█" max
- `agents`  running subagents listed below the footer, e.g. "↳2"
- `ctx`, `ctx_warn`, `ctx_crit`  context use, e.g. "67%"; exactly one is set,
  chosen by threshold, so each can carry its own colour
- `rc`      "⇄" while the session is registered for Remote Control

Model, effort and context come from a snapshot the Claude Code statusline
command writes per session (see README); Remote Control from Claude Code's own
per-process session files. herdr names the session of each pane.

Semantic state, waits and notifications stay untouched.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import socket
import stat
import sys
import time

SOURCE = "netresearch.bg-activity"
POLL_SECONDS = 2.0
REFRESH_SECONDS = 5.0
TTL_MS = 15_000
MAX_CONNECT_FAILURES = 5
QUIET_STATES = frozenset({"idle", "done"})

_RULE = re.compile(r"^─{10,}$")
_ITEM = re.compile(r"^(\d+) (monitor|shell)s?$")
_PLURAL = {"monitor": "monitors", "shell": "shells"}
# A running subagent below the footer: "◯ general-purpose  Reading …  18s · ↓ 140.1k tokens"
_SUBAGENT = re.compile(r"^\S \S+ {2,}.* · ↓ [\d.]+[kM]? tokens$")

SESSION_KEYS = ("model", "effort", "agents", "ctx", "ctx_warn", "ctx_crit", "rc")
_SESSION_ID = re.compile(r"^[0-9A-Fa-f-]{36}$")
MAX_SNAPSHOT_BYTES = 65_536
EFFORT_BARS = {"low": "▁", "medium": "▃", "high": "▅", "xhigh": "▇", "max": "█"}
CTX_WARN_PERCENT = 70
CTX_CRIT_PERCENT = 90


NOT_FOUND = frozenset({"pane_not_found", "workspace_not_found"})


class HerdrError(Exception):
    """The server answered a request with an error."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


def background_counts(screen: str) -> dict[str, int]:
    """Count background tasks named in the footer below the last horizontal rule.

    Only the lines after the prompt box are inspected, so prompt or transcript
    text such as "1 monitor still running" cannot produce a false positive.
    """
    lines = screen.splitlines()
    rules = [i for i, line in enumerate(lines) if _RULE.match(line.strip())]
    if not rules:
        return {}
    counts: dict[str, int] = {}
    for line in lines[rules[-1] + 1 :]:
        for piece in re.split(r"[·,]", line):
            match = _ITEM.match(piece.strip())
            if match:
                kind = match.group(2)
                counts[kind] = counts.get(kind, 0) + int(match.group(1))
    return counts


def describe(counts: dict[str, int]) -> str | None:
    if not counts:
        return None
    parts = [
        f"{n} {_PLURAL[kind] if n > 1 else kind}" for kind, n in sorted(counts.items())
    ]
    return "⧗ " + ", ".join(parts)


def subagent_count(screen: str) -> int:
    """Count running subagents Claude Code lists below its footer."""
    lines = screen.splitlines()
    rules = [i for i, line in enumerate(lines) if _RULE.match(line.strip())]
    if not rules:
        return 0
    return sum(1 for line in lines[rules[-1] + 1 :] if _SUBAGENT.match(line.strip()))


def model_abbrev(model_id: object) -> str | None:
    """Family initial plus version digits: claude-fable-5-1 -> F51.

    A trailing context marker ("[1m]") and a date suffix are dropped. An id
    without a family name before its version yields None.
    """
    if not isinstance(model_id, str):
        return None
    parts = model_id.split("[", 1)[0].strip().lower().removeprefix("claude-").split("-")
    if not parts[0].isalpha():
        return None
    digits = []
    for part in parts[1:]:
        if not part.isdigit() or len(part) >= 8:
            break
        digits.append(part)
    if not digits:
        return None
    return parts[0][0].upper() + "".join(digits)


def cache_dir() -> str:
    base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return os.path.join(base, "herdr-bg-activity")


def session_dir() -> str:
    return os.path.join(cache_dir(), "sessions")


def claude_sessions_dir() -> str:
    base = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
    return os.path.join(base, "sessions")


def _alive(pid: object) -> bool:
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def bridged_sessions(directory: str) -> set[str]:
    """Session ids of live Claude Code processes registered for Remote Control.

    Claude Code keeps one `<pid>.json` per process and sets `bridgeSessionId`
    once Remote Control is set up for it. Files of exited processes stay
    behind, so only live pids count.
    """
    bridged: set[str] = set()
    try:
        names = os.listdir(directory)
    except OSError:
        return bridged
    for name in names:
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(directory, name), "rb") as handle:
                raw = handle.read(MAX_SNAPSHOT_BYTES + 1)
            data = json.loads(raw) if len(raw) <= MAX_SNAPSHOT_BYTES else None
        except (OSError, ValueError):
            continue
        if (
            isinstance(data, dict)
            and isinstance(data.get("bridgeSessionId"), str)
            and isinstance(data.get("sessionId"), str)
            and _alive(data.get("pid"))
        ):
            bridged.add(data["sessionId"])
    return bridged


def read_snapshot(directory: str, session_id: object) -> dict | None:
    """Load the statusline snapshot for one session, or None if unusable."""
    if not isinstance(session_id, str) or not _SESSION_ID.match(session_id):
        return None
    try:
        with open(os.path.join(directory, f"{session_id}.json"), "rb") as handle:
            raw = handle.read(MAX_SNAPSHOT_BYTES + 1)
    except OSError:
        return None
    if len(raw) > MAX_SNAPSHOT_BYTES:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _field(data: dict, *path: str) -> object:
    for key in path:
        if not isinstance(data, dict):
            return None
        data = data.get(key)
    return data


def session_tokens(
    snapshot: dict | None, subagents: int, bridged: bool = False
) -> dict:
    tokens: dict[str, str | None] = dict.fromkeys(SESSION_KEYS)
    tokens["agents"] = f"↳{subagents}" if subagents else None
    tokens["rc"] = "⇄" if bridged else None
    if snapshot is None:
        return tokens
    tokens["model"] = model_abbrev(_field(snapshot, "model", "id"))
    level = _field(snapshot, "effort", "level")
    tokens["effort"] = EFFORT_BARS.get(level) if isinstance(level, str) else None
    percent = _field(snapshot, "context_window", "used_percentage")
    if isinstance(percent, (int, float)) and not isinstance(percent, bool):
        value = round(percent)
        key = (
            "ctx_crit"
            if value >= CTX_CRIT_PERCENT
            else "ctx_warn"
            if value >= CTX_WARN_PERCENT
            else "ctx"
        )
        tokens[key] = f"{value}%"
    return tokens


class Herdr:
    def __init__(self, socket_path: str) -> None:
        self.socket_path = socket_path

    def call(self, method: str, params: dict) -> dict:
        request = json.dumps({"id": SOURCE, "method": method, "params": params})
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
            conn.settimeout(2)
            conn.connect(self.socket_path)
            conn.sendall(request.encode() + b"\n")
            buf = b""
            while b"\n" not in buf:
                chunk = conn.recv(65536)
                if not chunk:
                    break
                buf += chunk
        response = json.loads(buf.split(b"\n", 1)[0])
        if "error" in response:
            error = response["error"]
            raise HerdrError(
                str(error.get("code", "unknown")),
                f"{method}: {error.get('message', error)}",
            )
        return response["result"]


class Publisher:
    """Send token patches only when they change or their TTL needs a refresh."""

    def __init__(self, herdr: Herdr) -> None:
        self.herdr = herdr
        self.sent: dict[tuple[str, str], tuple[dict, float]] = {}

    def publish(self, kind: str, target: str, tokens: dict, now: float) -> None:
        key = (kind, target)
        previous = self.sent.get(key)
        empty = all(v is None for v in tokens.values())
        if previous is None and empty:
            return
        if (
            previous is not None
            and previous[0] == tokens
            and (empty or now - previous[1] < REFRESH_SECONDS)
        ):
            return
        params = {f"{kind}_id": target, "source": SOURCE, "tokens": tokens}
        if not empty:
            params["ttl_ms"] = TTL_MS
        try:
            self.herdr.call(f"{kind}.report_metadata", params)
        except HerdrError as exc:
            if exc.code not in NOT_FOUND:
                raise
            # The pane or workspace is gone; forget it.
            self.sent.pop(key, None)
            return
        self.sent[key] = (tokens, now)

    def targets(self, kind: str) -> set[str]:
        return {target for k, target in self.sent if k == kind}


def tick(
    herdr: Herdr,
    publisher: Publisher,
    sessions: str | None = None,
    claude_sessions: str | None = None,
) -> None:
    now = time.monotonic()
    sessions = session_dir() if sessions is None else sessions
    claude_sessions = (
        claude_sessions_dir() if claude_sessions is None else claude_sessions
    )
    bridged: set[str] | None = None
    agents = herdr.call("agent.list", {})["agents"]
    pane_tokens: dict[str, dict] = {}
    ws_names: dict[str, set[str]] = {}
    ws_count: dict[str, int] = {}
    skipped_panes: set[str] = set()
    skipped_workspaces: set[str] = set()
    for agent in agents:
        pane, ws = agent["pane_id"], agent["workspace_id"]
        if agent.get("agent"):
            ws_names.setdefault(ws, set()).add(agent["agent"])
        quiet = agent.get("agent_status") in QUIET_STATES
        claude = agent.get("agent") == "claude"
        counts: dict[str, int] = {}
        subagents = 0
        if quiet or claude:
            try:
                read = herdr.call("pane.read", {"pane_id": pane, "source": "detection"})
            except HerdrError as exc:
                if exc.code != "pane_not_found":
                    raise
                # Closed since agent.list: leave its tokens alone for this tick.
                skipped_panes.add(pane)
                skipped_workspaces.add(ws)
                continue
            text = read["read"]["text"]
            if quiet:
                counts = background_counts(text)
            if claude:
                subagents = subagent_count(text)
        tokens = {"bg": describe(counts)}
        if claude:
            session = agent.get("agent_session") or {}
            session_id = session.get("value") if session.get("kind") == "id" else None
            if bridged is None:
                bridged = bridged_sessions(claude_sessions)
            tokens.update(
                session_tokens(
                    read_snapshot(sessions, session_id),
                    subagents,
                    session_id in bridged,
                )
            )
        else:
            tokens.update(dict.fromkeys(SESSION_KEYS))
        pane_tokens[pane] = tokens
        ws_count[ws] = ws_count.get(ws, 0) + sum(counts.values())

    for pane in publisher.targets("pane") - pane_tokens.keys() - skipped_panes:
        pane_tokens[pane] = {"bg": None, **dict.fromkeys(SESSION_KEYS)}
    for pane, tokens in pane_tokens.items():
        publisher.publish("pane", pane, tokens, now)

    workspaces = {
        w["workspace_id"] for w in herdr.call("workspace.list", {})["workspaces"]
    }
    for ws in (workspaces | publisher.targets("workspace")) - skipped_workspaces:
        names = ws_names.get(ws)
        count = ws_count.get(ws, 0)
        publisher.publish(
            "workspace",
            ws,
            {
                "cmd": ", ".join(sorted(names)) if names else None,
                "bg": f"⧗ {count}" if count else None,
            },
            now,
        )


def lock_path(socket_path: str) -> str:
    """Per-user, per-session lock file outside herdr's own directories.

    Named after the socket so a herdr-started and a hand-started instance for
    the same session meet on the same file.
    """
    base = os.environ.get("XDG_RUNTIME_DIR") or ""
    if not os.path.isdir(base):
        # WSL exports the variable without systemd-logind ever creating the
        # directory, so a set value is not a usable one. The shared temp
        # directory is no substitute: it is world-writable, so another user can
        # plant this predictable name first, and acquire_lock then refuses the
        # file and the plugin never starts. The plugin's own cache directory is
        # private to the user. A lock is runtime state rather than cache, but
        # it is one file in a directory that is already ours.
        base = cache_dir()
        os.makedirs(base, mode=0o700, exist_ok=True)
    digest = hashlib.sha256(os.path.realpath(socket_path).encode()).hexdigest()[:16]
    return os.path.join(base, f"herdr-bg-activity-{os.getuid()}-{digest}.lock")


def acquire_lock(path: str) -> int:
    """Block until the lock is ours.

    The path is predictable, so a planted symlink is refused and so is a file
    another user created first, which could otherwise hold the lock and block
    startup forever. Both directories lock_path picks are private to the user;
    this stays as the check that does not depend on that.
    """
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            raise PermissionError(f"refusing lock file not owned by this user: {path}")
        os.fchmod(fd, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX)
    except BaseException:
        os.close(fd)
        raise
    return fd


def main() -> int:
    socket_path = os.environ.get("HERDR_SOCKET_PATH")
    if not socket_path:
        print("HERDR_SOCKET_PATH is not set", file=sys.stderr)
        return 1

    # One instance per herdr session. A server restart starts a new instance
    # while the previous one is still counting its connection failures, so wait
    # for the lock instead of giving up.
    lock = acquire_lock(lock_path(socket_path))  # noqa: F841 - held until exit

    herdr = Herdr(socket_path)
    return run(herdr, Publisher(herdr))


def run(herdr: Herdr, publisher: Publisher, sleep=time.sleep) -> int:
    """Poll until herdr stays unreachable; any other failure only skips a tick.

    A crash would remove the markers until the next server start without any
    visible sign, so unexpected response shapes are logged and retried.
    """
    failures = 0
    last_error = None
    while True:
        try:
            tick(herdr, publisher)
            failures = 0
        except OSError as exc:
            failures += 1
            if failures >= MAX_CONNECT_FAILURES:
                print(f"herdr unreachable, exiting: {exc}", file=sys.stderr)
                return 0
        except Exception as exc:  # noqa: BLE001 - a crash would hide the markers silently
            failures = 0  # herdr answered, so the connection-failure streak is over
            message = f"{type(exc).__name__}: {exc}"
            if message != last_error:
                print(f"tick failed: {message}", file=sys.stderr)
                last_error = message
        sleep(POLL_SECONDS)


if __name__ == "__main__":
    sys.exit(main())
