import type { CreateClientConfig } from "../api/client.gen.ts";

/** The API lives on the same origin: Vite (dev) and nginx (prod) proxy /api to the backend. */
export const createClientConfig: CreateClientConfig = (config) => ({ ...config, baseUrl: "" });
