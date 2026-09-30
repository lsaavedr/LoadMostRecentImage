import { app } from "../../../scripts/app.js";

app.registerExtension({
    name: "LoadMostRecentImage.WidgetUpdate",
    async nodeCreated(node) {
        if (node.comfyClass !== "LoadMostRecentImage") {
            return;
        }

        const onExecuted = node.onExecuted;
        node.onExecuted = function (message) {
            const r = onExecuted ? onExecuted.apply(this, arguments) : undefined;
            try {
                if (message && message.ui && message.ui.reset_counter) {
                    const values = message.ui.reset_counter;
                    if (Array.isArray(values) && values.length > 0) {
                        const newValue = values[0];
                        const widget = node.widgets?.find(w => w.name === "reset_counter");
                        if (widget) {
                            widget.value = newValue;
                            if (node.onWidgetChanged && typeof widget.callback === "function") {
                                widget.callback(widget.value);
                            }
                            node.setDirtyCanvas(true, true);
                        }
                    }
                }
            } catch (e) {
                console.error("[LMR] widget update error", e);
            }
            return r;
        };
    },
});
