import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 开发:后端 ./run_web.sh 起在 8000,前端 5173 通过代理访问 /api。
// 发布:npm run build 输出到 dist(提交进 git,部署机无需 Node)。
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: { '/api': 'http://127.0.0.1:8000' },
  },
  build: { outDir: 'dist', emptyOutDir: true },
})
