import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import { initLook } from "./lib/look";
import { initSky } from "./lib/sky";
import { initAppearance } from "./lib/theme";
import "./styles/tokens.css";
import "./styles/base.css";
import "./ui/ui.css";
import "./ui/glass.css";
import { Sky } from "./ui/Sky";

initAppearance();
initLook();
initSky(); // 首帧前上好天色（壁纸 = ui/Sky.tsx，整个应用一层，登录页也在上面）
ReactDOM.createRoot(document.getElementById("root")!).render(<React.StrictMode><Sky /><App /></React.StrictMode>);
