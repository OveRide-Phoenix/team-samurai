import React from "react";
import { createRoot } from "react-dom/client";
import { App } from "./Portfolio.tsx";
import "@fontsource-variable/inter";
import "./styles.css";
import { resolveBrowserScope } from "./browserStorage";

async function start() {
  const root = document.getElementById("root");
  try {
    const scope = await resolveBrowserScope(import.meta.env.PROD);
    createRoot(root).render(
      <React.StrictMode>
        <App scope={scope} />
      </React.StrictMode>,
    );
  } catch {
    root.setAttribute("role", "alert");
    root.textContent = "Your session could not be opened. Reload Samurai to try again.";
  }
}
void start();
