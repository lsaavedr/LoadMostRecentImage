// `web/node/LoadMostRecentImage.js` imports `../../../scripts/app.js`, which
// ComfyUI provides at runtime and which does not exist in this repo. These
// synchronous module hooks stand in for it so the registration file can be
// exercised. Requires Node >= 22.15 (module.registerHooks).

export const APP_SPECIFIER = "scripts/app.js";
const STUB_URL = "stub:comfy-app";

export function resolve(specifier, context, nextResolve) {
  if (specifier.endsWith(APP_SPECIFIER)) {
    return { url: STUB_URL, format: "module", shortCircuit: true };
  }
  return nextResolve(specifier, context);
}

export function load(url, context, nextLoad) {
  if (url === STUB_URL) {
    return {
      format: "module",
      shortCircuit: true,
      source: `export const app = globalThis.__lmriStubApp;`,
    };
  }
  return nextLoad(url, context);
}
