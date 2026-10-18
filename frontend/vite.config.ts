import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: {
    // The AudioWorklet module must be a real file: audioWorklet.addModule()
    // doesn't reliably accept the data: URL Vite would inline for small files.
    assetsInlineLimit: (file) => (file.endsWith('.worklet.js') ? false : undefined),
  },
})
