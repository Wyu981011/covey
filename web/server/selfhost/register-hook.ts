/**
 * 自托管入口最先加载的模块：把 '@lark-apaas/fullstack-nestjs-core' 指到本地垫片，其余 @lark-apaas/* 一律拒绝。
 * 这样 workbench 的现有代码不用改，自托管运行时也不会加载任何妙搭平台的包。
 */
import Module from 'node:module';
import { join } from 'node:path';

const PLATFORM = '@lark-apaas/fullstack-nestjs-core';
const SHIM: string = join(__dirname, 'platform-shim');

type Resolve = (request: string, ...rest: unknown[]) => string;
const mod = Module as unknown as { _resolveFilename: Resolve };
const original: Resolve = mod._resolveFilename;

mod._resolveFilename = function patched(this: unknown, request: string, ...rest: unknown[]): string {
  if (request === PLATFORM) return original.call(this, SHIM, ...rest);
  if (request.startsWith('@lark-apaas/')) throw new Error(`自托管不加载妙搭平台的包：${request}`);
  return original.call(this, request, ...rest);
};
