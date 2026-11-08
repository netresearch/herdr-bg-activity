// Loaded with `node --import ./tests/js/register.mjs`: installs the resolve hook from hooks.mjs.
// registerHooks (Node 22.15+) runs in-thread; module.register() is deprecated from Node 26 on.
import { registerHooks } from "node:module";

import { resolve } from "./hooks.mjs";

registerHooks({ resolve });
