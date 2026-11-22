const TZ = 'Asia/Shanghai';

/** 接受秒级时间戳、毫秒时间戳或 ISO 字符串 */
export function toDate(v: number | string | null | undefined): Date | null {
  if (v === null || v === undefined || v === '') return null;
  if (typeof v === 'number') {
    if (v <= 0) return null;
    return new Date(v < 1e12 ? v * 1000 : v);
  }
  const d: Date = new Date(v);
  return Number.isNaN(d.getTime()) ? null : d;
}

export function clock(v: number | string | null | undefined): string {
  const d: Date | null = toDate(v);
  if (!d) return '';
  return d.toLocaleTimeString('zh-CN', { hour12: false, timeZone: TZ });
}

export function shortTime(v: number | string | null | undefined): string {
  const d: Date | null = toDate(v);
  if (!d) return '';
  const day: string = d.toLocaleDateString('zh-CN', { month: 'numeric', day: 'numeric', timeZone: TZ });
  const hm: string = d.toLocaleTimeString('zh-CN', { hour12: false, hour: '2-digit', minute: '2-digit', timeZone: TZ });
  return `${day} ${hm}`;
}

export function ageSeconds(v: string | null | undefined): number | null {
  const d: Date | null = toDate(v);
  return d ? Math.max(0, Math.round((Date.now() - d.getTime()) / 1000)) : null;
}

export function errorText(e: unknown): string {
  const err = e as { response?: { data?: { error?: { message?: string } } }; message?: string };
  return err?.response?.data?.error?.message ?? err?.message ?? '出错了';
}

export function ageMs(v: number | string | null | undefined): number | null {
  const d: Date | null = toDate(v);
  return d ? Math.max(0, Date.now() - d.getTime()) : null;
}

/** 去掉常见 Markdown 记号、压成一行，用于列表里的“最新一句” */
export function oneLineText(text: string, max = 140): string {
  const flat: string = text
    .replace(/```[\s\S]*?```/gu, ' ')
    .replace(/[#>*`_|-]+/gu, ' ')
    .replace(/\s+/gu, ' ')
    .trim();
  return flat.length > max ? `${flat.slice(0, max)}…` : flat;
}
