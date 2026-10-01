import { app } from "../../../scripts/app.js";

app.registerExtension({
    name: "LoadMostRecentImage.WidgetUpdate",
    async nodeCreated(node) {
        if (node.comfyClass !== "LoadMostRecentImage") {
            return;
        }

        const originalOnExecuted = node.onExecuted;
        node.onExecuted = function(message) {
            if (originalOnExecuted) {
                try { originalOnExecuted.call(this, message); } catch(e) {}
            }
            try {
                if (message && message.iter !== undefined) {
                    const values = message.iter;
                    if (Array.isArray(values) && values.length > 0) {
                        const newValue = values[0];
                        const widget = node.widgets?.find(w => w.name === "iter");
                        if (widget) {
                            widget.value = newValue;
                            if (widget.callback) {
                                widget.callback(widget.value);
                            }
                            node.setDirtyCanvas(true, true);
                        }
                    }
                }
            } catch (e) {
                console.error("[LMR] error:", e);
            }
        };

        const iterWidget = node.widgets?.find(w => w.name === "iter");
        if (iterWidget) {
            const originalCallback = iterWidget.callback;
            iterWidget.callback = function(value, ...args) {
                if (originalCallback) {
                    try { originalCallback.call(this, value, ...args); } catch(e) {}
                }
                (async () => {
                    try {
                        if (typeof app.queuePrompt === "function" && typeof app.graphToPrompt === "function") {
                            const prompt = await app.graphToPrompt();
                            await app.queuePrompt(0, prompt, { partialExecutionTargets: [String(node.id)] });
                        }
                    } catch (e) {
                        console.error("[LMR] partial exec error:", e);
                    }
                })();
            };
        }
    },
});
