console.log("[LMR] script reached");

try {
    import { app } from "../../../scripts/app.js";
    console.log("[LMR] app imported");
} catch (e) {
    console.error("[LMR] import error:", e);
}

setTimeout(() => {
    try {
        console.log("[LMR] timeout fired, checking app");
        if (typeof app === "undefined") {
            console.error("[LMR] app is undefined");
            return;
        }
        console.log("[LMR] app available");

        app.registerExtension({
            name: "LoadMostRecentImage.WidgetUpdate",
            async setup() {
                console.log("[LMR] extension setup called");
            },
            async nodeCreated(node) {
                console.log("[LMR] nodeCreated for any node:", node.comfyClass, node.id);
                if (node.comfyClass !== "LoadMostRecentImage") {
                    return;
                }
                console.log("[LMR] matching node found! widgets:", node.widgets?.map(w => w.name));
            },
        });
    } catch (e) {
        console.error("[LMR] setup error:", e);
    }
}, 500);
