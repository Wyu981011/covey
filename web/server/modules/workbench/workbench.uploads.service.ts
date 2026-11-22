import { Injectable, Inject, BadRequestException, NotFoundException } from '@nestjs/common';
import { DRIZZLE_DATABASE, type PostgresJsDatabase } from '@lark-apaas/fullstack-nestjs-core';
import { sql } from 'drizzle-orm';
import { randomBytes } from 'crypto';
import {
  UPLOAD_MAX_BYTES,
  UPLOAD_PART_BYTES,
  type OpenUploadInfo,
  type OpenUploadPart,
  type UploadDoneResponse,
  type UploadPartRequest,
  type UploadStartRequest,
  type UploadStartResponse,
} from '@shared/api.interface';
import { asRows, num, str } from './workbench.util';

/** 输入框的附件（Covey 数据约定 v20，T616）：页面经 /api/uploads 分段传进本应用库（uploads、upload_parts 两张表），
 *  say 里只带编号；Covey 执行 say 时经 /openapi/sync/upload 取回，存进话题的 incoming_media。
 *  每段原始字节 ≤ 512 KiB（base64 后整个请求在 1 MiB 的请求体上限内），单个文件 ≤ 20 MB，传完 7 天后过期，每小时跟着上传清一次。
 *  和图片表一样按 base64 文字进出库（现网连接把 Buffer 参数当文字传，bytea 列报 42804）。 */
const ID = /^[0-9a-f]{32}$/u;
const TTL_MS = 7 * 24 * 3600 * 1000;
const SWEEP_MS = 3600 * 1000;

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

  constructor(@Inject(DRIZZLE_DATABASE) private readonly db: PostgresJsDatabase) {}

  /** 开一个上传：回编号和要传几段 */
  async start(body: UploadStartRequest): Promise<UploadStartResponse> {
    const name: string = cleanName(body?.name);
    const mime: string = str(body?.mime).slice(0, 128) || 'application/octet-stream';
    const size: number = Math.floor(num(body?.size));
    if (!name) throw new BadRequestException('文件名不能为空');
    if (size <= 0) throw new BadRequestException('文件是空的');
    if (size > UPLOAD_MAX_BYTES) throw new BadRequestException(`文件超过 ${UPLOAD_MAX_BYTES / 1024 / 1024} MB`);
    const id: string = randomBytes(16).toString('hex');
    const parts: number = Math.ceil(size / UPLOAD_PART_BYTES);
    const at: string = new Date(Date.now() + TTL_MS).toISOString();
    await this.db.execute(sql`insert into uploads(id, name, mime, size, parts, done, expires_at)
      values (${id}, ${name}, ${mime}, ${size}, ${parts}, false, ${at})`);
    await this.sweep();
    return { id, parts };
  }

  /** 第 n 段；同一段再传就覆盖 */
  async part(id: string, body: UploadPartRequest): Promise<{ ok: true }> {
    const up: UploadRow = await this.row(id);
    if (up.done) throw new BadRequestException('这个附件已经传完了');
    const n: number = num(body?.n, -1);
    if (!Number.isInteger(n) || n < 0 || n >= up.parts) throw new BadRequestException('段号不对');
    const data: Buffer = Buffer.from(str(body?.data), 'base64');
    if (!data.length) throw new BadRequestException('这一段是空的');
    if (data.length > UPLOAD_PART_BYTES) throw new BadRequestException('这一段太大');
    await this.db.execute(sql`insert into upload_parts(upload_id, n, data) values (${id}, ${n}, decode(${data.toString('base64')}, 'base64'))
      on conflict (upload_id, n) do update set data = excluded.data, _updated_at = now()`);
    return { ok: true };
  }

  /** 段齐了、总字节等于开始时说的大小才算传完 */
  async done(id: string): Promise<UploadDoneResponse> {
    const up: UploadRow = await this.row(id);
    const got = asRows<{ n: number; bytes: number | string }>(
      await this.db.execute(sql`select count(*)::int as n, coalesce(sum(length(data)), 0)::bigint as bytes from upload_parts where upload_id = ${id}`),
    )[0];
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
    const row = asRows<{ data: string | null }>(
      await this.db.execute(sql`select encode(data, 'base64') as data from upload_parts where upload_id = ${id} and n = ${n}`),
    )[0];
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

  /** 过期的删掉：每小时最多一次，跟着开上传做（段跟着外键一起删，这里也显式删一次） */
  private async sweep(): Promise<void> {
    const now: number = Date.now();
    if (now - this.swept < SWEEP_MS) return;
    this.swept = now;
    await this.db.execute(sql`delete from upload_parts where upload_id in (select id from uploads where expires_at < now())`);
    await this.db.execute(sql`delete from uploads where expires_at < now()`);
  }
}
