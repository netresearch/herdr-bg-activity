"""Mark herdr agents that sit at the prompt while background work still runs.

herdr knows five agent states. A Claude Code pane whose turn has ended but
which still owns a running monitor or background shell reads as `idle`, the
same as a pane with nothing left to do. This process reads the footer Claude
Code renders below its prompt box ("1 monitor", "2 shells") and publishes it
as display metadata:

- pane token `bg`        e.g. "⧗ 1 monitor, 2 shells"  (Agent rows: `$bg`)
- workspace token `bg`   e.g. "⧗ 3"                     (Space rows: `$bg`)
- workspace token `cmd`  detected agent names, e.g. "claude" (Space rows: `$cmd`)

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
import tempfile
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


def tick(herdr: Herdr, publisher: Publisher) -> None:
    now = time.monotonic()
    agents = herdr.call("agent.list", {})["agents"]
    pane_bg: dict[str, str | None] = {}
    ws_names: dict[str, set[str]] = {}
    ws_count: dict[str, int] = {}
    skipped_panes: set[str] = set()
    skipped_workspaces: set[str] = set()
    for agent in agents:
        pane, ws = agent["pane_id"], agent["workspace_id"]
        if agent.get("agent"):
            ws_names.setdefault(ws, set()).add(agent["agent"])
        counts: dict[str, int] = {}
        if agent.get("agent_status") in QUIET_STATES:
            try:
                read = herdr.call("pane.read", {"pane_id": pane, "source": "detection"})
            except HerdrError as exc:
                if exc.code != "pane_not_found":
                    raise
                # Closed since agent.list: leave its tokens alone for this tick.
                skipped_panes.add(pane)
                skipped_workspaces.add(ws)
                continue
            counts = background_counts(read["read"]["text"])
        pane_bg[pane] = describe(counts)
        ws_count[ws] = ws_count.get(ws, 0) + sum(counts.values())

    for pane in publisher.targets("pane") - pane_bg.keys() - skipped_panes:
        pane_bg[pane] = None
    for pane, value in pane_bg.items():
        publisher.publish("pane", pane, {"bg": value}, now)

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
    base = os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()
    digest = hashlib.sha256(os.path.realpath(socket_path).encode()).hexdigest()[:16]
    return os.path.join(base, f"herdr-bg-activity-{os.getuid()}-{digest}.lock")


def acquire_lock(path: str) -> int:
    """Block until the lock is ours.

    The temp directory may be shared and the path is predictable, so a planted
    symlink is refused and so is a file another user created first, which
    could otherwise hold the lock and block startup forever.
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
