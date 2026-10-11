import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import { initLook } from "./lib/look";
import { initAppearance } from "./lib/theme";
import "./styles/tokens.css";
import "./styles/base.css";
import "./ui/ui.css";
import "./ui/glass.css";

initAppearance();
initLook();
ReactDOM.createRoot(document.getElementById("root")!).render(<React.StrictMode><App /></React.StrictMode>);
