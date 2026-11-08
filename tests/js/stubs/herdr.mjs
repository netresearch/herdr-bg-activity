// A stand-in for the Herdr app's `herdr` module. Tests set `state` and read `shared`.

export const state = {
  agents: [],
  panes: [],
  spaces: [],
  shared: {},
  platform: "windows",
  // (program, args, options) -> ExecResult, or throws like an unreachable machine.
  runProgram: async () => ({ code: 0, stdout: "{}", stderr: "" }),
};

// Puts `state` back to an empty app on Windows whose runner returns `{}`; call before each test.
export function reset() {
  Object.assign(state, { agents: [], panes: [], spaces: [], shared: {}, platform: "windows" });
  state.runProgram = async () => ({ code: 0, stdout: "{}", stderr: "" });
}

export const agents = () => state.agents;
export const panes = () => state.panes;
export const spaces = () => state.spaces;
export const shared = (key) => state.shared[key];
export const setShared = (key, value) => {
  state.shared[key] = value;
};
export const settings = () => ({ dark: true });
export const window = () => ({ platform: state.platform });
export const appHome = () => "/app";
export const readTextFile = async () => "# collect.py";
export const run = () => null;

// herdr's program runner: takes the program and an argv array, no shell.
const runStub = (...args) => state.runProgram(...args);
export { runStub as exec };
