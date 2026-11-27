import { Injectable, Inject, BadRequestException, ServiceUnavailableException } from '@nestjs/common';
import type { PostgresJsDatabase } from '@lark-apaas/fullstack-nestjs-core';
import { sql } from 'drizzle-orm';
import type { ImageHaveRequest, ImageHaveResponse, ImageUploadRequest } from '@shared/api.interface';
import { arr, asRows, num, str } from './workbench.util';
import { BlobPlace, imagePath, missingColumn } from './workbench.blobs';
import { memory } from './workbench.guard';
import { imageBytes } from './workbench.limits';
import { IMAGE_BLOBS, WB_DB } from './workbench.tokens';

/** 一轮的图片（Covey 数据约定 v19，T582）：Covey 经 /openapi 传上来，页面只经 /api/images/:id 取（要登录、只有主人）。
 *  不发签名直链给页面、不放公开存储；过期（消息之后 90 天）的每小时清一次。
 *  v44（T876）：字节放妙搭文件存储，images 表只存路径（thumb_path、full_path）和元数据；文件存储用不了、库还没有路径列时照旧放 bytea。
 *  老的 bytea 行照常读；有路径也有 bytea 的（回迁复制过、还没清）先读文件存储，取不到再读 bytea。 */
const ID = /^[0-9a-f]{16,64}$/u;
const MIMES: readonly string[] = ['image/webp', 'image/png', 'image/jpeg', 'image/gif'];
/** 一份图片的字节上限：请求体上限推出来（workbench.limits.ts），1 MiB 的旧上限下是 760 KB */
export const MAX_IMAGE_BYTES = imageBytes();
const HAVE_MAX = 200;
const SWEEP_MS = 3600 * 1000;
/** 回迁一次最多搬几行（每行两份） */
export const BACKFILL_MAX = 50;

export interface StoredImage {
  mime: string;
  data: Buffer;
}

interface ImageRow {
  mime: string;
  path: string | null;
  data: string | null;
}

@Injectable()
export class WorkbenchImagesService {
  private swept = 0;

  constructor(
    @Inject(WB_DB) private readonly db: PostgresJsDatabase,
    @Inject(IMAGE_BLOBS) private readonly blobs: BlobPlace,
  ) {}

  /** Covey 传一份（thumb 或 full）；同一个 id 再传就覆盖那一份 */
  async upload(body: ImageUploadRequest): Promise<{ ok: true }> {
    const id: string = str(body?.id);
    const v: string = str(body?.v);
    const mime: string = str(body?.mime);
    if (!ID.test(id)) throw new BadRequestException('id 要是 16–64 位十六进制');
    if (v !== 'thumb' && v !== 'full') throw new BadRequestException('v 只能是 thumb 或 full');
    if (!MIMES.includes(mime)) throw new BadRequestException('只收 webp、png、jpeg、gif');
    if (memory.pressure() !== 'ok') throw new ServiceUnavailableException('服务端内存紧张，稍后再传');
    const data: Buffer = Buffer.from(str(body?.data), 'base64');
    if (!data.length) throw new BadRequestException('data 为空');
    if (data.length > MAX_IMAGE_BYTES) throw new BadRequestException('图片太大');
    const w: number = Math.max(0, Math.floor(num(body?.w)));
    const h: number = Math.max(0, Math.floor(num(body?.h)));
    const expires: number = num(body?.expires_at);
    if (!expires) throw new BadRequestException('要有 expires_at（秒）');
    const at: string = new Date(expires * 1000).toISOString();
    const path: string | null = await this.store(id, v, mime, data);
    if (path !== null && (await this.writePath(id, v, mime, w, h, path, at))) {
      await this.sweep();
      return { ok: true };
    }
    // 现网的库连接把 Buffer 参数当文字传（bytea 列报 42804），所以按 base64 文字传、在库里 decode
    const b64: string = data.toString('base64');
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

  /** 存进文件存储，回路径；不该或不能存（自托管、库没有路径列、平台报错）是 null，调用方存 bytea */
  private async store(id: string, v: 'thumb' | 'full', mime: string, data: Buffer): Promise<string | null> {
    if (!this.blobs.usable() || !this.blobs.store) return null;
    try {
      const path: string = await this.blobs.store.put(imagePath(id, v, mime), data, mime);
      this.blobs.ok();
      return path;
    } catch (e) {
      this.blobs.failed('存图', e);
      return null;
    }
  }

  /** 路径写进库；这一份原来的 bytea 清掉（同一份的新字节在文件存储里）。库还没有路径列回 false */
  private async writePath(id: string, v: 'thumb' | 'full', mime: string, w: number, h: number, path: string, at: string): Promise<boolean> {
    try {
      if (v === 'thumb') {
        await this.db.execute(sql`insert into images(id, mime, w, h, thumb_path, expires_at) values (${id}, ${mime}, ${w}, ${h}, ${path}, ${at})
          on conflict (id) do update set mime = excluded.mime, w = excluded.w, h = excluded.h, thumb_path = excluded.thumb_path, thumb_data = null,
            expires_at = greatest(images.expires_at, excluded.expires_at), _updated_at = now()`);
      } else {
        await this.db.execute(sql`insert into images(id, mime, w, h, full_path, expires_at) values (${id}, ${mime}, ${w}, ${h}, ${path}, ${at})
          on conflict (id) do update set mime = excluded.mime, w = excluded.w, h = excluded.h, full_path = excluded.full_path, full_data = null,
            expires_at = greatest(images.expires_at, excluded.expires_at), _updated_at = now()`);
      }
      this.blobs.columns = true;
      return true;
    } catch (e) {
      if (!missingColumn(e)) throw e;
      this.blobs.noColumns();
      // 刚存进文件存储的那份没人引用了，删掉（删不掉也不影响这次退回 bytea）
      await this.blobs.store?.remove([path]).catch(() => undefined);
      return false;
    }
  }

  /** 哪些 id 两份都有了（Covey 传之前问一次，有的不再传） */
  async have(body: ImageHaveRequest): Promise<ImageHaveResponse> {
    const ids: string[] = arr<unknown>(body?.ids).map((x: unknown) => str(x)).filter((x: string) => ID.test(x)).slice(0, HAVE_MAX);
    if (!ids.length) return { have: [] };
    const list = sql.join(ids.map((x: string) => sql`${x}`), sql`, `);
    const res = await this.withColumns(
      () => this.db.execute(sql`select id from images where id in (${list})
        and (thumb_data is not null or thumb_path is not null) and (full_data is not null or full_path is not null) and expires_at > now()`),
      () => this.db.execute(sql`select id from images where id in (${list})
        and thumb_data is not null and full_data is not null and expires_at > now()`),
    );
    return { have: asRows<{ id: string }>(res).map((r: { id: string }) => r.id) };
  }

  /** 页面取一份；没有、过期了都是 null（控制器回 404，页面画“已过期”） */
  async get(id: string, v: 'thumb' | 'full'): Promise<StoredImage | null> {
    if (!ID.test(id)) return null;
    const res = await this.withColumns(
      () => this.db.execute(
        v === 'thumb'
          ? sql`select mime, thumb_path as path, case when thumb_path is null then encode(thumb_data, 'base64') end as data
              from images where id = ${id} and expires_at > now()`
          : sql`select mime, coalesce(full_path, case when full_data is null then thumb_path end) as path,
              case when full_path is null then encode(coalesce(full_data, case when thumb_path is null then thumb_data end), 'base64') end as data
              from images where id = ${id} and expires_at > now()`,
      ),
      () => this.db.execute(
        v === 'thumb'
          ? sql`select mime, null as path, encode(thumb_data, 'base64') as data from images where id = ${id} and expires_at > now()`
          : sql`select mime, null as path, encode(coalesce(full_data, thumb_data), 'base64') as data from images where id = ${id} and expires_at > now()`,
      ),
    );
    const row: ImageRow | undefined = asRows<ImageRow>(res)[0];
    if (!row) return null;
    const mime: string = MIMES.includes(row.mime) ? row.mime : 'application/octet-stream';
    if (row.path) {
      const got: Buffer | null = await this.fetchBlob(row.path);
      if (got) return { mime, data: got };
      // 文件存储取不到：回迁复制过的行 bytea 还在，再读一次 bytea
      const old = asRows<{ data: string | null }>(await this.db.execute(
        v === 'thumb'
          ? sql`select encode(thumb_data, 'base64') as data from images where id = ${id}`
          : sql`select encode(coalesce(full_data, thumb_data), 'base64') as data from images where id = ${id}`,
      ))[0];
      return old?.data ? { mime, data: decode64(old.data) } : null;
    }
    return row.data ? { mime, data: decode64(row.data) } : null;
  }

  private async fetchBlob(path: string): Promise<Buffer | null> {
    if (!this.blobs.store) return null;
    try {
      return await this.blobs.store.get(path);
    } catch (e) {
      this.blobs.failed('取图', e);
      return null;
    }
  }

  /**
   * 历史回迁（T876，只经开放接口手动触发，不自动跑）：把还只在 bytea 里的图搬进文件存储，一次最多 limit 行。
   * drop=false（默认）只复制：写上路径、bytea 留着，页面先读文件存储、取不到再读 bytea，不会丢；drop=true 才在复制并读回核对大小以后清掉 bytea。
   * 回 搬了几份、清了几份、还剩几行、出错几份。
   */
  async backfill(limit: number, drop: boolean): Promise<{ copied: number; dropped: number; left: number; errors: number; store: 'file' | 'db' }> {
    const out = { copied: 0, dropped: 0, left: 0, errors: 0, store: this.blobs.mode };
    if (!this.blobs.store || !this.blobs.usable()) return out;
    const n: number = Math.min(BACKFILL_MAX, Math.max(1, Math.floor(limit) || 1));
    const rows = asRows<{ id: string; mime: string; thumb: string | null; full: string | null; tp: string | null; fp: string | null }>(
      await this.withColumns(
        () => this.db.execute(sql`select id, mime, encode(thumb_data, 'base64') as thumb, encode(full_data, 'base64') as full,
          thumb_path as tp, full_path as fp from images where expires_at > now()
          and ((thumb_data is not null and (thumb_path is null or ${drop})) or (full_data is not null and (full_path is null or ${drop})))
          order by _created_at asc limit ${n}`),
        () => Promise.resolve([]),
      ),
    );
    for (const r of rows) {
      for (const v of ['thumb', 'full'] as const) {
        const b64: string | null = v === 'thumb' ? r.thumb : r.full;
        if (!b64) continue;
        const data: Buffer = decode64(b64);
        try {
          let path: string | null = v === 'thumb' ? r.tp : r.fp;
          if (!path) {
            path = await this.blobs.store.put(imagePath(r.id, v, r.mime), data, r.mime);
            await this.db.execute(v === 'thumb'
              ? sql`update images set thumb_path = ${path}, _updated_at = now() where id = ${r.id} and thumb_path is null`
              : sql`update images set full_path = ${path}, _updated_at = now() where id = ${r.id} and full_path is null`);
            out.copied += 1;
          }
          if (drop) {
            const back: Buffer | null = await this.blobs.store.get(path);
            if (!back || back.length !== data.length) throw new Error('读回的大小对不上');
            await this.db.execute(v === 'thumb'
              ? sql`update images set thumb_data = null, _updated_at = now() where id = ${r.id} and thumb_path = ${path}`
              : sql`update images set full_data = null, _updated_at = now() where id = ${r.id} and full_path = ${path}`);
            out.dropped += 1;
          }
        } catch (e) {
          out.errors += 1;
          this.blobs.failed('回迁', e);
        }
      }
    }
    const left = asRows<{ n: number }>(await this.withColumns(
      () => this.db.execute(sql`select count(*)::int as n from images where expires_at > now()
        and ((thumb_data is not null and thumb_path is null) or (full_data is not null and full_path is null))`),
      () => this.db.execute(sql`select count(*)::int as n from images where expires_at > now()`),
    ))[0];
    out.left = num(left?.n);
    return out;
  }

  /** 先按有路径列的写法查；库还没迁（列不存在）就记下、改用老写法 */
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

  /** 过期的删掉：每小时最多一次，跟着上传做。文件存储里的先删（删不掉的下次再删），再删行 */
  private async sweep(): Promise<void> {
    const now: number = Date.now();
    if (now - this.swept < SWEEP_MS) return;
    this.swept = now;
    if (this.blobs.store && this.blobs.columns !== false) {
      const gone = asRows<{ id: string; tp: string | null; fp: string | null }>(await this.withColumns(
        () => this.db.execute(sql`select id, thumb_path as tp, full_path as fp from images where expires_at < now() and (thumb_path is not null or full_path is not null) limit 500`),
        () => Promise.resolve([]),
      ));
      const paths: string[] = gone.flatMap((r) => [r.tp, r.fp]).filter((p): p is string => !!p);
      let removed: string[] = [];
      if (paths.length) {
        try {
          await this.blobs.store.remove(paths);
          removed = gone.map((r) => r.id);
        } catch (e) {
          this.blobs.failed('清过期图', e);
        }
      }
      // 只删没有文件的行和文件已删掉的行；文件没删掉的（或这一轮没轮到的）留到下一轮，不留下没人引用的文件
      const ids = removed.length ? sql` or id in (${sql.join(removed.map((x: string) => sql`${x}`), sql`, `)})` : sql``;
      await this.db.execute(sql`delete from images where expires_at < now() and ((thumb_path is null and full_path is null)${ids})`);
      return;
    }
    await this.db.execute(sql`delete from images where expires_at < now()`);
  }
}

/** encode() 每 76 个字符换一行 */
function decode64(b64: string): Buffer {
  return Buffer.from(b64.replace(/\s+/gu, ''), 'base64');
}
