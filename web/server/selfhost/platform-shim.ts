/**
 * 妙搭平台包 @lark-apaas/fullstack-nestjs-core 里 workbench 现有代码用到的那几个名字，自托管用本地实现。
 * register-hook.ts 把对那个包的 require 指到这里。
 */
import { SetMetadata } from '@nestjs/common';
import type { SQL } from 'drizzle-orm';

/** 数据库的注入令牌：自托管模块里提供 PGlite 或外部 Postgres 的包装 */
export const DRIZZLE_DATABASE = 'DRIZZLE_DATABASE';

/** 服务只用 `execute(sql\`…\`)`，PGlite 返回 `{rows}`、Postgres 返回行数组 */
export interface PostgresJsDatabase {
  execute(query: SQL): Promise<unknown>;
}

export const NEED_LOGIN = 'selfhost:need_login';

/** 平台上靠它挂登录校验；自托管里 /api 的会话校验在 auth.middleware.ts，这里只留标记 */
export function NeedLogin(): ClassDecorator & MethodDecorator {
  return SetMetadata(NEED_LOGIN, true);
}
