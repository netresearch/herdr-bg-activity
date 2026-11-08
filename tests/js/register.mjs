// Loaded with `node --import ./tests/js/register.mjs`: installs hooks.mjs.
import { register } from "node:module";

register("./hooks.mjs", import.meta.url);
