import { Injectable, Inject, BadRequestException, Logger } from '@nestjs/common';
import type { PostgresJsDatabase } from '@lark-apaas/fullstack-nestjs-core';
import { WB_DB } from './workbench.tokens';
import { sql } from 'drizzle-orm';
import {
  isSettingsKey,
  isSyncType,
  type InboxResponse,
  type SyncAckRequest,
  type SyncAckResponse,
  type SyncItem,
  type SyncUpsertRequest,
  type SyncUpsertResponse,
} from '@shared/api.interface';
import { arr, asRows, clipBody, missingTable, num, obj, str } from './workbench.util';
import { wake, waitFor } from './workbench.wake';

const MAX_ITEMS = 500;
/** 一批里同时写几条：库查询过闸门（workbench.guard.ts，Covey 这边最多 2 条连接），多发也只是排队，所以 4 条一组就够 */
const CHUNK = 4;
/** 挂着等取件时多久查一次库（毫秒） */
const INBOX_STEP_MS = 200;

interface OutboxRow {
  seq: number;
  op_id: string;
  kind: string;
  topic_key: string | null;
  project_key: string | null;
  payload: Record<string, unknown>;
  created_at: string;
}

/** Covey 一侧（/openapi）：推状态、取发件箱、回执 */
@Injectable()
export class WorkbenchSyncService {
  private readonly logger = new Logger(WorkbenchSyncService.name);
  /** 还没建 collabs 表时只记一次（协作条目跳过，别的照常收） */
  private noCollabTable = false;
  /** 妙搭模式没有登录表，第一次发现后不再查 */
  private noLoginTable = false;

  constructor(@Inject(WB_DB) private readonly db: PostgresJsDatabase) {}

  async upsert(body: SyncUpsertRequest): Promise<SyncUpsertResponse> {
    const items: SyncItem[] = arr<SyncItem>(body?.items);
    const deleted = arr<{ type: string; key: string }>(body?.deleted);
    if (items.length + deleted.length > MAX_ITEMS) {
      throw new BadRequestException(`一批最多 ${MAX_ITEMS} 条`);
    }
    for (const it of items) {
      if (!isSyncType(str(it?.type)) || !str(it?.key)) {
        throw new BadRequestException('每条要有合法的 type 和 key');
      }
      if (it.type === 'settings' && !isSettingsKey(it.key)) throw new BadRequestException('settings 的 key 不合法（7 个设置键或 memory:* 记忆键）');
    }
    for (const d of deleted) {
      if (d?.type === 'settings' && !isSettingsKey(str(d.key))) throw new BadRequestException('settings 的 key 不合法（7 个设置键或 memory:* 记忆键）');
    }
    let upserted = 0;
    for (let i = 0; i < items.length; i += CHUNK) {
      const part: SyncItem[] = items.slice(i, i + CHUNK);
      const results: number[] = await Promise.all(part.map((it: SyncItem) => this.upsertOne(it)));
      upserted += results.reduce((a: number, b: number) => a + b, 0);
    }
    let removed = 0;
    for (const d of deleted) {
      if (isSyncType(str(d?.type)) && str(d?.key) && (d.type !== 'settings' || isSettingsKey(d.key))) removed += await this.deleteOne(d.type, d.key);
    }
    await this.touchSynced();
    return { ok: true, upserted, skipped: items.length - upserted, deleted: removed };
  }

  /** 返回 1 表示写入，0 表示 rev 相同被跳过 */
  private async upsertOne(it: SyncItem): Promise<number> {
    const d: Record<string, unknown> = obj(it.data);
    const rev: string = str(it.rev);
    const json: string = JSON.stringify(d);
    switch (it.type) {
      case 'project':
        return this.write(sql`insert into projects(key, title, status, rev, data, updated_at)
          values (${it.key}, ${str(d.title)}, ${str(d.status, '在做')}, ${rev}, ${json}::jsonb, ${num(d.updated_at)})
          on conflict (key) do update set title = excluded.title, status = excluded.status,
            rev = excluded.rev, data = excluded.data, updated_at = excluded.updated_at, _updated_at = now()
          where projects.rev <> excluded.rev or excluded.rev = ''
          returning 1 as n`);
      case 'topic':
        // Covey 数据约定 v12：话题带 last_seq，这个话题 seq 比它大的轮次是推丢了的旧行（在跑时按“轮数 + 1”推的一轮，
        // 回答进来后落在更前的编号上），删掉；不然专项报告把同一个任务的 token 算两遍，还画成在跑
        if (typeof d.last_seq === 'number' && Number.isFinite(d.last_seq) && d.last_seq >= 0) {
          await this.db.execute(sql`delete from turns where topic_key = ${it.key} and seq > ${Math.floor(d.last_seq)}`);
        }
        return this.write(sql`insert into topics(key, project_key, number, title, state, unseen, rev, data, updated_at)
          values (${it.key}, ${str(d.project_key) || null}, ${typeof d.number === 'number' ? d.number : null},
            ${str(d.title)}, ${str(d.state, '空闲')}, ${d.unseen === true}, ${rev}, ${json}::jsonb, ${num(d.updated_at)})
          on conflict (key) do update set project_key = excluded.project_key, number = excluded.number,
            title = excluded.title, state = excluded.state, unseen = excluded.unseen, rev = excluded.rev,
            data = excluded.data, updated_at = excluded.updated_at, _updated_at = now()
          where topics.rev <> excluded.rev or excluded.rev = ''
          returning 1 as n`);
      case 'turn': {
        const body: string = clipBody(str(d.body));
        const rest: string = JSON.stringify({ ...d, body: undefined });
        return this.write(sql`insert into turns(key, topic_key, seq, role, status, body, rev, data)
          values (${it.key}, ${str(d.topic_key)}, ${num(d.seq)}, ${str(d.role, 'agent')},
            ${str(d.status, 'done')}, ${body}, ${rev}, ${rest}::jsonb)
          on conflict (key) do update set topic_key = excluded.topic_key, seq = excluded.seq,
            role = excluded.role, status = excluded.status, body = excluded.body, rev = excluded.rev,
            data = excluded.data, _updated_at = now()
          where turns.rev <> excluded.rev or excluded.rev = ''
          returning 1 as n`);
      }
      case 'question':
        return this.write(sql`insert into questions(key, topic_key, turn_key, state, rev, data)
          values (${it.key}, ${str(d.topic_key)}, ${str(d.turn_key) || null}, ${str(d.state, 'open')},
            ${rev}, ${json}::jsonb)
          on conflict (key) do update set topic_key = excluded.topic_key, turn_key = excluded.turn_key,
            state = excluded.state, rev = excluded.rev, data = excluded.data, _updated_at = now()
          where questions.rev <> excluded.rev or excluded.rev = ''
          returning 1 as n`);
      case 'settings':
        return this.writeSettings(it.key, rev, d);
      case 'collab':
        // v31：一次协作（docs/web.md 协作与三层记忆）。整条存进 data，读的时候按 shared/collab.ts 的 collabOf 认；
        // 汇总方和状态另存一列，话题页按“汇总方或协助方”找它
        return this.collabWrite(sql`insert into collabs(key, integrator, state, rev, data, updated_at)
          values (${it.key}, ${str(d.integrator)}, ${str(d.state, 'open')}, ${rev}, ${json}::jsonb, ${num(d.updated_at)})
          on conflict (key) do update set integrator = excluded.integrator, state = excluded.state, rev = excluded.rev,
            data = excluded.data, updated_at = excluded.updated_at, _updated_at = now()
          where collabs.rev <> excluded.rev or excluded.rev = ''
          returning 1 as n`);
      case 'login':
        return this.loginDecide(it.key, str(d.decision));
      default:
        return 0;
    }
  }

  /** 自托管（T653）：主人在飞书点了允许或拒绝。只改还没处理、没过期的请求；妙搭模式没有 login_requests 表，跳过不报错（同 collabs） */
  private async loginDecide(id: string, decision: string): Promise<number> {
    if (decision !== 'approved' && decision !== 'denied') throw new BadRequestException('login 的 decision 只能是 approved 或 denied');
    if (this.noLoginTable) return 0;
    try {
      return await this.write(sql`update login_requests set state = ${decision}, decided_at = now(), _updated_at = now()
        where id = ${id} and state = 'pending' and expires_at > now() returning 1 as n`);
    } catch (e) {
      if (!missingTable(e)) throw e;
      this.noLoginTable = true;
      this.logger.warn('login_requests 表不存在（不是自托管库）：login 条目跳过');
      return 0;
    }
  }

  /** collabs 表还没建（新网页先上、库还没迁）：这一条跳过、记一次日志，同一批别的条目照常写，Covey 那边不会整批重试 */
  private async collabWrite(query: ReturnType<typeof sql>): Promise<number> {
    try {
      return await this.write(query);
    } catch (e) {
      if (!missingTable(e)) throw e;
      if (!this.noCollabTable) this.logger.warn('collabs 表还没建：协作条目先跳过（见 collabs.sql）');
      this.noCollabTable = true;
      return 0;
    }
  }

  /** v7 设置快照、v15 本周用量、v16 整理专项建议：一行放进 sync_state（name = key，只有 settings、usage 和 tidy），rev 相同跳过 */
  private async writeSettings(name: string, rev: string, data: Record<string, unknown>): Promise<number> {
    const value: string = JSON.stringify({ rev, data, at: new Date().toISOString() });
    return this.write(sql`insert into sync_state(name, value) values (${name}, ${value}::jsonb)
      on conflict (name) do update set value = excluded.value, _updated_at = now()
      where ${rev} = '' or sync_state.value->>'rev' is distinct from ${rev}
      returning 1 as n`);
  }

  private async write(query: ReturnType<typeof sql>): Promise<number> {
    return asRows<{ n: number }>(await this.db.execute(query)).length;
  }

  private async deleteOne(type: string, key: string): Promise<number> {
    if (type === 'login') return 0;
    if (type === 'collab') return this.collabWrite(sql`delete from collabs where key = ${key} returning 1 as n`);
    const q =
      type === 'project'
        ? sql`delete from projects where key = ${key} returning 1 as n`
        : type === 'topic'
          ? sql`delete from topics where key = ${key} returning 1 as n`
          : type === 'turn'
            ? sql`delete from turns where key = ${key} returning 1 as n`
            : type === 'settings'
              ? sql`delete from sync_state where name = ${key} returning 1 as n`
              : sql`delete from questions where key = ${key} returning 1 as n`;
    return this.write(q);
  }

  private async touchSynced(): Promise<void> {
    await this.db.execute(
      sql`insert into sync_state(name, value) values ('last_sync', ${JSON.stringify({ at: new Date().toISOString() })}::jsonb)
        on conflict (name) do update set value = excluded.value, _updated_at = now()`,
    );
  }

  /**
   * 取发件箱。waitMs 不是 null（Covey 带了 wait）：没有新操作就挂着，每 200 毫秒查一次库（同进程里 POST /api/outbox 写入会提前叫醒），
   * 最多等 waitMs 毫秒，有了马上返回；响应里带 waited: true，Covey 靠它认出这个服务端支持 wait。不带 wait 时和以前完全一样。
   */
  async inbox(after: number, limit: number, waitMs: number | null = null, aborted: () => boolean = () => false): Promise<InboxResponse> {
    const fetchRows = async (): Promise<OutboxRow[]> => {
      const res = await this.db.execute(
        sql`select seq::int as seq, op_id, kind, topic_key, project_key, payload, _created_at as created_at
          from outbox where state = 'new' and seq > ${after} order by seq asc limit ${limit}`,
      );
      return asRows<OutboxRow>(res);
    };
    if (waitMs === null) return { items: await fetchRows() };
    let latest: OutboxRow[] = [];
    const items: OutboxRow[] = await waitFor<OutboxRow[]>(
      'inbox',
      waitMs,
      INBOX_STEP_MS,
      async () => {
        latest = await fetchRows();
        return latest.length ? latest : null;
      },
      () => latest,
      aborted,
    );
    return { items, waited: true };
  }

  async ack(body: SyncAckRequest): Promise<SyncAckResponse> {
    let updated = 0;
    for (const r of arr<SyncAckRequest['results'][number]>(body?.results)) {
      if (r?.state !== 'done' && r?.state !== 'failed') {
        throw new BadRequestException('state 只能是 done 或 failed');
      }
      const res = await this.db.execute(
        sql`update outbox set state = ${r.state}, message = ${str(r.message)}, acked_at = now(), _updated_at = now()
          where op_id = ${str(r.op_id)} and state = 'new' returning 1 as n`,
      );
      updated += asRows<{ n: number }>(res).length;
    }
    // 叫醒挂着等这条回执的浏览器请求（GET /api/outbox/:opId?wait=）
    if (updated > 0) wake('ack');
    return { ok: true, updated };
  }
}
