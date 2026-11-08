"""Collect background activity of the coding agents on one herdr-core machine.

The agents-bg mod runs this file as `python3 -c <source>` on each machine
that hosts agents, through herdr-core, and gets one JSON object:

    {"terminals": {"t2": {"bg": "⧗ 1 monitor", "agents": 2, "model": "O5",
                          "effort": "high", "ctx": 67, "rc": true}},
     "error": null}

The parsing follows netresearch/herdr-bg-activity (herdr_bg_activity.py):
background work is read from the footer Claude Code draws below its prompt
box, and only while the agent waits at the prompt (idle or done). Model,
effort and context use come from the statusline snapshot described in that
plugin's README; Remote Control from Claude Code's per-process session files.
"""

import json
import os
import re
import shutil
import subprocess
import sys

QUIET = {"idle", "done"}
CLAUDE = {"claude-code", "claude"}
MAX_FILE_BYTES = 65_536

_RULE = re.compile(r"^─{10,}$")
_ITEM = re.compile(r"^(\d+) (monitor|shell)s?$")
_PLURAL = {"monitor": "monitors", "shell": "shells"}
_SUBAGENT = re.compile(r"^\S \S+ {2,}.* · ↓ [\d.]+[kM]? tokens$")
_SESSION_ID = re.compile(r"^[0-9A-Fa-f-]{36}$")


def footer(screen):
    lines = screen.splitlines()
    rules = [i for i, line in enumerate(lines) if _RULE.match(line.strip())]
    return lines[rules[-1] + 1 :] if rules else []


def background_counts(lines):
    counts = {}
    for line in lines:
        for piece in re.split(r"[·,]", line):
            match = _ITEM.match(piece.strip())
            if match:
                kind = match.group(2)
                counts[kind] = counts.get(kind, 0) + int(match.group(1))
    return counts


def describe(counts):
    if not counts:
        return None
    parts = [
        f"{n} {_PLURAL[kind] if n > 1 else kind}" for kind, n in sorted(counts.items())
    ]
    return "⧗ " + ", ".join(parts)


def model_abbrev(model_id):
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


def read_json(path):
    try:
        with open(path, "rb") as handle:
            raw = handle.read(MAX_FILE_BYTES + 1)
        if len(raw) > MAX_FILE_BYTES:
            return None
        data = json.loads(raw)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def field(data, *path):
    for key in path:
        if not isinstance(data, dict):
            return None
        data = data.get(key)
    return data


def alive(pid):
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def hc_binary():
    found = shutil.which("hc")
    if found:
        return found
    local = os.path.expanduser("~/.local/bin/hc")
    return local if os.path.exists(local) else "hc"


def hc(binary, *args):
    result = subprocess.run(
        [binary, *args, "--json"],
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"hc {args[0]}: {result.stderr.strip() or result.returncode}"
        )
    return json.loads(result.stdout)


def session_dirs():
    cache = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    claude = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
    return (
        os.path.join(cache, "herdr-bg-activity", "sessions"),
        os.path.join(claude, "sessions"),
    )


def claude_details(binary, address, subagents):
    snapshots, processes = session_dirs()
    info = {"agents": subagents or None}
    pid = field(hc(binary, "get", address), "foreground", "pid")
    process = read_json(os.path.join(processes, f"{pid}.json")) if alive(pid) else None
    session_id = field(process, "sessionId")
    info["rc"] = isinstance(field(process, "bridgeSessionId"), str)
    if not isinstance(session_id, str) or not _SESSION_ID.match(session_id):
        return info
    snapshot = read_json(os.path.join(snapshots, f"{session_id}.json"))
    info["model"] = model_abbrev(field(snapshot, "model", "id"))
    level = field(snapshot, "effort", "level")
    info["effort"] = level if isinstance(level, str) else None
    percent = field(snapshot, "context_window", "used_percentage")
    if isinstance(percent, (int, float)) and not isinstance(percent, bool):
        info["ctx"] = round(percent)
    return info


def collect():
    binary = hc_binary()
    found = {}
    for terminal in hc(binary, "ls").get("terminals", []):
        address, app, status = (
            terminal.get("address"),
            terminal.get("agent"),
            terminal.get("status"),
        )
        if not address or not status:
            continue
        quiet, claude = status in QUIET, app in CLAUDE
        if not (quiet or claude):
            continue
        try:
            lines = footer(hc(binary, "read", address).get("text", ""))
            info = {"bg": describe(background_counts(lines)) if quiet else None}
            if claude:
                subagents = sum(1 for line in lines if _SUBAGENT.match(line.strip()))
                info.update(claude_details(binary, address, subagents))
        except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired):
            # Gone since `hc ls`, or one read failed: skip it for this round.
            continue
        found[address] = {k: v for k, v in info.items() if v not in (None, False)}
    return found


# --- ports mode: services the sessions started, as links -------------------------
#
# Three sources, each reported with what the mod needs to place it:
# - TCP listeners of this user's processes (`ss -ltnpH`). A listener belongs to the
#   terminal whose shell it descends from. Below a coding agent only work started
#   through a shell counts (Bash tool, background shells); a non-shell child of the
#   agent is one of its MCP servers or helpers and is left out.
# - Docker containers with published ports, placed by their compose working_dir.
#   DDEV's own containers are left out: DDEV is listed by its project URL instead.
# - Running DDEV projects (`ddev list -j`): primary URL and project root.

SHELLS = {"bash", "sh", "zsh", "fish", "dash", "ksh"}
AGENT_PROGRAMS = {"claude", "codex", "opencode", "pi", "hermes", "herdr", "herdr-core"}
OPENABLE = {"0.0.0.0", "*", "::", "[::]", "127.0.0.1", "::1", "[::1]"}
_SS_USER = re.compile(r'\("([^"]*)",pid=(\d+)')
_DOCKER_PORT = re.compile(r"^(.*):(\d+)->(\d+)/tcp$")


def proc_stat(pid):
    try:
        with open(f"/proc/{pid}/stat", "rb") as handle:
            raw = handle.read().decode("utf-8", "replace")
    except OSError:
        return None
    # comm sits in parentheses and may itself contain spaces or parentheses.
    head, _, tail = raw.rpartition(")")
    fields = tail.split()
    if len(fields) < 2:
        return None
    return head.split("(", 1)[1], int(fields[1])


def run_json_lines(*argv):
    try:
        result = subprocess.run(
            argv, check=False, capture_output=True, text=True, timeout=8
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout if result.returncode == 0 else None


def git_toplevel(folder):
    out = run_json_lines("git", "-C", folder, "rev-parse", "--show-toplevel")
    return (out or "").strip()


def process_links(roots, agents):
    """roots: shell pid -> terminal address; agents: agent pid -> terminal address."""
    out = run_json_lines("ss", "-ltnpH") or ""
    links = []
    seen = set()
    for line in out.splitlines():
        cols = line.split()
        if len(cols) < 6:
            continue
        host, _, port = cols[3].rpartition(":")
        if host not in OPENABLE or not port.isdigit() or int(port) >= 32768:
            continue
        for name, pid in _SS_USER.findall(" ".join(cols[5:])):
            pid = int(pid)
            if (pid, port) in seen or name in AGENT_PROGRAMS:
                continue
            seen.add((pid, port))
            terminal, below, current, chain = None, None, pid, 0
            while current > 1 and chain < 64:
                stat = proc_stat(current)
                if not stat:
                    break
                # Any coding agent, also one outside herdr-core: the process right
                # below it decides, and only a shell is user work.
                if current in agents or stat[0] in AGENT_PROGRAMS:
                    shell = (
                        below is not None and (proc_stat(below) or ("",))[0] in SHELLS
                    )
                    terminal = agents.get(current) if shell else False
                    break
                if current in roots:
                    terminal = roots[current]
                    break
                below, current, chain = current, stat[1], chain + 1
            if terminal is False:
                continue  # an agent's MCP server or helper
            try:
                cwd = os.readlink(f"/proc/{pid}/cwd")
            except OSError:
                cwd = None
            git_root = git_toplevel(cwd) if cwd else ""
            links.append(
                {
                    "kind": "process",
                    "port": int(port),
                    "loopback": host in {"127.0.0.1", "::1", "[::1]"},
                    "label": name,
                    "terminal": terminal,
                    "cwd": cwd,
                    # The project it serves: a pane must work inside it to claim it.
                    "root": git_root or cwd,
                }
            )
    return links


def docker_links():
    out = run_json_lines("docker", "ps", "--format", "{{json .}}")
    links = []
    for line in (out or "").splitlines():
        try:
            box = json.loads(line)
        except ValueError:
            continue
        labels = dict(
            part.split("=", 1)
            for part in box.get("Labels", "").split(",")
            if "=" in part
        )
        if "com.ddev.platform" in labels:
            continue
        # Host port -> bound to loopback only; IPv4 and IPv6 binds of one port are one link.
        ports = {}
        for spec in box.get("Ports", "").split(","):
            match = _DOCKER_PORT.match(spec.strip())
            if match and match.group(1) in OPENABLE:
                port = int(match.group(2))
                loopback = match.group(1) in {"127.0.0.1", "::1", "[::1]"}
                ports[port] = ports.get(port, True) and loopback
        for port, loopback in sorted(ports.items()):
            links.append(
                {
                    "kind": "docker",
                    "port": port,
                    "loopback": loopback,
                    "label": labels.get("com.docker.compose.service")
                    or box.get("Names", ""),
                    "cwd": labels.get("com.docker.compose.project.working_dir"),
                }
            )
    return links


def ddev_links():
    out = run_json_lines("ddev", "list", "-j")
    try:
        projects = json.loads(out or "{}").get("raw") or []
    except ValueError:
        return []
    return [
        {
            "kind": "ddev",
            "url": p.get("primary_url"),
            "label": p.get("name"),
            "cwd": p.get("approot"),
        }
        for p in projects
        if isinstance(p, dict) and p.get("status") == "running" and p.get("primary_url")
    ]


def is_wsl():
    try:
        with open("/proc/sys/kernel/osrelease") as handle:
            release = handle.read().lower()
    except OSError:
        return False
    return "microsoft" in release or "wsl" in release


def collect_ports():
    binary = hc_binary()
    roots, agents = {}, {}
    for terminal in hc(binary, "ls").get("terminals", []):
        address = terminal.get("address")
        if not address:
            continue
        try:
            info = hc(binary, "get", address)
        except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired):
            continue
        if isinstance(info.get("pid"), int):
            roots[info["pid"]] = address
        foreground = field(info, "foreground", "pid")
        if terminal.get("agent") and isinstance(foreground, int):
            agents[foreground] = address
    return process_links(roots, agents) + docker_links() + ddev_links()


def main():
    # os.kill(pid, 0) terminates the process on Windows instead of probing it.
    if os.name != "posix":
        print(json.dumps({"terminals": {}, "error": "unsupported platform"}))
        return
    try:
        if sys.argv[1:] == ["ports"]:
            result = {"links": collect_ports(), "wsl": is_wsl(), "error": None}
        else:
            result = {"terminals": collect(), "error": None}
        print(json.dumps(result, ensure_ascii=False))
    except Exception as exc:  # noqa: BLE001 - the mod shows the reason
        print(
            json.dumps(
                {"terminals": {}, "links": [], "error": f"{type(exc).__name__}: {exc}"}
            )
        )


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
