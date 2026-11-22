/**
 * 自托管的库：默认进程内 PGlite（数据目录 COVEY_WEB_DB_DIR），设了 DATABASE_URL 就连外部 Postgres。
 * 两种都包成现有服务用的 `execute(query)`：PGlite 返回 `{rows}`，Postgres 返回行数组，workbench.util 的 asRows 都认。
 * PGlite 只能一个进程打开同一个目录：别同时起两个自托管服务指同一个 COVEY_WEB_DB_DIR。
 */
import { existsSync, mkdirSync, renameSync, rmSync } from 'node:fs';
import { join } from 'node:path';
import { Logger } from '@nestjs/common';
import { PgDialect } from 'drizzle-orm/pg-core';
import type { SQL } from 'drizzle-orm';
import { SCHEMA } from './schema';
import type { SelfhostConfig } from './config';

export interface SelfhostDb {
  kind: 'pglite' | 'postgres';
  execute(query: SQL): Promise<unknown>;
  close(): Promise<void>;
  /** 整库快照（PGlite 的 dumpDataDir('gzip')，tar.gz）；外部 Postgres 返回 null，用 pg_dump */
  dump(): Promise<Buffer | null>;
}

/** 恢复标记：`<db>.restore/` 里写完全部内容后最后写它，启动时只认有它的 */
export const RESTORE_MARK = '.covey-restore-complete';

const stamp = (d: Date): string => d.toISOString().replace(/[-:]/gu, '').replace('T', '-').slice(0, 15);

/**
 * 启动时的恢复交换（只 PGlite）：`<db>.restore/.covey-restore-complete` 在，就把 `<db>` 改名成
 * `<db>.before-restore-<时间>`、删标记、把 `<db>.restore` 改名成 `<db>`。没标记的 .restore 只警告不动。
 * 返回做了什么：swapped（换了）、incomplete（没标记）、none。
 */
export function applyRestore(dbDir: string, now: Date = new Date()): 'swapped' | 'incomplete' | 'none' {
  const log = new Logger('SelfhostDb');
  const staged = `${dbDir}.restore`;
  if (!existsSync(staged)) return 'none';
  if (!existsSync(join(staged, RESTORE_MARK))) {
    log.warn(`${staged} 在，但没有 ${RESTORE_MARK}（还没放完？），不动它`);
    return 'incomplete';
  }
  const aside = `${dbDir}.before-restore-${stamp(now)}`;
  const hadDb: boolean = existsSync(dbDir);
  if (hadDb) renameSync(dbDir, aside);
  try {
    rmSync(join(staged, RESTORE_MARK), { force: true });
    renameSync(staged, dbDir);
  } catch (e) {
    if (hadDb && !existsSync(dbDir)) renameSync(aside, dbDir);
    throw e;
  }
  log.log(`已用 ${staged} 换上恢复的库${hadDb ? `，原库留在 ${aside}` : ''}`);
  return 'swapped';
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
    return { kind: 'postgres', execute: (q: SQL) => orm.execute(q) as Promise<unknown>, close: () => client.end(), dump: () => Promise.resolve(null) };
  }
  const { PGlite } = await import('@electric-sql/pglite');
  applyRestore(cfg.dbDir);
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
    dump: async () => Buffer.from(await (await pg.dumpDataDir('gzip')).arrayBuffer()),
  };
}
