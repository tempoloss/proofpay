import { fileURLToPath } from "node:url";
import tailwind from "@tailwindcss/vite";
import { tanstackRouter } from "@tanstack/router-plugin/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [tanstackRouter({ target: "react", autoCodeSplitting: true }), react(), tailwind()],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  server: {
    port: 5273,
    host: true,
    strictPort: true,
    // Same origin for the page, the API, the PayPal return URLs and MCP: no CORS.
    proxy: {
      "/api": "http://localhost:8000",
      "/paypal": "http://localhost:8000",
      "/mcp": "http://localhost:8001",
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    restoreMocks: true,
  },
});
