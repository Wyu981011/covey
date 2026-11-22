// 自托管前端构建：不用 @lark-apaas 的 Vite 预设；把代码里用到的 @lark-apaas/client-toolkit 换成 client/src/selfhost/ 下的垫片。
// 页面不引入任何妙搭监控、埋点、水印脚本。输出到 dist-selfhost/client（index.html + assets）。
import path from 'path';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

const shim = (name: string): string => path.resolve(__dirname, 'client/src/selfhost', name);

export default defineConfig({
  root: path.resolve(__dirname, 'client/selfhost'),
  publicDir: path.resolve(__dirname, 'client/public'),
  base: '/',
  plugins: [react()],
  define: {
    __SELFHOST__: 'true',
    'process.env.CLIENT_BASE_PATH': JSON.stringify('/'),
    'process.env.NODE_ENV': JSON.stringify('production'),
  },
  resolve: {
    alias: [
      { find: '@client', replacement: path.resolve(__dirname, 'client') },
      { find: '@shared', replacement: path.resolve(__dirname, 'shared') },
      { find: /^@lark-apaas\/client-toolkit\/utils\/getAxiosForBackend$/u, replacement: shim('getAxiosForBackend.ts') },
      { find: /^@lark-apaas\/client-toolkit\/logger$/u, replacement: shim('logger.ts') },
      { find: /^@lark-apaas\/client-toolkit\/components\/AppContainer$/u, replacement: shim('AppContainer.tsx') },
      { find: /^@lark-apaas\/client-toolkit\/components\/ErrorRender$/u, replacement: shim('ErrorRender.tsx') },
      { find: /^@lark-apaas\/client-toolkit\/components\/NotFoundRender$/u, replacement: shim('NotFoundRender.tsx') },
      { find: /^@lark-apaas\/client-toolkit\/lib\/index\.css$/u, replacement: shim('toolkit.css') },
      { find: /^@\//u, replacement: `${path.resolve(__dirname, 'client/src')}/` },
    ],
  },
  build: {
    outDir: path.resolve(__dirname, 'dist-selfhost/client'),
    emptyOutDir: true,
    sourcemap: false,
    chunkSizeWarningLimit: 2500,
  },
});
