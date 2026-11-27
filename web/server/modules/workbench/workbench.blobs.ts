/**
 * 图片和附件的字节放哪（T876）：妙搭文件存储，PG 只存路径和元数据；文件存储用不了（自托管、平台报错、旧库还没有路径列）时
 * 照旧放进 bytea 列。纯逻辑，不带 Nest 装饰器：平台的 FileService 由 workbench.module.ts 注入后包成 PlatformBlobs，单测换成假的。
 *
 * 鉴权和现网一致：文件不发直链给浏览器。页面仍只经 /api/images/:id（要登录、只有主人）取图，服务端拿短时签名地址自己去取字节再回给页面；
 * Covey 仍只经 /openapi/sync/upload/part 取附件。签名地址只在服务端进程里缓存（比签名的有效期短），不出进程、不进库、不写日志。
 */
export interface FileMetaLike {
  filePath?: string;
}
/** 平台 FileService（@lark-apaas/fullstack-nestjs-core）用到的那几个方法 */
export interface FileServiceLike {
  upload(file: Buffer, options?: { filePath?: string; fileName?: string; contentType?: string; upsert?: boolean }): Promise<FileMetaLike>;
  createSignedUrl(path: string, expiresIn: number): Promise<string>;
  remove(filePaths: string[]): Promise<unknown>;
}

export interface BlobStore {
  /** 存一份，回存好的路径；失败就抛（调用方退回 bytea） */
  put(path: string, data: Buffer, mime: string): Promise<string>;
  /** 取一份；没有是 null，别的错误抛 */
  get(path: string): Promise<Buffer | null>;
  remove(paths: string[]): Promise<void>;
}

/** 签名地址签多久、在进程里用多久（秒） */
export const SIGN_SECONDS = 600;
export const SIGN_REUSE_SECONDS = 480;
const SIGNED_KEPT = 2000;

type Fetch = (url: string) => Promise<{ ok: boolean; status: number; arrayBuffer: () => Promise<ArrayBuffer> }>;

export class PlatformBlobs implements BlobStore {
  private readonly signed: Map<string, { url: string; until: number }> = new Map();

  private readonly fs: FileServiceLike;
  private readonly fetchUrl: Fetch;
  private readonly now: () => number;

  constructor(fs: FileServiceLike, fetchUrl: Fetch = (u: string) => fetch(u), now: () => number = () => Date.now()) {
    this.fs = fs;
    this.fetchUrl = fetchUrl;
    this.now = now;
  }

  async put(path: string, data: Buffer, mime: string): Promise<string> {
    const name: string = path.split('/').pop() || 'blob';
    const meta: FileMetaLike = await this.fs.upload(data, { filePath: path, fileName: name, contentType: mime, upsert: true });
    const stored: string = typeof meta?.filePath === 'string' && meta.filePath ? meta.filePath : '';
    if (!stored) throw new Error('文件存储没回路径');
    this.signed.delete(stored);
    return stored;
  }

  async get(path: string): Promise<Buffer | null> {
    for (let attempt = 0; attempt < 2; attempt += 1) {
      const url: string = await this.url(path, attempt > 0);
      if (!url) return null;
      const res = await this.fetchUrl(url);
      if (res.ok) return Buffer.from(await res.arrayBuffer());
      this.signed.delete(path);
      // 签名过期（403）再签一次；404 是没有这个文件
      if (res.status === 404) return null;
      if (res.status !== 403 || attempt > 0) throw new Error(`文件存储取不到（${res.status}）`);
    }
    return null;
  }

  async remove(paths: string[]): Promise<void> {
    const list: string[] = paths.filter(Boolean);
    for (const p of list) this.signed.delete(p);
    for (let i = 0; i < list.length; i += 100) await this.fs.remove(list.slice(i, i + 100));
  }

  private async url(path: string, fresh: boolean): Promise<string> {
    const hit = this.signed.get(path);
    if (!fresh && hit && hit.until > this.now()) return hit.url;
    const url: string = await this.fs.createSignedUrl(path, SIGN_SECONDS);
    if (!url) return '';
    if (this.signed.size >= SIGNED_KEPT) this.signed.delete(this.signed.keys().next().value as string);
    this.signed.set(path, { url, until: this.now() + SIGN_REUSE_SECONDS * 1000 });
    return url;
  }
}

/**
 * 存哪的状态：文件存储能不能用、库里有没有路径列。第一次失败记一行日志，之后不刷屏；
 * 文件存储连着失败 FAIL_OFF 次就歇 OFF_MS 再试（平台临时不可用时不每次都多等一个超时），库里没有路径列就一直走 bytea。
 */
export const FAIL_OFF = 3;
export const OFF_MS = 10 * 60 * 1000;

export class BlobPlace {
  /** 库里有没有路径列（images.thumb_path 等）；null 是还不知道 */
  columns: boolean | null = null;
  private fails = 0;
  private offUntil = 0;
  private logged = new Set<string>();
  /** 观测：存进文件存储、退回 bytea 各多少份 */
  stored = 0;
  fellBack = 0;

  readonly store: BlobStore | null;
  private readonly log: (msg: string) => void;
  private readonly now: () => number;

  constructor(store: BlobStore | null, log: (msg: string) => void = () => undefined, now: () => number = () => Date.now()) {
    this.store = store;
    this.log = log;
    this.now = now;
  }

  /** 这会儿新写的该放文件存储吗 */
  usable(): boolean {
    return !!this.store && this.columns !== false && this.now() >= this.offUntil;
  }

  /** limits.store */
  get mode(): 'file' | 'db' {
    return this.usable() && this.fails === 0 ? 'file' : 'db';
  }

  ok(): void {
    this.fails = 0;
    this.stored += 1;
  }

  failed(what: string, e: unknown): void {
    this.fails += 1;
    this.fellBack += 1;
    if (this.fails >= FAIL_OFF) this.offUntil = this.now() + OFF_MS;
    const msg: string = e instanceof Error ? e.message : String(e);
    const key: string = `${what}:${msg.slice(0, 60)}`;
    if (!this.logged.has(key) && this.logged.size < 50) {
      this.logged.add(key);
      this.log(`[workbench] 文件存储${what}失败，这一份退回库里（${msg.slice(0, 200)}）`);
    }
  }

  noColumns(): void {
    if (this.columns !== false) this.log('[workbench] 库里还没有文件存储的路径列（见 web/deploy/miaoda/migrations/），图片和附件照旧存库里');
    this.columns = false;
  }
}

/** 查询报“列不存在”（42703）：库还没迁到有路径列的版本 */
export function missingColumn(e: unknown): boolean {
  const err = e as { code?: unknown; cause?: { code?: unknown } } | null;
  return err?.code === '42703' || err?.cause?.code === '42703';
}

/** 文件存储里的路径：前缀分图片和附件，id 是内容哈希或随机编号，不含主人的任何信息 */
export const imagePath = (id: string, v: 'thumb' | 'full', mime: string): string => `covey/images/${id}-${v}.${extOf(mime)}`;
export const partPath = (id: string, n: number): string => `covey/uploads/${id}/${n}.part`;

function extOf(mime: string): string {
  return ({ 'image/webp': 'webp', 'image/png': 'png', 'image/jpeg': 'jpg', 'image/gif': 'gif' } as Record<string, string>)[mime] ?? 'bin';
}
