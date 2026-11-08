// Stand-ins for gpui-kit / gpui-base: every builder call returns the element itself and
// is recorded, so a test can read what a mod rendered (ids, text, click handlers).
// The record lives under `$calls` and `$kids`, names no builder method uses.

// One recording element of the given kind; `when(cond, fn)` runs fn only if cond holds.
function element(kind) {
  const el = { $kind: kind, $calls: [], $kids: [] };
  const proxy = new Proxy(el, {
    get(target, prop) {
      if (Object.hasOwn(target, prop)) return target[prop];
      return (...args) => {
        target.$calls.push([prop, ...args]);
        if (prop === "child") target.$kids.push(args[0]);
        if (prop === "children") target.$kids.push(...args[0]);
        if (prop === "when" && args[0]) args[1](proxy);
        return proxy;
      };
    },
  });
  return proxy;
}

export const div = () => element("div");
export const h_flex = () => element("h_flex");
export const v_flex = () => element("v_flex");
export const svg = () => element("svg");
export const image = () => element("image");
// The base class mods extend; tests call their methods directly, nothing renders.
export class View {
  render() {
    return null;
  }
}

// The first argument of the last call to `method` on an element, or undefined.
export function arg(el, method) {
  return el.$calls.findLast((c) => c[0] === method)?.[1];
}
