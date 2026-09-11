import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const buildId = new Date().toISOString().slice(0, 19).replace("T", " ");

// Keep the dev proxy aligned with the backend, which honors COBOL_API_HOST /
// COBOL_API_PORT (defaults 127.0.0.1:8000).
const apiHost = process.env.COBOL_API_HOST || "127.0.0.1";
const apiPort = process.env.COBOL_API_PORT || "8000";
const apiTarget = `http://${apiHost}:${apiPort}`;

// Dev server port; override with WEB_DEV_PORT. Default avoids the common
// 5173/5174 range so it does not collide with other Vite apps.
const devPort = Number(process.env.WEB_DEV_PORT) || 5180;

export default defineConfig({
  define: {
    __APP_BUILD_ID__: JSON.stringify(buildId),
  },
  plugins: [react()],
  server: {
    port: devPort,
    proxy: {
      "/api": {
        target: apiTarget,
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
});
