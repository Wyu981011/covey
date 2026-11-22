// 自托管构建的 Tailwind 配置：和 tailwind.config.ts 一样扫 client/src，但不引用妙搭的预设（也就不扫平台包）
export default {
  darkMode: 'class',
  content: ['./client/src/**/*.{ts,tsx,css}'],
  prefix: '',
  plugins: [],
};
