import { test } from "node:test";
import assert from "node:assert/strict";
import { createExtension } from "../web/node/LoadMostRecentImage.extension.js";

function fakeApp() {
  const calls = [];
  return {
    calls,
    graph: { _nodes: [] },
    queuePrompt: async (...args) => calls.push(["queuePrompt", ...args]),
    graphToPrompt: async () => calls.push(["graphToPrompt"]),
  };
}

function fakeNode({
  comfyClass = "LoadMostRecentImage",
  widgetValue = 0,
  directory = "",
} = {}) {
  const widget = { name: "iter", value: widgetValue, callback: null };
  const dirWidget = { name: "directory", value: directory, callback: null };
  const node = {
    comfyClass,
    id: 7,
    widgets: [dirWidget, widget],
    onExecuted: null,
    setDirtyCanvas(a, b) {
      this.dirtied = a && b;
    },
  };
  return { node, widget, dirWidget };
}

test("nodeCreated ignores nodes of other classes", async () => {
  const ext = createExtension(fakeApp());
  const { node } = fakeNode({ comfyClass: "Other" });
  await ext.nodeCreated(node);
  assert.equal(node.onExecuted, null);
});

test("nodeCreated defaults an unset iter widget to 0", async () => {
  const ext = createExtension(fakeApp());
  const { node, widget } = fakeNode({ widgetValue: undefined });
  await ext.nodeCreated(node);
  assert.equal(widget.value, 0);
});

test("nodeCreated preserves an existing iter value", async () => {
  const ext = createExtension(fakeApp());
  const { node, widget } = fakeNode({ widgetValue: 3 });
  await ext.nodeCreated(node);
  assert.equal(widget.value, 3);
});

test("onExecuted writes the iter response back into the widget", async () => {
  const ext = createExtension(fakeApp());
  const { node, widget } = fakeNode();
  await ext.nodeCreated(node);
  node.onExecuted({ iter: [2] });
  assert.equal(widget.value, 2);
  assert.equal(node.dirtied, true);
});

test("onExecuted ignores payloads without iter", async () => {
  const ext = createExtension(fakeApp());
  const { node, widget } = fakeNode({ widgetValue: 1 });
  await ext.nodeCreated(node);
  node.onExecuted({});
  assert.equal(widget.value, 1);
});

test("widget callback treats empty values as 0", async () => {
  const ext = createExtension(fakeApp());
  const { node, widget } = fakeNode();
  await ext.nodeCreated(node);
  widget.callback("");
  await new Promise((r) => setImmediate(r));
  assert.ok(true); // callback did not throw
});

test("afterConfigureGraph resets iter to 1 on every matching node", async () => {
  const app = fakeApp();
  const ext = createExtension(app);
  const { node: n1, widget: w1 } = fakeNode({ widgetValue: 5 });
  const { node: n2, widget: w2 } = fakeNode({ widgetValue: 9 });
  const { node: other, widget: wOther } = fakeNode({
    comfyClass: "Other",
    widgetValue: 4,
  });
  app.graph._nodes = [n1, n2, other];
  await ext.afterConfigureGraph();
  assert.equal(w1.value, 1);
  assert.equal(w2.value, 1);
  assert.equal(wOther.value, 4);
});

test("onExecuted ignores empty iter arrays", async () => {
  const ext = createExtension(fakeApp());
  const { node, widget } = fakeNode({ widgetValue: 1 });
  await ext.nodeCreated(node);
  node.onExecuted({ iter: [] });
  assert.equal(widget.value, 1);
});

test("onExecuted ignores non-array iter payloads", async () => {
  const ext = createExtension(fakeApp());
  const { node, widget } = fakeNode({ widgetValue: 1 });
  await ext.nodeCreated(node);
  node.onExecuted({ iter: 5 });
  assert.equal(widget.value, 1);
});

test("onExecuted does not fire the widget callback (it would recurse)", async () => {
  const ext = createExtension(fakeApp());
  const { node, widget } = fakeNode({ widgetValue: 0 });
  await ext.nodeCreated(node);
  const seen = [];
  widget.callback = (v) => seen.push(v);
  node.onExecuted({ iter: [3] });
  assert.deepEqual(seen, []);
});

test("afterConfigureGraph clears persisted history on the backend", async () => {
  const app = fakeApp();
  const ext = createExtension(app);
  const { node, widget } = fakeNode({ widgetValue: 3 });
  app.graph._nodes = [node];

  const calls = [];
  const realFetch = globalThis.fetch;
  globalThis.fetch = async (url, opts) => {
    calls.push([url, opts]);
    return { ok: true, status: 200 };
  };
  try {
    await ext.afterConfigureGraph();
  } finally {
    globalThis.fetch = realFetch;
  }

  assert.equal(calls.length, 1);
  assert.equal(calls[0][0], "/load_most_recent_image/clear_history");
  assert.equal(calls[0][1].method, "POST");
  assert.equal(widget.value, 1);
});

test("afterConfigureGraph names its configurations in the request", async () => {
  // The whole point: the backend deletes only the configurations listed here.
  // If the body were missing, opening one workflow would wipe every other.
  const app = fakeApp();
  const ext = createExtension(app);
  const { node, widget } = fakeNode({ widgetValue: 3 });
  node.widgets = [
    { name: "directory", value: "/work/out" },
    { name: "pattern", value: ".*\\.png$" },
    { name: "recursive", value: "true" },
    { name: "sort_by", value: "created" },
    widget,
  ];
  app.graph._nodes = [node];

  const calls = [];
  const realFetch = globalThis.fetch;
  globalThis.fetch = async (url, opts) => {
    calls.push([url, opts]);
    return { ok: true, status: 200 };
  };
  try {
    await ext.afterConfigureGraph();
  } finally {
    globalThis.fetch = realFetch;
  }

  const body = JSON.parse(calls[0][1].body);
  assert.deepEqual(body, {
    configs: [
      {
        directory: "/work/out",
        pattern: ".*\\.png$",
        recursive: "true",
        sort_by: "created",
      },
    ],
  });
});

test("afterConfigureGraph sends one entry per configured node", async () => {
  const app = fakeApp();
  const ext = createExtension(app);
  const first = fakeNode({ widgetValue: 4, directory: "/work/a" });
  const second = fakeNode({ widgetValue: 9, directory: "/work/b" });
  app.graph._nodes = [first.node, second.node];

  const calls = [];
  const realFetch = globalThis.fetch;
  globalThis.fetch = async (url, opts) => {
    calls.push([url, opts]);
    return { ok: true, status: 200 };
  };
  try {
    await ext.afterConfigureGraph();
  } finally {
    globalThis.fetch = realFetch;
  }

  const { configs } = JSON.parse(calls[0][1].body);
  assert.equal(configs.length, 2);
  assert.deepEqual(
    configs.map((c) => c.directory),
    ["/work/a", "/work/b"],
  );
  assert.equal(first.widget.value, 1);
  assert.equal(second.widget.value, 1);
});

test("afterConfigureGraph sends an empty list when the graph has none", async () => {
  // An empty list is not the same as no body: the backend sweeps everything
  // rather than reading it as a malformed request.
  const app = fakeApp();
  const ext = createExtension(app);
  app.graph._nodes = [];

  const calls = [];
  const realFetch = globalThis.fetch;
  globalThis.fetch = async (url, opts) => {
    calls.push([url, opts]);
    return { ok: true, status: 200 };
  };
  try {
    await ext.afterConfigureGraph();
  } finally {
    globalThis.fetch = realFetch;
  }

  assert.deepEqual(JSON.parse(calls[0][1].body), { configs: [] });
});

test("afterConfigureGraph omits a widget that does not exist", async () => {
  // JSON.stringify drops undefined keys, so an absent widget arrives as an
  // absent key. The backend then applies execute's defaults for it, rather
  // than computing a key the node would never write.
  const app = fakeApp();
  const ext = createExtension(app);
  const { node } = fakeNode({});
  node.widgets = [{ name: "directory", value: "/work/solo" }];
  app.graph._nodes = [node];

  const calls = [];
  const realFetch = globalThis.fetch;
  globalThis.fetch = async (url, opts) => {
    calls.push([url, opts]);
    return { ok: true, status: 200 };
  };
  try {
    await ext.afterConfigureGraph();
  } finally {
    globalThis.fetch = realFetch;
  }

  const { configs } = JSON.parse(calls[0][1].body);
  assert.deepEqual(configs, [{ directory: "/work/solo" }]);
  assert.equal("pattern" in configs[0], false);
});

test("afterConfigureGraph warns when the backend could not clear", async () => {
  // The widget resets to 1 either way, so a silent failure would leave it
  // claiming a fresh session while the old history is still persisted.
  const app = fakeApp();
  const ext = createExtension(app);
  const { node, widget } = fakeNode({ widgetValue: 7 });
  app.graph._nodes = [node];

  const realFetch = globalThis.fetch;
  const origWarn = console.warn;
  const warnings = [];
  globalThis.fetch = async () => ({ ok: false, status: 500 });
  console.warn = (...args) => warnings.push(args.join(" "));
  try {
    await ext.afterConfigureGraph();
  } finally {
    globalThis.fetch = realFetch;
    console.warn = origWarn;
  }

  assert.equal(warnings.length, 1);
  assert.ok(warnings[0].includes("500"));
  assert.equal(widget.value, 1);
});

test("afterConfigureGraph tolerates a missing node list", async () => {
  const app = fakeApp();
  delete app.graph._nodes;
  const ext = createExtension(app);
  await ext.afterConfigureGraph();
  assert.ok(true);
});

test("widget callback triggers a partial queue with the node id", async () => {
  const app = fakeApp();
  const ext = createExtension(app);
  const { node, widget } = fakeNode();
  await ext.nodeCreated(node);
  widget.callback(2);
  await new Promise((r) => setImmediate(r));
  await new Promise((r) => setTimeout(r, 0));
  assert.deepEqual(
    app.calls.map((c) => c[0]),
    ["graphToPrompt", "queuePrompt"],
  );
});

test("nodeCreated without an iter widget leaves onExecuted unwrapped", async () => {
  const ext = createExtension(fakeApp());
  const node = {
    comfyClass: "LoadMostRecentImage",
    id: 7,
    widgets: [],
    onExecuted: null,
  };
  await ext.nodeCreated(node);
  assert.equal(node.onExecuted, null);
});

test("nodeCreated normalises a null iter value to 1", async () => {
  const ext = createExtension(fakeApp());
  const { node, widget } = fakeNode({ widgetValue: null });
  await ext.nodeCreated(node);
  assert.equal(widget.value, 1);
});

test("nodeCreated normalises an empty-string iter value to 1", async () => {
  const ext = createExtension(fakeApp());
  const { node, widget } = fakeNode({ widgetValue: "" });
  await ext.nodeCreated(node);
  assert.equal(widget.value, 1);
});

test("widget callback treats undefined as 0", async () => {
  const ext = createExtension(fakeApp());
  const { node, widget } = fakeNode();
  await ext.nodeCreated(node);
  widget.callback(undefined);
  await new Promise((r) => setTimeout(r, 0));
  assert.ok(true);
});

test("widget callback does not cue when graphToPrompt is missing", async () => {
  const app = fakeApp();
  delete app.graphToPrompt;
  const ext = createExtension(app);
  const { node, widget } = fakeNode();
  await ext.nodeCreated(node);
  widget.callback(1);
  await new Promise((r) => setTimeout(r, 0));
  assert.deepEqual(app.calls, []);
});

test("onExecuted swallows errors from the original handler", async () => {
  const ext = createExtension(fakeApp());
  const { node, widget } = fakeNode();
  node.onExecuted = () => {
    throw new Error("boom");
  };
  await ext.nodeCreated(node);
  assert.doesNotThrow(() => node.onExecuted({ iter: [4] }));
  assert.equal(widget.value, 4);
});

test("onExecuted logs errors instead of crashing", async () => {
  const ext = createExtension(fakeApp());
  const { node } = fakeNode();
  await ext.nodeCreated(node);
  // Induce an exception inside the try block by corrupting the node widgets.
  Object.defineProperty(node, "widgets", {
    get() {
      throw new Error("boom");
    },
  });
  const origError = console.error;
  console.error = () => {};
  try {
    assert.doesNotThrow(() => node.onExecuted({ iter: [1] }));
  } finally {
    console.error = origError;
  }
});

test("widget callback swallows errors from the original callback", async () => {
  const ext = createExtension(fakeApp());
  const { node, widget } = fakeNode();
  node.widgets = [
    {
      name: "iter",
      value: 0,
      callback: () => {
        throw new Error("boom");
      },
    },
  ];
  await ext.nodeCreated(node);
  assert.doesNotThrow(() => node.widgets[0].callback(2));
});

test("widget callback logs errors from graphToPrompt", async () => {
  const app = fakeApp();
  app.graphToPrompt = async () => {
    throw new Error("boom");
  };
  const ext = createExtension(app);
  const { node, widget } = fakeNode();
  await ext.nodeCreated(node);
  const origError = console.error;
  console.error = () => {};
  try {
    widget.callback(1);
    await new Promise((r) => setTimeout(r, 0));
  } finally {
    console.error = origError;
  }
});

test("widget callback with no app functions returns without queuing", async () => {
  const app = fakeApp();
  delete app.queuePrompt;
  delete app.graphToPrompt;
  const ext = createExtension(app);
  const { node, widget } = fakeNode();
  await ext.nodeCreated(node);
  widget.callback(1);
  await new Promise((r) => setTimeout(r, 0));
  assert.deepEqual(app.calls, []);
});
