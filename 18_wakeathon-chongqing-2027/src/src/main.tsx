import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);

// 评测模式：`?eval=1` 时注入 window.__wakeEval，供 Playwright CLI 跑分。
// 演示路径不受影响（条件动态导入，普通访问不会加载评测代码）。
if (new URLSearchParams(window.location.search).has("eval")) {
  void import("./eval/bridge").then(({ installEvalBridge }) => installEvalBridge());
}
