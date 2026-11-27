import { Injectable, Inject, BadRequestException, NotFoundException, ServiceUnavailableException } from '@nestjs/common';
import type { PostgresJsDatabase } from '@lark-apaas/fullstack-nestjs-core';
import { sql } from 'drizzle-orm';
import { randomBytes } from 'crypto';
import {
  UPLOAD_MAX_BYTES,
  type OpenUploadInfo,
  type OpenUploadPart,
  type UploadDoneResponse,
  type UploadPartRequest,
  type UploadStartRequest,
  type UploadStartResponse,
} from '@shared/api.interface';
import { asRows, num, str } from './workbench.util';
import { BlobPlace, missingColumn, partPath } from './workbench.blobs';
import { memory } from './workbench.guard';
import { partBytes } from './workbench.limits';
import { UPLOAD_BLOBS, WB_DB } from './workbench.tokens';

/** 输入框的附件（Covey 数据约定 v20，T616）：页面经 /api/uploads 分段传进来（uploads、upload_parts 两张表），
 *  say 里只带编号；Covey 执行 say 时经 /openapi/sync/upload 取回，存进话题的 incoming_media。
 *  单个文件 ≤ 20 MB，传完 7 天后过期，每小时跟着上传清一次（文件存储里的也一起删）。
 *  v44（T876）：每段原始字节由请求体上限推出来（workbench.limits.ts 的 partBytes，8mb 时 4 MiB；1 MiB 的旧上限下 512 KiB），
 *  start 的响应带 part_bytes，页面照它切；段的字节放妙搭文件存储，upload_parts 只存路径和字节数（path、bytes）。
 *  文件存储用不了、库还没有这两列时照旧放 bytea（按 base64 文字进出库：现网连接把 Buffer 参数当文字传，bytea 列报 42804）。 */
const ID = /^[0-9a-f]{32}$/u;
const TTL_MS = 7 * 24 * 3600 * 1000;
const SWEEP_MS = 3600 * 1000;
/** 这个服务端每段收多少原始字节 */
export const PART_BYTES = partBytes();

/** 文件名只留最后一段，去掉控制字符，最多 200 字 */
export function cleanName(v: unknown): string {
  // eslint-disable-next-line no-control-regex
  const base: string = str(v).split(/[\\/]/u).pop()?.replace(/[\u0000-\u001f\u007f]/gu, '').trim() ?? '';
  return Array.from(base).slice(0, 200).join('');
}

interface UploadRow {
  id: string;
  name: string;
  mime: string;
  size: number | string;
  parts: number;
  done: boolean;
}

@Injectable()
export class WorkbenchUploadsService {
  private swept = 0;

  constructor(
    @Inject(WB_DB) private readonly db: PostgresJsDatabase,
    @Inject(UPLOAD_BLOBS) private readonly blobs: BlobPlace,
  ) {}

  /** 开一个上传：回编号、要传几段、每段多大 */
  async start(body: UploadStartRequest): Promise<UploadStartResponse> {
    const name: string = cleanName(body?.name);
    const mime: string = str(body?.mime).slice(0, 128) || 'application/octet-stream';
    const size: number = Math.floor(num(body?.size));
    if (!name) throw new BadRequestException('文件名不能为空');
    if (size <= 0) throw new BadRequestException('文件是空的');
    if (size > UPLOAD_MAX_BYTES) throw new BadRequestException(`文件超过 ${UPLOAD_MAX_BYTES / 1024 / 1024} MB`);
    if (memory.pressure() !== 'ok') throw new ServiceUnavailableException('服务端内存紧张，稍后再传');
    const id: string = randomBytes(16).toString('hex');
    const parts: number = Math.ceil(size / PART_BYTES);
    const at: string = new Date(Date.now() + TTL_MS).toISOString();
    await this.db.execute(sql`insert into uploads(id, name, mime, size, parts, done, expires_at)
      values (${id}, ${name}, ${mime}, ${size}, ${parts}, false, ${at})`);
    await this.sweep();
    return { id, parts, part_bytes: PART_BYTES };
  }

  /** 第 n 段；同一段再传就覆盖 */
  async part(id: string, body: UploadPartRequest): Promise<{ ok: true }> {
    const up: UploadRow = await this.row(id);
    if (up.done) throw new BadRequestException('这个附件已经传完了');
    const n: number = num(body?.n, -1);
    if (!Number.isInteger(n) || n < 0 || n >= up.parts) throw new BadRequestException('段号不对');
    if (memory.pressure() === 'critical') throw new ServiceUnavailableException('服务端内存紧张，稍后再传');
    const data: Buffer = Buffer.from(str(body?.data), 'base64');
    if (!data.length) throw new BadRequestException('这一段是空的');
    if (data.length > PART_BYTES) throw new BadRequestException('这一段太大');
    if (this.blobs.usable() && this.blobs.store) {
      let path: string | null = null;
      try {
        path = await this.blobs.store.put(partPath(id, n), data, 'application/octet-stream');
        this.blobs.ok();
      } catch (e) {
        this.blobs.failed('存附件', e);
      }
      if (path !== null) {
        try {
          await this.db.execute(sql`insert into upload_parts(upload_id, n, data, path, bytes) values (${id}, ${n}, null, ${path}, ${data.length})
            on conflict (upload_id, n) do update set data = null, path = excluded.path, bytes = excluded.bytes, _updated_at = now()`);
          this.blobs.columns = true;
          return { ok: true };
        } catch (e) {
          if (!missingColumn(e)) throw e;
          this.blobs.noColumns();
          await this.blobs.store.remove([path]).catch(() => undefined);
        }
      }
    }
    await this.withColumns(
      () => this.db.execute(sql`insert into upload_parts(upload_id, n, data, path, bytes) values (${id}, ${n}, decode(${data.toString('base64')}, 'base64'), null, ${data.length})
        on conflict (upload_id, n) do update set data = excluded.data, path = null, bytes = excluded.bytes, _updated_at = now()`),
      () => this.db.execute(sql`insert into upload_parts(upload_id, n, data) values (${id}, ${n}, decode(${data.toString('base64')}, 'base64'))
        on conflict (upload_id, n) do update set data = excluded.data, _updated_at = now()`),
    );
    return { ok: true };
  }

  /** 段齐了、总字节等于开始时说的大小才算传完 */
  async done(id: string): Promise<UploadDoneResponse> {
    const up: UploadRow = await this.row(id);
    const got = asRows<{ n: number; bytes: number | string }>(await this.withColumns(
      () => this.db.execute(sql`select count(*)::int as n, coalesce(sum(coalesce(bytes, length(data))), 0)::bigint as bytes from upload_parts where upload_id = ${id}`),
      () => this.db.execute(sql`select count(*)::int as n, coalesce(sum(length(data)), 0)::bigint as bytes from upload_parts where upload_id = ${id}`),
    ))[0];
    if (num(got?.n) !== up.parts) throw new BadRequestException(`还差 ${up.parts - num(got?.n)} 段没传`);
    if (Number(got?.bytes ?? 0) !== Number(up.size)) throw new BadRequestException('传上来的大小和文件对不上，重传一次');
    if (!up.done) await this.db.execute(sql`update uploads set done = true, _updated_at = now() where id = ${id}`);
    return { id, name: up.name, mime: up.mime, size: Number(up.size) };
  }

  /** Covey 取：传完、没过期的才给 */
  async info(id: string): Promise<OpenUploadInfo> {
    const up: UploadRow = await this.row(id);
    if (!up.done) throw new NotFoundException('附件还没传完');
    return { id, name: up.name, mime: up.mime, size: Number(up.size), parts: up.parts, done: true };
  }

  async getPart(id: string, n: number): Promise<OpenUploadPart> {
    const up: UploadRow = await this.row(id);
    if (!up.done) throw new NotFoundException('附件还没传完');
    if (!Number.isInteger(n) || n < 0 || n >= up.parts) throw new NotFoundException('没有这一段');
    const row = asRows<{ data: string | null; path: string | null }>(await this.withColumns(
      () => this.db.execute(sql`select case when path is null then encode(data, 'base64') end as data, path from upload_parts where upload_id = ${id} and n = ${n}`),
      () => this.db.execute(sql`select encode(data, 'base64') as data, null as path from upload_parts where upload_id = ${id} and n = ${n}`),
    ))[0];
    if (row?.path && this.blobs.store) {
      let got: Buffer | null = null;
      try {
        got = await this.blobs.store.get(row.path);
      } catch (e) {
        this.blobs.failed('取附件', e);
        throw new ServiceUnavailableException('附件暂时取不到，稍后再试');
      }
      if (got) return { n, data: got.toString('base64') };
      throw new NotFoundException('没有这一段');
    }
    if (!row?.data) throw new NotFoundException('没有这一段');
    return { n, data: row.data.replace(/\s+/gu, '') }; // encode() 每 76 个字符换一行
  }

  /** 没有、过期了都是 404 */
  private async row(id: string): Promise<UploadRow> {
    if (!ID.test(str(id))) throw new NotFoundException('没有这个附件');
    const up: UploadRow | undefined = asRows<UploadRow>(
      await this.db.execute(sql`select id, name, mime, size, parts, done from uploads where id = ${id} and expires_at > now()`),
    )[0];
    if (!up) throw new NotFoundException('附件不存在或已过期');
    return up;
  }

  private async withColumns<T>(withCols: () => Promise<T>, without: () => Promise<T>): Promise<T> {
    if (this.blobs.columns === false) return without();
    try {
      const r: T = await withCols();
      this.blobs.columns = true;
      return r;
    } catch (e) {
      if (!missingColumn(e)) throw e;
      this.blobs.noColumns();
      return without();
    }
  }

  /** 过期的删掉：每小时最多一次，跟着开上传做。文件存储里的段先删（删不掉的下次再删），再删段和附件（段跟着外键一起删，这里也显式删一次） */
  private async sweep(): Promise<void> {
    const now: number = Date.now();
    if (now - this.swept < SWEEP_MS) return;
    this.swept = now;
    if (this.blobs.store && this.blobs.columns !== false) {
      const gone = asRows<{ upload_id: string; path: string }>(await this.withColumns(
        () => this.db.execute(sql`select p.upload_id, p.path from upload_parts p join uploads u on u.id = p.upload_id
          where u.expires_at < now() and p.path is not null order by p.upload_id limit 1000`),
        () => Promise.resolve([]),
      ));
      if (gone.length) {
        try {
          await this.blobs.store.remove(gone.map((r) => r.path));
        } catch (e) {
          this.blobs.failed('清过期附件', e);
          return; // 文件没删掉：行先留着，下一轮再删，不留下没人引用的文件
        }
        // 删掉了文件的段把路径清掉；还有路径的（这一轮没轮到）的附件留到下一轮
        await this.db.execute(sql`update upload_parts set path = null where path in (${sql.join(gone.map((r) => sql`${r.path}`), sql`, `)})`);
        await this.db.execute(sql`delete from upload_parts where upload_id in (select id from uploads where expires_at < now())
          and upload_id not in (select upload_id from upload_parts where path is not null)`);
        await this.db.execute(sql`delete from uploads where expires_at < now() and id not in (select upload_id from upload_parts)`);
        return;
      }
    }
    await this.db.execute(sql`delete from upload_parts where upload_id in (select id from uploads where expires_at < now())`);
    await this.db.execute(sql`delete from uploads where expires_at < now()`);
  }
}
