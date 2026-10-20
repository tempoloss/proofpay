import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// Node 25+ ships its own `localStorage` global (undefined without
// --localstorage-file) that shadows the one jsdom provides; Vitest exposes the
// jsdom instance, so point the global back at jsdom's storage.
declare const jsdom: { window: Window } | undefined;
if (typeof jsdom !== "undefined") {
  Object.defineProperty(globalThis, "localStorage", { value: jsdom.window.localStorage, configurable: true });
}

afterEach(() => {
  cleanup();
  localStorage.clear();
});
