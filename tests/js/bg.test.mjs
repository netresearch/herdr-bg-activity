// Tests for herdr-app/mods/agents-bg/bg.js and spaces-bg/bg.js, the mod logic that
// places service links and spots agents waiting on background work. Run with
//   node --import ./tests/js/register.mjs --test tests/js/

import assert from "node:assert/strict";
import { beforeEach, describe, test } from "node:test";

import { arg } from "./stubs/gpui.mjs";
import { reset, state } from "./stubs/herdr.mjs";
import {
  LINKS_KEY,
  SHARED_KEY,
  collectOn,
  detailLine,
  isHome,
  keepLast,
  paneOf,
  place,
  startPolling,
  urlOf,
  waitsOnBackground,
  within,
} from "../../herdr-app/mods/agents-bg/bg.js";
import { bgCount, spaceTail } from "../../herdr-app/mods/spaces-bg/bg.js";

const ok = (out) => ({ code: 0, stdout: JSON.stringify(out), stderr: "" });

// A cx whose spawned tasks can be awaited and whose timers run on demand.
function fakeCx() {
  const tasks = [];
  const timers = [];
  const cx = {
    spawn: (fn) => tasks.push(fn(cx)),
    timer: { every: (_ms, fn) => timers.push(fn) },
    async settle() {
      while (tasks.length) await tasks.shift();
    },
    async tick() {
      for (const fn of timers) fn(cx);
      await cx.settle();
    },
  };
  return cx;
}

beforeEach(() => {
  reset();
  console.log = () => {}; // collectOn logs every failure; keep test output clean
});

describe("collectOn", () => {
  test("passes a successful result through", async () => {
    state.runProgram = async () => ok({ terminals: { t2: {} }, error: null });
    assert.deepEqual(await collectOn("x", "wsl", []), { terminals: { t2: {} }, error: null });
  });

  test("treats an error collect.py reports itself as a failed round", async () => {
    state.runProgram = async () => ok({ terminals: {}, error: "RuntimeError: hc ls: timeout" });
    assert.equal(await collectOn("x", "wsl", []), null);
  });

  test("treats a non-zero exit and an unreachable machine as failed rounds", async () => {
    state.runProgram = async () => ({ code: 1, stdout: "", stderr: "boom" });
    assert.equal(await collectOn("x", "wsl", []), null);
    state.runProgram = async () => {
      throw new Error("unreachable");
    };
    assert.equal(await collectOn("x", "wsl", []), null);
  });
});

describe("keepLast", () => {
  test("keeps a failing machine's result for two rounds, then drops it", () => {
    const failures = new Map();
    assert.deepEqual(
      [keepLast(failures, "wsl", true), keepLast(failures, "wsl", true), keepLast(failures, "wsl", true)],
      [true, true, false],
    );
  });

  test("a success resets the count", () => {
    const failures = new Map();
    keepLast(failures, "wsl", true);
    keepLast(failures, "wsl", true);
    keepLast(failures, "wsl", false);
    assert.equal(keepLast(failures, "wsl", true), true);
  });
});

describe("folders", () => {
  test("isHome", () => {
    for (const f of ["/", "/root", "/root/", "/home/cybot", "/home/cybot/", "/Users/me", undefined]) assert.equal(isHome(f), true, f);
    for (const f of ["/home/cybot/projects", "/srv", "/home", "/Users/me/x", "/tmp/x"]) assert.equal(isHome(f), false, f);
  });

  test("within", () => {
    const cases = [
      ["/p/app", "/p/app", true],
      ["/p/app/x", "/p/app", true],
      ["/p/app/x", "/p/app/", true],
      ["/p/app", "/p/app/", true],
      ["/p/apple", "/p/app", false],
      ["/p", "/p/app", false],
      ["/x", "/", true],
    ];
    for (const [path, folder, want] of cases) assert.equal(within(path, folder), want, `${path} in ${folder}`);
  });
});

describe("urlOf", () => {
  test("a port opens on localhost, a DDEV project at its URL", () => {
    assert.equal(urlOf({ port: 5173 }), "http://localhost:5173");
    assert.equal(urlOf({ url: "https://shop.ddev.site" }), "https://shop.ddev.site");
  });

  test("only http(s) URLs become links", () => {
    assert.equal(urlOf({ url: "file:///etc/passwd" }), null);
    assert.equal(urlOf({ url: "javascript:alert(1)" }), null);
  });
});

describe("paneOf", () => {
  const ps = [
    { terminal: "wsl/t2", cwd: "/home/u/projects", tab: "tb1" },
    { terminal: "wsl/t3", cwd: "/home/u/projects/app", tab: "tb2" },
    { terminal: "wsl/t4", cwd: "/home/u/projects/app/web", tab: "tb2" },
    { terminal: "t9", cwd: "/home/u/projects/app", tab: "tb3" },
  ];
  const agentsAt = new Set(["wsl/t2", "wsl/t3"]);

  test("the terminal a process descends from wins", () => {
    assert.equal(paneOf({ machine: "wsl", terminal: "t4", root: "/x" }, ps, agentsAt), ps[2]);
  });

  test("a pane in a folder above the project does not claim it", () => {
    const pane = paneOf({ machine: "wsl", root: "/home/u/projects/other", cwd: "/home/u/projects/other" }, ps, agentsAt);
    assert.equal(pane, null);
  });

  test("inside the project, an agent's pane is preferred", () => {
    const pane = paneOf({ machine: "wsl", root: "/home/u/projects/app", cwd: "/home/u/projects/app/web" }, ps, agentsAt);
    assert.equal(pane, ps[1]);
  });

  test("a terminal without a pane falls back to the project folder", () => {
    const pane = paneOf({ machine: "wsl", terminal: "t77", root: "/home/u/projects/app" }, ps, agentsAt);
    assert.equal(pane, ps[1]);
  });

  test("panes on another machine and the home folder never claim a service", () => {
    assert.equal(paneOf({ machine: null, root: "/home/u/projects/app" }, ps.slice(0, 3), agentsAt), null);
    assert.equal(paneOf({ machine: "wsl", root: "/home/u" }, ps, agentsAt), null);
  });
});

describe("place", () => {
  test("links land on the agent and its space, once each, sorted by port", () => {
    state.agents = [{ address: "wsl/t3" }];
    state.panes = [{ terminal: "wsl/t3", cwd: "/p/app", tab: "tb1" }];
    state.spaces = [{ id: "sp1", tabs: [{ id: "tb1" }] }];
    const found = [
      { kind: "process", machine: "wsl", terminal: "t3", port: 8080, label: "go" },
      { kind: "docker", machine: "wsl", root: "/p/app", port: 5432, label: "db" },
      { kind: "process", machine: "wsl", terminal: "t3", port: 8080, label: "go" },
    ];
    const out = place(found);
    assert.deepEqual(out.byAgent["wsl/t3"].map((l) => l.text), [":5432", ":8080"]);
    assert.deepEqual(out.bySpace.sp1.map((l) => l.url), ["http://localhost:5432", "http://localhost:8080"]);
    assert.equal(out.bySpace.sp1[0].title, "docker: db\nhttp://localhost:5432");
  });
});

describe("waitsOnBackground", () => {
  test("only an agent at the prompt that still owns background work", () => {
    state.shared[SHARED_KEY] = { "wsl/t2": { bg: "⧗ 1 shell" }, "wsl/t3": {} };
    assert.equal(waitsOnBackground({ address: "wsl/t2", status: "idle" }), true);
    assert.equal(waitsOnBackground({ address: "wsl/t2", status: "done" }), true);
    assert.equal(waitsOnBackground({ address: "wsl/t2", status: "working" }), false);
    assert.equal(waitsOnBackground({ address: "wsl/t3", status: "done" }), false);
  });
});

describe("polling", () => {
  function setUp(platform) {
    state.platform = platform;
    state.agents = [{ address: "wsl/t3" }, { address: "vps/t1" }];
    state.spaces = [
      { id: "s1", machine: "wsl", tabs: [{ id: "tb1" }] },
      { id: "s2", machine: "vps", tabs: [{ id: "tb2" }] },
    ];
    state.panes = [
      { terminal: "wsl/t3", cwd: "/p/app", tab: "tb1" },
      { terminal: "vps/t1", cwd: "/srv/app", tab: "tb2" },
    ];
  }

  test("links only for a WSL machine behind a Windows app, not for another remote", async () => {
    setUp("windows");
    state.runProgram = async (_p, args, { on }) =>
      args.includes("ports")
        ? ok({ wsl: on === "wsl", error: null, links: [{ kind: "process", terminal: on === "wsl" ? "t3" : "t1", port: 3000, label: "node" }] })
        : ok({ terminals: {}, error: null });
    const cx = fakeCx();
    startPolling({}, cx);
    await cx.settle();
    const links = state.shared[LINKS_KEY];
    assert.deepEqual(Object.keys(links.byAgent), ["wsl/t3"]);
    assert.deepEqual(Object.keys(links.bySpace), ["s1"]);
  });

  test("a failing machine keeps its details for two rounds, then shows nothing", async () => {
    setUp("windows");
    let fail = false;
    state.runProgram = async (_p, args, { on }) => {
      if (fail && on === "wsl") return { code: 1, stdout: "", stderr: "down" };
      return args.includes("ports") ? ok({ wsl: true, links: [] }) : ok({ terminals: { [on === "wsl" ? "t3" : "t1"]: { bg: "⧗ 1 shell" } } });
    };
    const view = {};
    const cx = fakeCx();
    startPolling(view, cx);
    await cx.settle();
    assert.ok(state.shared[SHARED_KEY]["wsl/t3"]);
    fail = true;
    await cx.tick();
    await cx.tick();
    assert.ok(state.shared[SHARED_KEY]["wsl/t3"], "kept for two failed rounds");
    await cx.tick();
    assert.equal(state.shared[SHARED_KEY]["wsl/t3"], undefined, "dropped after the third");
    assert.ok(state.shared[SHARED_KEY]["vps/t1"], "the other machine is unaffected");
  });

  test("agents on this Windows computer are not polled", async () => {
    setUp("windows");
    state.agents = [{ address: "t1" }];
    state.spaces = [{ id: "s0", machine: null, tabs: [] }];
    const machines = [];
    state.runProgram = async (_p, _a, { on }) => {
      machines.push(on);
      return ok({});
    };
    const cx = fakeCx();
    startPolling({}, cx);
    await cx.settle();
    assert.deepEqual(machines, []);
  });
});

describe("rendering", () => {
  test("the detail line carries no negative top margin (it hides the list's scrollbar)", () => {
    state.shared[SHARED_KEY] = { "wsl/t3": { model: "O55", ctx: 40 } };
    const line = detailLine({ muted: "m", ansi1: "r", ansi2: "g", ansi3: "y", accent: "a" }, { address: "wsl/t3" }, 33);
    assert.equal(arg(line, "mt"), undefined);
  });

  test("the space tail counts background tasks of its agents", () => {
    assert.equal(bgCount("⧗ 1 monitor, 2 shells"), 3);
    assert.equal(bgCount(undefined), 0);
    state.agents = [{ address: "wsl/t3", space: "s1", app: "claude-code" }];
    state.shared[SHARED_KEY] = { "wsl/t3": { bg: "⧗ 2 shells" } };
    const tail = spaceTail({ dim: "d", ansi3: "y", accent: "a", foreground: "f" }, "s1");
    const texts = tail.$kids.flatMap((c) => c.$kids);
    assert.deepEqual(texts, ["✻", "⧗ 2"]);
  });
});
