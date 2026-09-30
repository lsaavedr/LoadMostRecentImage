import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";

console.log("[LMR] extension loaded, app:", typeof app, "api:", typeof api);

app.registerExtension({
    name: "LoadMostRecentImage.WidgetUpdate",
    setup() {
        console.log("[LMR] setup called");
        api.addEventListener("executed", (event) => {
            try {
                const { node_id, output } = event.detail;
                const node = app.graph.getNodeById(node_id);
                if (!node || node.comfyClass !== "LoadMostRecentImage") {
                    return;
                }
                if (output && output.ui && output.ui.reset_counter) {
                    const values = output.ui.reset_counter;
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
        });
    },
});
