import { defineConfig } from "vite";
export default defineConfig({
  base: "./",
  build: { outDir: "dist", sourcemap: false },
  server: { strictPort: true, port: 5173 },
  preview: { strictPort: true, port: 4173 },
});
