/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The UI lives under /ui so its routes never collide with API paths (/search, /files, ...).
// In dev, API calls are proxied to FastAPI; in production FastAPI serves frontend/dist at /ui itself.
const API = process.env.API_URL ?? "http://localhost:8000";
const apiPaths = ["/search", "/files", "/chunks", "/ingest", "/answer", "/evaluation", "/config", "/docs", "/openapi.json"];

export default defineConfig({
  base: "/ui/",
  plugins: [react()],
  server: { proxy: Object.fromEntries(apiPaths.map((p) => [p, { target: API, changeOrigin: true }])) },
  test: { environment: "jsdom", setupFiles: ["src/test-setup.ts"], globals: false },
});
