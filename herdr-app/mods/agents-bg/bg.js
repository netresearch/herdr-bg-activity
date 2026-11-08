// Background activity per agent, after netresearch/herdr-bg-activity: monitors and
// background shells an agent still owns while it waits at the prompt, plus Claude
// Code session details (model, effort, context use, subagents, Remote Control), and
// links to the services the sessions started. collect.py does the work, once per
// machine; the results go to the shared keys SHARED_KEY and LINKS_KEY, which
// spaces-bg reads as well.

import { div } from "gpui-kit";
import { h_flex } from "gpui-base";
// herdr's exec takes the program and an argv array; no shell is involved.
import { agents, appHome, exec as execFile, panes, readTextFile, settings, shared, setShared, spaces, window } from "herdr";

export const SHARED_KEY = "bg-activity.info";
export const LINKS_KEY = "bg-activity.links";
const POLL_MS = 2500;
const PORTS_MS = 8000;
const EFFORT = { low: "▁", medium: "▃", high: "▅", xhigh: "▇", max: "█" };
// Claude Code's /effort picker colors (dark theme; max: Claude's accent), and the
// same hues darkened for contrast on a light sidebar.
const EFFORT_COLOR = {
  dark: { low: "#ffc107", medium: "#4eba65", high: "#b1b9f9", xhigh: "#af87ff", max: "#d77757" },
  light: { low: "#9a6700", medium: "#2f7d3f", high: "#4c58c9", xhigh: "#7a45d6", max: "#b2502f" },
};
const CTX_WARN = 70;
const CTX_CRIT = 90;
const KIND_PREFIX = { process: "", docker: "docker: ", ddev: "ddev: " };

// "wsl/t2" -> "wsl"; an agent on this computer has no prefix.
const machineOf = (address) => (address.includes("/") ? address.slice(0, address.lastIndexOf("/")) : null);
const onWindows = () => window()?.platform === "windows";
// collect.py needs a POSIX machine: on a Windows app, this computer is skipped.
const usable = (machines) => [...new Set(machines)].filter((m) => m !== null || !onWindows());

export const infoOf = (address) => shared(SHARED_KEY)?.[address] ?? null;
export const agentLinks = (address) => shared(LINKS_KEY)?.byAgent?.[address] ?? [];

// Setting shared state redraws every mod, so only on a change.
function publish(key, value) {
  if (JSON.stringify(value) !== JSON.stringify(shared(key) ?? {})) setShared(key, value);
}

// collect.py's JSON from one machine, or null when it can't run there.
async function collectOn(script, machine, args) {
  try {
    const r = await execFile("python3", ["-c", script, ...args], { on: machine });
    const out = JSON.parse(r.stdout || "{}");
    if (out.error) console.log(`bg-activity ${machine ?? "local"}: ${out.error}`);
    return out;
  } catch (e) {
    console.log(`bg-activity ${machine ?? "local"}: ${e?.message ?? e}`);
    return null;
  }
}

// Starts polling for one mod copy. State lives on `view`; no cx is kept.
export function startPolling(view, cx) {
  view.bgBusy = false;
  view.portsBusy = false;
  cx.spawn(async (cx) => {
    view.bgScript = await readTextFile(`${appHome()}/mods/agents-bg/collect.py`);
    poll(view, cx);
    pollPorts(view, cx);
  });
  cx.timer.every(POLL_MS, (cx) => poll(view, cx));
  cx.timer.every(PORTS_MS, (cx) => pollPorts(view, cx));
}

function poll(view, cx) {
  if (view.bgBusy || !view.bgScript) return;
  const machines = usable(agents().map((a) => machineOf(a.address)));
  view.bgBusy = true;
  cx.spawn(async () => {
    const results = await Promise.all(machines.map((m) => collectOn(view.bgScript, m, [])));
    const info = {};
    machines.forEach((machine, i) => {
      for (const [addr, v] of Object.entries(results[i]?.terminals ?? {})) info[machine ? `${machine}/${addr}` : addr] = v;
    });
    view.bgBusy = false;
    publish(SHARED_KEY, info);
  });
}

// --- links to the services sessions started ---------------------------------------
// collect.py's ports mode lists listeners, Docker containers and DDEV projects per
// machine; each one is placed on an agent and a space and published to LINKS_KEY as
// { byAgent: { address: [link] }, bySpace: { spaceId: [link] } },
// link = { key, text, url, title }.

const HOME = /^\/(?:home\/[^/]+|Users\/[^/]+|root)?\/?$/;
const isHome = (folder) => HOME.test(folder ?? "/");
const within = (path, folder) => path === folder || path.startsWith(`${folder.replace(/\/+$/, "")}/`);

function pollPorts(view, cx) {
  if (view.portsBusy || !view.bgScript) return;
  const machines = usable(spaces().map((s) => s.machine ?? null));
  view.portsBusy = true;
  cx.spawn(async () => {
    const results = await Promise.all(machines.map((m) => collectOn(view.bgScript, m, ["ports"])));
    const found = [];
    machines.forEach((machine, i) => {
      // A WSL machine's ports reach this Windows computer as localhost.
      const host = machine === null || (results[i]?.wsl && onWindows()) ? "localhost" : machine;
      for (const l of results[i]?.links ?? []) found.push({ ...l, machine, host });
    });
    view.portsBusy = false;
    publish(LINKS_KEY, place(found));
  });
}

// What this computer opens for a service, or null for another machine's loopback.
function urlOf(l) {
  if (l.url) return l.url;
  return l.host === "localhost" || !l.loopback ? `http://${l.host}:${l.port}` : null;
}

// The pane a service belongs to: the terminal it descends from, else a pane working
// inside its project (git root, compose folder, DDEV root). A pane in a folder above
// the project, such as ~/projects, does not claim it: that would hand it every service.
function paneOf(l, ps, agentSet) {
  const prefix = l.machine ? `${l.machine}/` : "";
  if (l.terminal) return ps.find((p) => p.terminal === prefix + l.terminal) ?? null;
  const root = l.root ?? l.cwd;
  if (!root || isHome(root)) return null;
  // Same machine: a remote pane's terminal carries the machine prefix, a local one none.
  const sameMachine = (p) => (prefix ? p.terminal.startsWith(prefix) : !p.terminal.includes("/"));
  // An agent first, then a pane in the service's own folder, then the deepest one.
  const score = (p) => (agentSet.has(p.terminal) ? 1e6 : 0) + (l.cwd && within(l.cwd, p.cwd) ? 1e3 : 0) + p.cwd.length;
  const inside = ps.filter((p) => sameMachine(p) && p.cwd && within(p.cwd, root));
  return inside.sort((a, b) => score(b) - score(a))[0] ?? null;
}

function linkOf(l, url) {
  return {
    key: `${l.kind}:${l.port ?? l.url}`,
    text: l.kind === "ddev" ? `${l.label} ↗` : `:${l.port}`,
    url,
    title: `${KIND_PREFIX[l.kind] ?? ""}${l.label}\n${url}`,
  };
}

function place(found) {
  const ps = panes().filter((p) => p.terminal);
  const tabSpace = new Map(spaces().flatMap((s) => s.tabs.map((t) => [t.id, s.id])));
  const agentSet = new Set(agents().map((a) => a.address));
  const byAgent = {};
  const bySpace = {};
  const add = (map, k, link) => {
    map[k] ??= [];
    if (!map[k].some((x) => x.key === link.key)) map[k].push(link);
  };
  for (const l of found) {
    const url = urlOf(l);
    const pane = url ? paneOf(l, ps, agentSet) : null;
    if (!pane) continue;
    const link = linkOf(l, url);
    if (agentSet.has(pane.terminal)) add(byAgent, pane.terminal, link);
    const space = tabSpace.get(pane.tab);
    if (space) add(bySpace, space, link);
  }
  const byKey = (a, b) => a.key.localeCompare(b.key, undefined, { numeric: true });
  for (const list of [...Object.values(byAgent), ...Object.values(bySpace)]) list.sort(byKey);
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

function ctxColor(t, percent) {
  if (percent >= CTX_CRIT) return t.ansi1;
  if (percent >= CTX_WARN) return t.ansi3;
  return t.muted;
}

// The line under an agent row: "O55 ▃ ↳1 26% ⇄ ⧗ 1 monitor :5175". Null when empty.
export function detailLine(t, a, indent) {
  const d = infoOf(a.address) ?? {};
  const parts = [];
  const tok = (key, text, color) => parts.push(div().id(`${key}-${a.address}`).flex_none().text_color(color).child(text));
  if (d.model) tok("model", d.model, t.muted);
  if (EFFORT[d.effort]) tok("effort", EFFORT[d.effort], EFFORT_COLOR[settings()?.dark ? "dark" : "light"][d.effort]);
  if (d.agents) tok("subs", `↳${d.agents}`, t.muted);
  if (typeof d.ctx === "number") tok("ctx", `${d.ctx}%`, ctxColor(t, d.ctx));
  if (d.rc) tok("rc", "⇄", t.ansi2);
  if (d.bg) parts.push(div().id(`bg-${a.address}`).min_w(0).truncate().text_color(t.ansi3).child(d.bg));
  parts.push(...linkChips(t, agentLinks(a.address), a.address));
  if (!parts.length) return null;
  // Wraps when the links don't fit on one line.
  return h_flex().id(`detail-${a.address}`).pl(indent).pr(8).mt(-6).pb(2).min_h(20).flex_none().flex_wrap().gap_x(6).gap_y(1).items_center().text_size(11.5).children(parts);
}
