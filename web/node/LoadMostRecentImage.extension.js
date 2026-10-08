// Pure extension definition — no ComfyUI imports — so it can be unit tested
// with a stub graph/node/app.
export function createExtension(app) {
  return {
    name: "LoadMostRecentImage.WidgetUpdate",

    async nodeCreated(node) {
      if (node.comfyClass !== "LoadMostRecentImage") {
        return;
      }

      const iterWidget = node.widgets?.find((w) => w.name === "iter");
      if (!iterWidget) {
        return;
      }

      if (
        iterWidget.value === undefined ||
        iterWidget.value === null ||
        iterWidget.value === ""
      ) {
        iterWidget.value = 1;
      }

      const originalOnExecuted = node.onExecuted;
      node.onExecuted = function (message) {
        if (originalOnExecuted) {
          try {
            originalOnExecuted.call(this, message);
          } catch (e) {}
        }
        try {
          if (message && message.iter !== undefined) {
            const values = message.iter;
            if (Array.isArray(values) && values.length > 0) {
              const newValue = values[0];
              const widget = node.widgets?.find((w) => w.name === "iter");
              if (widget) {
                widget.value = newValue;
                // Do NOT fire widget.callback here: it would
                // queue another partial execution and the node
                // would recurse, with `iter` running upwards from
                // whatever state was persisted on disk.
                node.setDirtyCanvas(true, true);
              }
            }
          }
        } catch (e) {
          console.error("[LMR] error:", e);
        }
      };

      const originalCallback = iterWidget.callback;
      iterWidget.callback = function (value, ...args) {
        if (value === undefined || value === null || value === "") {
          value = 0;
        }
        if (originalCallback) {
          try {
            originalCallback.call(this, value, ...args);
          } catch (e) {}
        }
        (async () => {
          try {
            if (
              typeof app.queuePrompt === "function" &&
              typeof app.graphToPrompt === "function"
            ) {
              const prompt = await app.graphToPrompt();
              await app.queuePrompt(0, prompt, {
                partialExecutionTargets: [String(node.id)],
              });
            }
          } catch (e) {
            console.error("[LMR] partial exec error:", e);
          }
        })();
      };
    },

    async afterConfigureGraph() {
      // A fresh page shows a brand-new session:
      //  - the widget counter goes back to 0
      //  - the backend's persisted history is wiped
      try {
        const res = await fetch("/load_most_recent_image/clear_history", {
          method: "POST",
        });
        if (res && res.ok === false) {
          console.warn(
            "[LMR] clear_history failed (HTTP " +
              res.status +
              "); the persisted history was left in place.",
          );
        }
      } catch (e) {
        // No backend available (e.g. unit tests) — ignore.
      }
      for (const node of app.graph._nodes || []) {
        if (node.comfyClass !== "LoadMostRecentImage") {
          continue;
        }
        const iterWidget = node.widgets?.find((w) => w.name === "iter");
        if (iterWidget) {
          iterWidget.value = 1;
        }
      }
    },
  };
}
