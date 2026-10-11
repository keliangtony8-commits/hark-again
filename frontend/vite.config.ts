import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// 本地开发：把 /api 和 /ws 代理到后端
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://localhost:8000",
      "/ws": { target: "ws://localhost:8000", ws: true },
    },
  },
});
