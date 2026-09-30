import { app } from "../../../scripts/app.js";
console.log("[LMR] app loaded, registering extension");

app.registerExtension({
    name: "LoadMostRecentImage.WidgetUpdate",
    setup() {
        console.log("[LMR] SETUP called");
    },
    nodeCreated(node) {
        console.log("[LMR] nodeCreated:", node.comfyClass, "id:", node.id);
        if (node.comfyClass === "LoadMostRecentImage") {
            console.log("[LMR] >>> MATCH! widgets:", node.widgets?.map(w => w.name));
        }
    },
});
