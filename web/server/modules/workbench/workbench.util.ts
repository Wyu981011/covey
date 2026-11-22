export function asRows<T>(res: unknown): T[] {
  if (Array.isArray(res)) return res as T[];
  const rows: unknown = (res as { rows?: unknown } | null)?.rows;
  return Array.isArray(rows) ? (rows as T[]) : [];
}

export function str(v: unknown, fallback = ''): string {
  return typeof v === 'string' ? v : fallback;
}

export function num(v: unknown, fallback = 0): number {
  return typeof v === 'number' && Number.isFinite(v) ? v : fallback;
}

export function arr<T>(v: unknown): T[] {
  return Array.isArray(v) ? (v as T[]) : [];
}

export function obj(v: unknown): Record<string, unknown> {
  return v && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, unknown>) : {};
}

/** 查询报“表不存在”（42P01）：新表还没在这个库里建。drizzle 可能把驱动的错包一层（cause） */
export function missingTable(e: unknown): boolean {
  const err = e as { code?: unknown; cause?: { code?: unknown } } | null;
  return err?.code === '42P01' || err?.cause?.code === '42P01';
}

export const MAX_BODY_BYTES = 64 * 1024;

/** 正文单条 ≤64 KB，超了截断并写明 */
export function clipBody(body: string): string {
  const buf: Buffer = Buffer.from(body, 'utf8');
  if (buf.length <= MAX_BODY_BYTES) return body;
  const head: string = buf.subarray(0, MAX_BODY_BYTES).toString('utf8');
  return `${head}\n\n…（正文超过 64 KB，已截断）`;
}

export function oneLine(text: string, max = 120): string {
  const flat: string = text.replace(/\s+/gu, ' ').trim();
  return flat.length > max ? `${flat.slice(0, max)}…` : flat;
}

const ENTITIES: Record<string, string> = { amp: '&', lt: '<', gt: '>', quot: '"', apos: "'", '#39': "'", '#x27': "'", '#x2F': '/', '#47': '/' };

/** 步骤说明在 Covey 的执行轨迹里是给飞书卡片转义过的（`&amp;&amp;`、`&lt;&lt;`、`&quot;`），网页按纯文字显示，
 * 要先还原一次，不然页面上看到的是 `cd … &amp;&amp; git fetch`（T550 评审 P1-10）。只还原这几个常见实体，没转义过的原样不动。 */
export function unescapeHtml(s: string): string {
  return s.includes('&') ? s.replace(/&(amp|lt|gt|quot|apos|#39|#x27|#x2F|#47);/giu, (m: string, k: string) => ENTITIES[k] ?? ENTITIES[k.toLowerCase()] ?? m) : s;
}
