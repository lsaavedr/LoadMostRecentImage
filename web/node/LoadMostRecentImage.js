import { app } from "../../../scripts/app.js";

console.log("[LMR] extension loaded");

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
                if (message && message.reset_counter) {
                    const values = message.reset_counter;
                    if (Array.isArray(values) && values.length > 0) {
                        const newValue = values[0];
                        const widget = node.widgets?.find(w => w.name === "reset_counter");
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
    },
});
