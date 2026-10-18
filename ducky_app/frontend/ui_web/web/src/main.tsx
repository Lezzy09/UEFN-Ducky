import React from "react";
import ReactDOM from "react-dom/client";
// The app's fonts ship inside it (nothing is fetched from the internet at runtime).
import "@fontsource/inter/400.css";
import "@fontsource/inter/500.css";
import "@fontsource/inter/600.css";
import "@fontsource/jetbrains-mono/400.css";
import "@fontsource/jetbrains-mono/500.css";
import "./theme/styles/index.css";
import App from "./App";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { dismissBootSplashAfterPaint } from "./bootSplash";
import {
  directConfigFromLocation,
  hideDesktopBridge,
  isDirectMode,
  isRemoteDuckyWindow,
  startDirectTransport,
} from "./remote/directTransport";
import { RemoteDuckyBar } from "./components/RemoteDuckyBar";
import { installAppIdle } from "./utils/appIdle";

const remoteDucky = isRemoteDuckyWindow();
// Phone panel on the panel host, or a window showing another of your UEFN Duckies:
// bring up the WebRTC transport before React mounts so the first PanelApi call
// already has somewhere to go.
if (isDirectMode()) {
  if (remoteDucky) hideDesktopBridge();
  startDirectTransport(directConfigFromLocation(__PANEL_VERSION__));
} else {
  // Tell Ducky the page started: a window whose page never gets here is reported
  // as stuck on its loading screen (frontend/boot_report.py).
  (window as Window & { __duckyStarted?: boolean }).__duckyStarted = true;
  void fetch("/__panel_boot", { method: "POST", body: '{"started":true}' }).catch(() => undefined);
}

// Endless glows hold still while the window sits in the background.
installAppIdle();

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    {remoteDucky ? <RemoteDuckyBar name={directConfigFromLocation(__PANEL_VERSION__).name || "UEFN Ducky"} /> : null}
    <ErrorBoundary label="App">
      <App />
    </ErrorBoundary>
  </React.StrictMode>
);

// Keep the HTML splash up for ~3.5s (and until the app shell has painted),
// then fade it out so the logo reads clearly before the UI appears.
dismissBootSplashAfterPaint();
