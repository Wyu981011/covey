import { Injectable, Inject, BadRequestException } from '@nestjs/common';
import { DRIZZLE_DATABASE, type PostgresJsDatabase } from '@lark-apaas/fullstack-nestjs-core';
import { sql } from 'drizzle-orm';
import type { ImageHaveRequest, ImageHaveResponse, ImageUploadRequest } from '@shared/api.interface';
import { arr, asRows, num, str } from './workbench.util';

/** 一轮的图片（Covey 数据约定 v19，T582）：Covey 经 /openapi 传上来，存在本应用库的 images 表（缩略图、大图各一份），
 *  页面只经 /api/images/:id 取（要登录、只有主人）。不发签名直链、不放公开存储；过期（消息之后 90 天）的每小时清一次。 */
const ID = /^[0-9a-f]{16,64}$/u;
const MIMES: readonly string[] = ['image/webp', 'image/png', 'image/jpeg', 'image/gif'];
/** 一份图片的字节上限：Covey 压到 700 KB 以内，base64 之后整个请求在 1 MiB 内 */
export const MAX_IMAGE_BYTES = 760 * 1024;
const HAVE_MAX = 200;
const SWEEP_MS = 3600 * 1000;

export interface StoredImage {
  mime: string;
  data: Buffer;
}

@Injectable()
export class WorkbenchImagesService {
  private swept = 0;

  constructor(@Inject(DRIZZLE_DATABASE) private readonly db: PostgresJsDatabase) {}

  /** Covey 传一份（thumb 或 full）；同一个 id 再传就覆盖那一份 */
  async upload(body: ImageUploadRequest): Promise<{ ok: true }> {
    const id: string = str(body?.id);
    const v: string = str(body?.v);
    const mime: string = str(body?.mime);
    if (!ID.test(id)) throw new BadRequestException('id 要是 16–64 位十六进制');
    if (v !== 'thumb' && v !== 'full') throw new BadRequestException('v 只能是 thumb 或 full');
    if (!MIMES.includes(mime)) throw new BadRequestException('只收 webp、png、jpeg、gif');
    const data: Buffer = Buffer.from(str(body?.data), 'base64');
    if (!data.length) throw new BadRequestException('data 为空');
    if (data.length > MAX_IMAGE_BYTES) throw new BadRequestException('图片太大');
    // 现网的库连接把 Buffer 参数当文字传（bytea 列报 42804），所以按 base64 文字传、在库里 decode
    const b64: string = data.toString('base64');
    const w: number = Math.max(0, Math.floor(num(body?.w)));
    const h: number = Math.max(0, Math.floor(num(body?.h)));
    const expires: number = num(body?.expires_at);
    if (!expires) throw new BadRequestException('要有 expires_at（秒）');
    const at: string = new Date(expires * 1000).toISOString();
    if (v === 'thumb') {
      await this.db.execute(sql`insert into images(id, mime, w, h, thumb_data, expires_at) values (${id}, ${mime}, ${w}, ${h}, decode(${b64}, 'base64'), ${at})
        on conflict (id) do update set mime = excluded.mime, w = excluded.w, h = excluded.h, thumb_data = excluded.thumb_data,
          expires_at = greatest(images.expires_at, excluded.expires_at), _updated_at = now()`);
    } else {
      await this.db.execute(sql`insert into images(id, mime, w, h, full_data, expires_at) values (${id}, ${mime}, ${w}, ${h}, decode(${b64}, 'base64'), ${at})
        on conflict (id) do update set mime = excluded.mime, w = excluded.w, h = excluded.h, full_data = excluded.full_data,
          expires_at = greatest(images.expires_at, excluded.expires_at), _updated_at = now()`);
    }
    await this.sweep();
    return { ok: true };
  }

  /** 哪些 id 两份都有了（Covey 传之前问一次，有的不再传） */
  async have(body: ImageHaveRequest): Promise<ImageHaveResponse> {
    const ids: string[] = arr<unknown>(body?.ids).map((x: unknown) => str(x)).filter((x: string) => ID.test(x)).slice(0, HAVE_MAX);
    if (!ids.length) return { have: [] };
    const res = await this.db.execute(sql`select id from images where id in (${sql.join(ids.map((x: string) => sql`${x}`), sql`, `)})
      and thumb_data is not null and full_data is not null and expires_at > now()`);
    return { have: asRows<{ id: string }>(res).map((r: { id: string }) => r.id) };
  }

  /** 页面取一份；没有、过期了都是 null（控制器回 404，页面画“已过期”） */
  async get(id: string, v: 'thumb' | 'full'): Promise<StoredImage | null> {
    if (!ID.test(id)) return null;
    const res = await this.db.execute(
      v === 'thumb'
        ? sql`select mime, encode(thumb_data, 'base64') as data from images where id = ${id} and expires_at > now()`
        : sql`select mime, encode(coalesce(full_data, thumb_data), 'base64') as data from images where id = ${id} and expires_at > now()`,
    );
    const row = asRows<{ mime: string; data: string | null }>(res)[0];
    if (!row?.data) return null;
    const data: Buffer = Buffer.from(row.data.replace(/\s+/gu, ''), 'base64');  // encode() 每 76 个字符换一行
    return { mime: MIMES.includes(row.mime) ? row.mime : 'application/octet-stream', data };
  }

  /** 过期的删掉：每小时最多一次，跟着上传做 */
  private async sweep(): Promise<void> {
    const now: number = Date.now();
    if (now - this.swept < SWEEP_MS) return;
    this.swept = now;
    await this.db.execute(sql`delete from images where expires_at < now()`);
  }
}
