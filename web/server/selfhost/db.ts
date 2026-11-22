/**
 * 自托管的库：默认进程内 PGlite（数据目录 COVEY_WEB_DB_DIR），设了 DATABASE_URL 就连外部 Postgres。
 * 两种都包成现有服务用的 `execute(query)`：PGlite 返回 `{rows}`，Postgres 返回行数组，workbench.util 的 asRows 都认。
 * PGlite 只能一个进程打开同一个目录：别同时起两个自托管服务指同一个 COVEY_WEB_DB_DIR。
 */
import { mkdirSync } from 'node:fs';
import { Logger } from '@nestjs/common';
import { PgDialect } from 'drizzle-orm/pg-core';
import type { SQL } from 'drizzle-orm';
import { SCHEMA } from './schema';
import type { SelfhostConfig } from './config';

export interface SelfhostDb {
  kind: 'pglite' | 'postgres';
  execute(query: SQL): Promise<unknown>;
  close(): Promise<void>;
}

export async function openDb(cfg: Pick<SelfhostConfig, 'databaseUrl' | 'dbDir'>): Promise<SelfhostDb> {
  const log = new Logger('SelfhostDb');
  if (cfg.databaseUrl) {
    const { default: postgres } = await import('postgres');
    const { drizzle } = await import('drizzle-orm/postgres-js');
    const client = postgres(cfg.databaseUrl, { max: 8, onnotice: () => undefined });
    const orm = drizzle(client);
    for (const ddl of SCHEMA) await client.unsafe(ddl);
    log.log('已连外部 Postgres（DATABASE_URL）');
    return { kind: 'postgres', execute: (q: SQL) => orm.execute(q) as Promise<unknown>, close: () => client.end() };
  }
  const { PGlite } = await import('@electric-sql/pglite');
  mkdirSync(cfg.dbDir, { recursive: true });
  const pg = new PGlite(cfg.dbDir);
  await pg.waitReady;
  const dialect = new PgDialect();
  await pg.exec(`${SCHEMA.join(';\n')};`);
  log.log(`进程内 PGlite，数据目录 ${cfg.dbDir}`);
  return {
    kind: 'pglite',
    execute: (q: SQL) => {
      const { sql, params } = dialect.sqlToQuery(q);
      return pg.query(sql, params as unknown[]);
    },
    close: () => pg.close(),
  };
}
