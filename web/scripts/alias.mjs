// 单测里认 vite、tsc 认的路径别名（@shared/、@client/）和不带扩展名的相对导入（./room → ./room.ts），
// 这样被测的纯函数模块可以照项目里的写法互相导入：node --import ./scripts/alias.mjs --test scripts/xxx.test.mjs
import { registerHooks } from 'node:module';
import { statSync } from 'node:fs';

const root = new URL('../', import.meta.url);
const ALIASES = [['@shared/', 'shared/'], ['@client/', 'client/']];
const TRY = ['', '.ts', '/index.ts'];

const isFile = (url) => {
  try {
    return statSync(url).isFile();
  } catch {
    return false;
  }
};
const found = (href) => TRY.map((ext) => new URL(href + ext)).find(isFile)?.href ?? null;

registerHooks({
  resolve(specifier, context, next) {
    for (const [alias, dir] of ALIASES) {
      if (specifier.startsWith(alias)) {
        const hit = found(new URL(dir + specifier.slice(alias.length), root).href);
        if (hit) return next(hit, context);
      }
    }
    if (/^\.\.?\//u.test(specifier) && context.parentURL?.endsWith('.ts') && !/\.[cm]?[jt]sx?$/u.test(specifier)) {
      const hit = found(new URL(specifier, context.parentURL).href);
      if (hit) return next(hit, context);
    }
    return next(specifier, context);
  },
});
