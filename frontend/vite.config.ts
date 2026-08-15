import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: false,
    proxy: {
      "/health": process.env.VITE_API_PROXY_TARGET ?? "http://localhost:8000",
      "/v1": process.env.VITE_API_PROXY_TARGET ?? "http://localhost:8000"
    }
  }
});
