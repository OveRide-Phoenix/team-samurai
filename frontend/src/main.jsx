import React from "react";
import { createRoot } from "react-dom/client";
import { App } from "./Portfolio.tsx";
import "@fontsource-variable/inter";
import "./styles.css";
import { resolveBrowserScope } from "./browserStorage";

async function start() {
  const root = document.getElementById("root");
  try {
    if (import.meta.env.DEV && ['panels', 'intake'].includes(new URLSearchParams(location.search).get('preview'))) {
      const { default: LocalPanelPreview } = await import('./LocalPanelPreview');
      createRoot(root).render(<React.StrictMode><LocalPanelPreview /></React.StrictMode>);
      return;
    }
    const scope = await resolveBrowserScope(import.meta.env.PROD);
    createRoot(root).render(
      <React.StrictMode>
        <App scope={scope} />
      </React.StrictMode>,
    );
  } catch {
    root.setAttribute("role", "alert");
    root.textContent = "Sign in to Samurai and reload to open your workspace.";
  }
}
void start();
