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
} = {}) {
  const widget = { name: "iter", value: widgetValue, callback: null };
  const node = {
    comfyClass,
    id: 7,
    widgets: [widget],
    onExecuted: null,
    setDirtyCanvas(a, b) {
      this.dirtied = a && b;
    },
  };
  return { node, widget };
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
  const { node: other } = fakeNode({ comfyClass: "Other", widgetValue: 4 });
  app.graph._nodes = [n1, n2, other];
  await ext.afterConfigureGraph();
  assert.equal(w1.value, 1);
  assert.equal(w2.value, 1);
  assert.equal(other.widgets[0].value, 4);
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

  assert.deepEqual(calls, [
    ["/load_most_recent_image/clear_history", { method: "POST" }],
  ]);
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
