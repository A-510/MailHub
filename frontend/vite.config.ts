import fs from 'node:fs'
import path from 'node:path'
import { defineConfig, type Plugin } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

const LIVE2D_MIME_TYPES: Record<string, string> = {
  '.json': 'application/json; charset=utf-8',
  '.png': 'image/png',
  '.moc3': 'application/octet-stream',
  '.txt': 'text/plain; charset=utf-8',
  '.md': 'text/markdown; charset=utf-8',
}

/**
 * 在 Vite 开发服务器中直出项目根目录下的 live2d/ 静态资源
 */
function serveRootLive2dPlugin(): Plugin {
  const live2dRoot = path.resolve(__dirname, '../live2d')

  return {
    name: 'serve-root-live2d',
    configureServer(server) {
      server.middlewares.use('/live2d', (req, res, next) => {
        const rawUrl = (req.url || '/').split('?')[0]
        let decodedPath = ''
        try {
          decodedPath = decodeURIComponent(rawUrl).replace(/^\/+/, '')
        } catch {
          res.statusCode = 400
          res.end('Invalid URL encoding')
          return
        }

        const targetPath = path.resolve(live2dRoot, decodedPath)
        // 防止路径穿越访问 live2d 目录之外的文件
        if (targetPath !== live2dRoot && !targetPath.startsWith(live2dRoot + path.sep)) {
          res.statusCode = 403
          res.end('Forbidden')
          return
        }

        if (!fs.existsSync(targetPath) || !fs.statSync(targetPath).isFile()) {
          next()
          return
        }

        const ext = path.extname(targetPath).toLowerCase()
        res.setHeader('Content-Type', LIVE2D_MIME_TYPES[ext] ?? 'application/octet-stream')
        fs.createReadStream(targetPath).pipe(res)
      })
    },
  }
}

export default defineConfig({
  plugins: [vue(), serveRootLive2dPlugin()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8765',
        changeOrigin: true,
      },
    },
  },
})
