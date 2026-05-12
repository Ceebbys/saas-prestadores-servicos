import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

// Bundle output: ../../static/js/chatbot-builder/
// (que entra no collectstatic Django + WhiteNoise re-hasheia para CompressedManifest)
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: path.resolve(__dirname, "../../static/js/chatbot-builder"),
    emptyOutDir: true,
    sourcemap: false, // WhiteNoise CompressedManifest quebra em sourcemaps
    rollupOptions: {
      output: {
        // Sem hash do Vite: WhiteNoise re-hasheia no collectstatic
        entryFileNames: "main.js",
        chunkFileNames: "chunks/[name].js",
        assetFileNames: (assetInfo) => {
          if (assetInfo.name && assetInfo.name.endsWith(".css")) {
            return "style.css";
          }
          return "[name][extname]";
        },
      },
    },
    // Pula a geração do index.html (Django serve via template flow_builder.html).
    // Mantemos `lib mode` para output direto sem HTML.
  },
  // Dev server (npm run dev) — não usado pelo Django, só para HMR local
  server: {
    port: 5173,
    strictPort: false,
  },
});
