import React from "react";
import ReactDOM from "react-dom/client";
import CaptureOverlay from "./capture/CaptureOverlay";
import "./styles/tokens.css";

// Entry point for the "capture" Tauri window (ui/shell/tauri.conf.json),
// separate from src/main.tsx's dashboard entry — a second Vite build
// input (vite.config.ts), matching the two-window shape Tauri expects
// (each window loads its own HTML document). Deliberately does NOT
// import styles/base.css: that stylesheet targets the dashboard's
// `.shell`/`.left-rail`/etc. chrome, none of which this window has.
ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <CaptureOverlay />
  </React.StrictMode>,
);
