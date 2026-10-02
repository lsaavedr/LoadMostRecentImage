import { app } from "../../../scripts/app.js";
import { createExtension } from "./LoadMostRecentImage.extension.js";

app.registerExtension(createExtension(app));
