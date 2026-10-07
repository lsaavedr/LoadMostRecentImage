import { test } from "node:test";
import assert from "node:assert/strict";
import { registerHooks } from "node:module";

import * as hooks from "./stubAppHooks.js";

// Covers web/node/LoadMostRecentImage.js, the ComfyUI entry file. It has no
// exports -- importing it is the whole assertion: it must resolve the
// ComfyUI-provided `scripts/app.js` and register the extension.
test("entry file registers the extension with ComfyUI's app", async () => {
  const registered = [];
  globalThis.__lmriStubApp = {
    registerExtension: (ext) => registered.push(ext),
  };
  registerHooks(hooks);

  await import("../web/node/LoadMostRecentImage.js");

  assert.equal(registered.length, 1);
  assert.equal(registered[0].name, "LoadMostRecentImage.WidgetUpdate");
  for (const hook of ["nodeCreated", "afterConfigureGraph"]) {
    assert.equal(typeof registered[0][hook], "function");
  }

  delete globalThis.__lmriStubApp;
});
