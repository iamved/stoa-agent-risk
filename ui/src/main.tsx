import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { EmbeddedProvider } from "./data/embedded";
import { App } from "./app/App";
import "./styles.css";

const root = document.getElementById("root");
if (root) {
  createRoot(root).render(
    <StrictMode>
      <App provider={new EmbeddedProvider()} />
    </StrictMode>,
  );
}
