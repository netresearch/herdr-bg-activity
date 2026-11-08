// Background activity per agent, after netresearch/herdr-bg-activity: monitors and
// background shells an agent still owns while it waits at the prompt, plus Claude
// Code session details (model, effort, context use, subagents, Remote Control).
// collect.py does the work, once per machine; the result goes to the shared key
// SHARED_KEY, which spaces-bg reads as well.

import { div } from "gpui-kit";
import { h_flex } from "gpui-base";
// herdr's exec takes the program and an argv array; no shell is involved.
import { agents, appHome, exec as execFile, panes, readTextFile, settings, shared, setShared, spaces, window } from "herdr";

export const SHARED_KEY = "bg-activity.info";
const POLL_MS = 2500;
const EFFORT = { low: "▁", medium: "▃", high: "▅", xhigh: "▇", max: "█" };
// Claude Code's /effort picker colors (dark theme; max: Claude's accent), and the
// same hues darkened for contrast on a light sidebar.
const EFFORT_COLOR = {
  dark: { low: "#ffc107", medium: "#4eba65", high: "#b1b9f9", xhigh: "#af87ff", max: "#d77757" },
  light: { low: "#9a6700", medium: "#2f7d3f", high: "#4c58c9", xhigh: "#7a45d6", max: "#b2502f" },
};
const CTX_WARN = 70;
const CTX_CRIT = 90;

// "wsl/t2" -> "wsl"; an agent on this computer has no prefix.
const machineOf = (address) => (address.includes("/") ? address.slice(0, address.lastIndexOf("/")) : null);

export const infoOf = (address) => shared(SHARED_KEY)?.[address] ?? null;

// Starts polling for one mod copy. State lives on `view`; no cx is kept.
export function startPolling(view, cx) {
  view.bgBusy = false;
  cx.spawn(async (cx) => {
    view.bgScript = await readTextFile(`${appHome()}/mods/agents-bg/collect.py`);
    poll(view, cx);
  });
  cx.timer.every(POLL_MS, (cx) => poll(view, cx));
  view.portsBusy = false;
  cx.timer.every(PORTS_MS, (cx) => pollPorts(view, cx));
}

// --- links to the services sessions started ---------------------------------------
// collect.py's ports mode lists listeners, Docker containers and DDEV projects per
// machine; here each one is placed on an agent and a space and published to LINKS_KEY
// as { byAgent: { address: [link] }, bySpace: { spaceId: [link] } },
// link = { key, text, url, title }.

export const LINKS_KEY = "bg-activity.links";
const PORTS_MS = 8000;
const isHome = (f) => /^(\/home\/[^/]+|\/Users\/[^/]+|\/root|\/)\/?$/.test(f ?? "/");
const within = (path, folder) => path === folder || path.startsWith(`${folder.replace(/\/+$/, "")}/`);

function pollPorts(view, cx) {
  if (view.portsBusy || !view.bgScript) return;
  const windows = window()?.platform === "windows";
  const machines = [...new Set(spaces().map((s) => s.machine ?? null))].filter((m) => m !== null || !windows);
  view.portsBusy = true;
  cx.spawn(async () => {
    const found = [];
    for (const machine of machines) {
      try {
        const r = await execFile("python3", ["-c", view.bgScript, "ports"], { on: machine });
        const out = JSON.parse(r.stdout || "{}");
        if (out.error) console.log(`bg-activity ports ${machine ?? "local"}: ${out.error}`);
        // A WSL machine's ports reach this Windows computer as localhost.
        const host = machine === null || (out.wsl && windows) ? "localhost" : machine;
        for (const l of out.links ?? []) found.push({ ...l, machine, host });
      } catch (e) {
        console.log(`bg-activity ports ${machine ?? "local"}: ${e?.message ?? e}`);
      }
    }
    view.portsBusy = false;
    const next = place(found);
    if (JSON.stringify(next) !== JSON.stringify(shared(LINKS_KEY) ?? {})) setShared(LINKS_KEY, next);
  });
}

function place(found) {
  const ps = panes().filter((p) => p.terminal);
  const tabSpace = new Map(spaces().flatMap((s) => s.tabs.map((t) => [t.id, s.id])));
  const agentSet = new Set(agents().map((a) => a.address));
  const byAgent = {};
  const bySpace = {};
  const add = (map, k, link) => {
    const list = (map[k] ??= []);
    if (!list.some((x) => x.key === link.key)) list.push(link);
  };
  for (const l of found) {
    const url = l.url ?? (l.host === "localhost" || !l.loopback ? `http://${l.host}:${l.port}` : null);
    if (!url) continue; // bound to another machine's loopback: nothing this computer can open
    const prefix = l.machine ? `${l.machine}/` : "";
    // The terminal it descends from, else a pane working inside its project (git root,
    // compose folder, DDEV root). A pane in a folder above the project, such as
    // ~/projects, does not claim it: that would hand every service to it.
    let pane = l.terminal ? ps.find((p) => p.terminal === prefix + l.terminal) : null;
    const root = l.root ?? l.cwd;
    if (!pane && root && !isHome(root)) {
      // Same machine: a remote pane's terminal carries the machine prefix, a local one none.
      const sameMachine = (p) => (prefix ? p.terminal.startsWith(prefix) : !p.terminal.includes("/"));
      const inside = ps.filter((p) => sameMachine(p) && p.cwd && within(p.cwd, root));
      // An agent first, then the pane closest to where the service runs.
      const score = (p) => (agentSet.has(p.terminal) ? 1e6 : 0) - (l.cwd && within(l.cwd, p.cwd) ? 0 : 1e3) + p.cwd.length;
      pane = inside.sort((a, b) => score(b) - score(a))[0];
    }
    if (!pane) continue;
    const link = {
      key: `${l.kind}:${l.port ?? l.url}`,
      text: l.kind === "ddev" ? `${l.label} ↗` : `:${l.port}`,
      url,
      title: `${l.kind === "process" ? l.label : l.kind === "docker" ? `docker: ${l.label}` : `ddev: ${l.label}`}\n${url}`,
    };
    if (agentSet.has(pane.terminal)) add(byAgent, pane.terminal, link);
    const space = tabSpace.get(pane.tab);
    if (space) add(bySpace, space, link);
  }
  for (const list of [...Object.values(byAgent), ...Object.values(bySpace)]) list.sort((a, b) => a.key.localeCompare(b.key, undefined, { numeric: true }));
  return { byAgent, bySpace };
}

// Clickable chips for a list of links; a click opens the browser on this computer.
export function linkChips(t, list, id) {
  return (list ?? []).map((l) =>
    div().id(`link-${id}-${l.key}`).flex_none().text_color(t.accent).cursor_pointer()
      .hover((s) => s.text_color(t.foreground).underline())
      .tooltip(`${l.title}\nclick: open in browser`)
      .on_click((_e, cx) => { cx.stop_propagation(); cx.open_url(l.url); })
      .child(l.text));
}

export const agentLinks = (address) => shared(LINKS_KEY)?.byAgent?.[address] ?? [];

function poll(view, cx) {
  if (view.bgBusy || !view.bgScript) return;
  // collect.py needs a POSIX machine; agents on this Windows computer are skipped.
  const skipLocal = window()?.platform === "windows";
  const machines = [...new Set(agents().map((a) => machineOf(a.address)))].filter((m) => m !== null || !skipLocal);
  view.bgBusy = true;
  cx.spawn(async () => {
    const info = {};
    for (const machine of machines) {
      try {
        const r = await execFile("python3", ["-c", view.bgScript], { on: machine });
        const out = JSON.parse(r.stdout || "{}");
        if (out.error) console.log(`bg-activity ${machine ?? "local"}: ${out.error}`);
        for (const [addr, v] of Object.entries(out.terminals ?? {})) info[machine ? `${machine}/${addr}` : addr] = v;
      } catch (e) {
        console.log(`bg-activity ${machine ?? "local"}: ${e?.message ?? e}`);
      }
    }
    view.bgBusy = false;
    // Setting shared state redraws every mod, so only on a change.
    if (JSON.stringify(info) !== JSON.stringify(shared(SHARED_KEY) ?? {})) setShared(SHARED_KEY, info);
  });
}

// The line under an agent row: "O55 ▃ ↳1 26% ⇄ ⧗ 1 monitor". Null when there's nothing.
export function detailLine(t, a, indent) {
  const d = infoOf(a.address) ?? {};
  const parts = [];
  const tok = (key, text, color) => parts.push(div().id(`${key}-${a.address}`).flex_none().text_color(color).child(text));
  if (d.model) tok("model", d.model, t.muted);
  if (d.effort && EFFORT[d.effort]) tok("effort", EFFORT[d.effort], EFFORT_COLOR[settings()?.dark ? "dark" : "light"][d.effort]);
  if (d.agents) tok("subs", `↳${d.agents}`, t.muted);
  if (typeof d.ctx === "number") tok("ctx", `${d.ctx}%`, d.ctx >= CTX_CRIT ? t.ansi1 : d.ctx >= CTX_WARN ? t.ansi3 : t.muted);
  if (d.rc) tok("rc", "⇄", t.ansi2);
  if (d.bg) parts.push(div().id(`bg-${a.address}`).min_w(0).truncate().text_color(t.ansi3).child(d.bg));
  parts.push(...linkChips(t, agentLinks(a.address), a.address));
  if (!parts.length) return null;
  // Wraps when the links don't fit on one line.
  return h_flex().id(`detail-${a.address}`).pl(indent).pr(8).mt(-6).pb(2).min_h(20).flex_none().flex_wrap().gap_x(6).gap_y(1).items_center().text_size(11.5).children(parts);
}
