import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    include: ["packages/*/tests/**/*.test.ts", "apps/game-server/tests/**/*.test.ts", "apps/web/tests/**/*.test.ts"],
    environment: "node",
  },
});
