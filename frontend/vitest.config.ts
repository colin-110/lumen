import path from "node:path";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  // @vitejs/plugin-react and vitest resolve slightly different copies of vite's
  // types, which TS reports as an overload mismatch at this slot even though
  // the plugin is correct at runtime.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  plugins: [react() as any],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./vitest.setup.ts"],
    // Next's own build output and e2e dirs would otherwise be collected.
    include: ["src/**/*.test.{ts,tsx}"],
  },
  resolve: {
    // Mirrors the "@/*" -> "src/*" alias in tsconfig.json, so tests import
    // modules by the same specifier the app does.
    alias: { "@": path.resolve(__dirname, "./src") },
  },
});
