// Node module hooks for the herdr-app mod tests: the app's own modules ("gpui-kit",
// "gpui-base", "herdr") exist only inside the Herdr app, so tests resolve them to the
// stubs next to this file.

const STUBS = {
  "gpui-kit": new URL("./stubs/gpui.mjs", import.meta.url).href,
  "gpui-base": new URL("./stubs/gpui.mjs", import.meta.url).href,
  herdr: new URL("./stubs/herdr.mjs", import.meta.url).href,
};

export async function resolve(specifier, context, nextResolve) {
  if (Object.hasOwn(STUBS, specifier)) return { url: STUBS[specifier], shortCircuit: true };
  return nextResolve(specifier, context);
}
