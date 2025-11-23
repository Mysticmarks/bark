import { defineConfig } from 'vite';

export default defineConfig({
  server: {
    port: 4173,
    host: true,
    proxy: {
      '/api': 'http://localhost:8000'
    }
  },
  build: {
    sourcemap: true,
    cssCodeSplit: true,
    assetsInlineLimit: 4096,
    chunkSizeWarningLimit: 600,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('three')) return 'three';
        }
      }
    }
  }
});
