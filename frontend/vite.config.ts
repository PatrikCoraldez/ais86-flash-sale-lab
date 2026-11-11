import { defineConfig, type Plugin } from 'vite';

const apiTarget = 'http://127.0.0.1:8019';

function contentSecurityPolicy(): Plugin {
  return {
    name: 'flash-content-security-policy',
    apply: 'build',
    transformIndexHtml() {
      return [
        {
          tag: 'meta',
          attrs: {
            'http-equiv': 'Content-Security-Policy',
            content:
              "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self'; base-uri 'self'; form-action 'self'; object-src 'none'"
          },
          injectTo: 'head-prepend'
        }
      ];
    }
  };
}

export default defineConfig({
  plugins: [contentSecurityPolicy()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    proxy: {
      '/api': { target: apiTarget, changeOrigin: false },
      '/healthz': { target: apiTarget, changeOrigin: false },
      '/readyz': { target: apiTarget, changeOrigin: false }
    }
  },
  build: {
    outDir: 'dist',
    assetsDir: 'assets',
    assetsInlineLimit: 0,
    sourcemap: false,
    target: 'es2022'
  }
});
