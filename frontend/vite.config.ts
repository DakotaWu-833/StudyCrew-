import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import { resolve } from "node:path";

export default defineConfig({
  plugins: [react()],
  base: "/static/workspace/",
  build: {
    // Django versions the single workspace stylesheet. Route scripts retain
    // content hashes while their shared styles load with the shell.
    cssCodeSplit: false,
    outDir: resolve(import.meta.dirname, "../static/workspace"),
    emptyOutDir: true,
    sourcemap: false,
    manifest: true,
    rollupOptions: {
      output: {
        // The Django entry URL carries a version query. Shared modules must
        // never import that entry again through an unversioned URL: browsers
        // would instantiate a second router/query context and root.
        manualChunks: (id) => {
          if (id.includes("preload-helper")) return "preload";
          if (id.includes("pdfjs-dist")) return "pdf-preview";
          if (id.includes("node_modules")) return "vendor";
          if (/\/src\/(api|app|components)\//.test(id.replaceAll("\\", "/"))) return "workspace";
        },
        entryFileNames: "main.js",
        chunkFileNames: "assets/[name]-[hash].js",
        assetFileNames: (assetInfo) =>
          assetInfo.names.some((name) => name.endsWith(".css"))
            ? "workspace.css"
            : "assets/[name]-[hash][extname]",
      },
    },
  },
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/account": "http://127.0.0.1:8000",
    },
  },
  test: {
    environment: "jsdom",
  },
});
