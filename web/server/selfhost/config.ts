/** 自托管服务的配置：全部来自环境变量（见 deploy/selfhost/README.md） */
import { readFileSync, statSync } from 'node:fs';
import { join, resolve } from 'node:path';

export interface SelfhostConfig {
  host: string;
  port: number;
  /** 外部 Postgres 的连接串；空就用进程内 PGlite */
  databaseUrl: string;
  dbDir: string;
  staticDir: string;
  allowRemoteOpenapi: boolean;
}

/** DATABASE_URL；没设时读 COVEY_WEB_DATABASE_URL_FILE 指的文件（Manager 拉起时指 <数据根>/web/database-url，有这个文件就用外部库：连接串可能带密码，不放服务清单） */
export function databaseUrlOf(env: NodeJS.ProcessEnv): string {
  const direct: string = (env.DATABASE_URL || '').trim();
  if (direct) return direct;
  const file: string = env.COVEY_WEB_DATABASE_URL_FILE || '';
  if (!file) return '';
  try {
    return readFileSync(file, 'utf8').trim();
  } catch {
    return '';
  }
}

export function loadConfig(env: NodeJS.ProcessEnv = process.env): SelfhostConfig {
  const port: number = Number(env.COVEY_WEB_PORT || '18650');
  return {
    host: env.COVEY_WEB_HOST || '127.0.0.1',
    port: Number.isInteger(port) && port > 0 && port < 65536 ? port : 18650,
    databaseUrl: databaseUrlOf(env),
    dbDir: resolve(env.COVEY_WEB_DB_DIR || './data/db'),
    // 构建产物里本文件在 dist-selfhost/server/selfhost/，前端在 dist-selfhost/client（单测按 ESM 直接导入时没有 __dirname）
    staticDir: resolve(env.COVEY_WEB_STATIC_DIR || join(typeof __dirname === 'string' ? __dirname : process.cwd(), '..', '..', 'client')),
    allowRemoteOpenapi: env.COVEY_WEB_OPENAPI_ALLOW_REMOTE === '1',
  };
}

/** 开放接口的密钥。密钥文件每次按修改时间重读：换了文件不用重启；文件读不到就当没配（接口全拒）。 */
export class KeySource {
  private cache: { path: string; mtimeMs: number; key: string } | null = null;

  private readonly env: NodeJS.ProcessEnv;

  constructor(env: NodeJS.ProcessEnv = process.env) {
    this.env = env;
  }

  current(): string {
    const file: string = this.env.COVEY_WEB_KEY_FILE || '';
    if (!file) return (this.env.COVEY_WEB_OPENAPI_KEY || '').trim();
    try {
      const mtimeMs: number = statSync(file).mtimeMs;
      if (!this.cache || this.cache.path !== file || this.cache.mtimeMs !== mtimeMs) {
        this.cache = { path: file, mtimeMs, key: readFileSync(file, 'utf8').trim() };
      }
      return this.cache.key;
    } catch {
      this.cache = null;
      return '';
    }
  }
}
