import { defineConfig } from "@hey-api/openapi-ts";

/**
 * The API client is generated from the OpenAPI description, never written by
 * hand. The backend exports it with `uv run proofpay-cli openapi
 * ../frontend/schema/openapi.json`; the snapshot is committed, so type checks
 * and builds do not need a running server.
 *
 * Runtime settings live in `src/shared/lib/api-runtime.ts`: the output folder
 * is wiped on every generation.
 */
export default defineConfig({
  input: "./schema/openapi.json",
  output: { path: "src/shared/api" },
  plugins: [
    { name: "@hey-api/client-fetch", runtimeConfigPath: "./src/shared/lib/api-runtime.ts" },
    "@hey-api/typescript",
    "@hey-api/sdk",
    { name: "@tanstack/react-query", exportFromIndex: true },
  ],
});
