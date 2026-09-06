import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 개발 중에는 5173 에서 뜨고 /api 요청만 코어(8000)로 넘긴다.
// 폐쇄망에서는 npm run build 결과(dist)를 코어가 직접 서빙하므로 프록시가 필요없다.
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: process.env.CORE_URL || 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    // 외부 CDN 을 쓰지 않도록 모든 자원을 번들에 넣는다. (폐쇄망 전제)
    assetsInlineLimit: 0,
  },
})
