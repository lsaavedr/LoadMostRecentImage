import { app, api } from "../../../scripts/api.js";

app.registerExtension({
    name: "LoadMostRecentImage.WidgetUpdate",
    async setup() {
        console.log("[LMR] extension loaded");
    },
    async nodeCreated(node) {
        if (node.comfyClass !== "LoadMostRecentImage") {
            return;
        }
        console.log("[LMR] node created:", node.id, "widgets:", node.widgets?.map(w => w.name));
    },
});

api.addEventListener("executed", (event) => {
    const { node_id, output } = event.detail;
    console.log("[LMR] executed event for node:", node_id, "output:", JSON.stringify(output));
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
                console.log("[LMR] updating widget from", widget.value, "to", newValue);
                widget.value = newValue;
                if (widget.callback) {
                    widget.callback(widget.value);
                }
                node.setDirtyCanvas(true, true);
            } else {
                console.warn("[LMR] widget 'reset_counter' not found in node", node.id);
            }
        }
    }
});
