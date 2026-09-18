import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { viteSingleFile } from "vite-plugin-singlefile";

// One self-contained HTML file. All JS and CSS are inlined; the Python
// injector later replaces the data placeholder and pins the CSP hashes.
export default defineConfig({
  plugins: [react(), tailwindcss(), viteSingleFile({ removeViteModuleLoader: true })],
  resolve: {
    alias: {
      // One vendored copy of Cytoscape, shared with the legacy report. The npm
      // package is a devDependency for its type definitions only.
      cytoscape: fileURLToPath(new URL("../src/stoa/templates/cytoscape.min.js", import.meta.url)),
    },
  },
  build: {
    // The vendored Cytoscape build is UMD and lives outside node_modules.
    commonjsOptions: { include: [/cytoscape\.min\.js$/, /node_modules/] },
    outDir: "dist",
    emptyOutDir: true,
    target: "es2022",
    cssCodeSplit: false,
    assetsInlineLimit: 100_000_000,
    reportCompressedSize: false,
    modulePreload: { polyfill: false },
  },
  test: {
    environment: "node",
    include: ["tests/**/*.test.ts"],
  },
});
