import { resolve } from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const root = resolve(__dirname, "src/renderer");

export default defineConfig({
  root,
  base: "./",
  plugins: [react()],
  build: {
    outDir: resolve(__dirname, "dist/renderer"),
    emptyOutDir: true,
    rollupOptions: {
      input: {
        index: resolve(root, "index.html"),
        overlay: resolve(root, "overlay.html"),
        picker: resolve(root, "picker.html"),
      },
    },
  },
});
