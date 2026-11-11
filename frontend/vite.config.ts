import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The built files go into the Python package, so `pipx install` needs no Node.
export default defineConfig({
  plugins: [react()],
  base: "./",
  build: {
    outDir: "../src/hiab/web",
    emptyOutDir: true,
    chunkSizeWarningLimit: 900,
  },
  server: {
    proxy: { "/api": "http://127.0.0.1:2222" },
  },
});
