import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  worker: { format: "es" },
  server: {
    port: 5173,
    // examples/ and backend test fixtures live next to frontend/
    fs: { allow: [".."] },
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/ws": { target: "ws://127.0.0.1:8000", ws: true },
    },
  },
  build: { chunkSizeWarningLimit: 4000 },
  test: { include: ["test/**/*.test.ts"], environment: "node" },
});
