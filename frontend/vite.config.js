import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// `npm run dev` talks to the Python server on :8000. `npm run build` writes dist/,
// which the Python server then serves at http://127.0.0.1:8000/ (no Node needed on demo day).
const backend = "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": backend,
      "/media": backend,
      "/console": backend,
      "/phone": backend,
      "/ws": { target: backend.replace("http", "ws"), ws: true },
    },
  },
  build: { outDir: "dist", emptyOutDir: true, chunkSizeWarningLimit: 900 },
  test: { environment: "node", include: ["src/tests/**/*.test.js"] },
});
