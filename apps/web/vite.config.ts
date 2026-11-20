/// <reference types="vitest/config" />
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";

const API = process.env.API_ORIGIN ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  server: {
    port: 5173,
    // Same-origin in dev so the HttpOnly refresh cookie (path /api/v1/auth) works like production behind Nginx.
    proxy: {
      "/api/v1/ws": { target: API.replace("http", "ws"), ws: true },
      "/api": { target: API, changeOrigin: false },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    css: false,
    globals: true,
  },
});
