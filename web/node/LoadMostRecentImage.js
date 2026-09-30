import { app, api } from "../../../scripts/api.js";

console.log("[LMR] extension loaded");

app.registerExtension({
    name: "LoadMostRecentImage.WidgetUpdate",
    setup() {
        console.log("[LMR] setup called");
        api.addEventListener("executed", (event) => {
            try {
                console.log("[LMR] executed event:", JSON.stringify(event.detail));
                const { node_id, output } = event.detail;
                const node = app.graph.getNodeById(node_id);
                if (!node) {
                    console.log("[LMR] node not found:", node_id);
                    return;
                }
                if (node.comfyClass !== "LoadMostRecentImage") {
                    return;
                }
                console.log("[LMR] matching node executed, output:", JSON.stringify(output));
                if (output && output.ui && output.ui.reset_counter) {
                    const values = output.ui.reset_counter;
                    if (Array.isArray(values) && values.length > 0) {
                        const newValue = values[0];
                        const widget = node.widgets?.find(w => w.name === "reset_counter");
                        if (widget) {
                            console.log("[LMR] updating widget from", widget.value, "to", newValue);
                            widget.value = newValue;
                            if (widget.callback) {
                                widget.callback(widget.value);
                            }
                            node.setDirtyCanvas(true, true);
                        } else {
                            console.warn("[LMR] widget not found");
                        }
                    }
                }
            } catch (e) {
                console.error("[LMR] executed handler error:", e);
            }
        });
    },
});
