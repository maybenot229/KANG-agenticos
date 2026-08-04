import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./styles/tokens.css";
import "./styles/base.css";

// Pure API client (UI-P1): this file's only job is mounting React. No
// truth, no domain logic, no local persistence beyond view preferences —
// everything KANG knows comes from the generated client (ADR-011), never
// from state invented here.
ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
