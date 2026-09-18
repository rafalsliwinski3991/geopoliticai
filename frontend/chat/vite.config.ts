import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  base: "/chat/",
  plugins: [react()],
  server: {
    // `npm run dev` works against Compose without nginx: the SPA runs on its
    // own port and proxies the two routes it needs.
    proxy: {
      "/api": "http://localhost:3001",
      "/accounts": "http://localhost:8083",
    },
  },
  test: {
    environment: "jsdom",
  },
});
