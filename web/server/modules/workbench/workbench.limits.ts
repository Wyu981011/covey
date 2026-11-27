/**
 * 这个服务端的收发上限和内存读数（数据约定 v44，T876）。纯函数和进程级的读数，不带 Nest 装饰器，单测直接导入。
 *
 * - 请求体上限：环境变量 BODY_SIZE_LIMIT，没设是 DEFAULT_BODY_LIMIT（8mb）。main.ts 把它交给 configureApp 的 bodyLimit
 *   （平台包默认只收 1mb；妙搭 FaaS 自己的硬顶是 12 MB，再大直接被网关拒，所以默认留 4 MB 余量）。
 * - 一张图、附件的一段：由请求体上限推出来（base64 之后整个请求放得下），各有封顶；请求体上限不超过 1 MiB（旧部署、自托管设得小）时
 *   和以前完全一样：一张图 760 KiB、附件一段 512 KiB。
 * - 内存：V8 堆上限（看 NODE_OPTIONS 的 --max-old-space-size 生效没有）、此刻常驻、容器（cgroup）上限，单位 MB，读不到是 0。
 */
import { readFileSync } from 'fs';
import { getHeapStatistics } from 'v8';

export const DEFAULT_BODY_LIMIT = '8mb';
const MIB = 1024 * 1024;
/** 旧上限下的数（请求体 ≤ 1 MiB 时照旧） */
export const LEGACY_IMAGE_BYTES = 760 * 1024;
export const LEGACY_PART_BYTES = 512 * 1024;
/** 放大以后的封顶：一张图 4 MiB，附件一段 4 MiB（base64 后约 5.6 MB） */
export const MAX_IMAGE_BYTES = 4 * MIB;
export const MAX_PART_BYTES = 4 * MIB;
/** 请求里 base64 之外的 JSON 留多少 */
const SLACK = 64 * 1024;

const UNITS: Record<string, number> = { b: 1, kb: 1024, mb: MIB, gb: 1024 * MIB };

/** '8mb'、'512kb'、'1048576' 这类写法（同 body-parser 用的 bytes 包，大小写不论）→ 字节；认不出是 null */
export function parseBytes(raw: unknown): number | null {
  if (typeof raw === 'number') return Number.isFinite(raw) && raw > 0 ? Math.floor(raw) : null;
  const m = /^\s*(\d+(?:\.\d+)?)\s*(b|kb|mb|gb)?\s*$/iu.exec(String(raw ?? ''));
  if (!m) return null;
  const n: number = Math.floor(Number(m[1]) * UNITS[(m[2] ?? 'b').toLowerCase()]);
  return n > 0 ? n : null;
}

/** 交给 configureApp 的 bodyLimit：BODY_SIZE_LIMIT 认得出就用它，否则默认 */
export function bodyLimit(env: NodeJS.ProcessEnv = process.env): string {
  const raw: string = String(env.BODY_SIZE_LIMIT ?? '').trim();
  return raw && parseBytes(raw) !== null ? raw : DEFAULT_BODY_LIMIT;
}

export function bodyBytes(env: NodeJS.ProcessEnv = process.env): number {
  return parseBytes(bodyLimit(env)) ?? 8 * MIB;
}

/** base64 之后加上 JSON 的外壳还在请求体上限里的原始字节数 */
const rawFits = (body: number): number => Math.max(0, Math.floor(((body - SLACK) * 3) / 4));

/** 一份图片解出来最多多少字节 */
export function imageBytes(body: number = bodyBytes()): number {
  return body <= MIB ? LEGACY_IMAGE_BYTES : Math.min(MAX_IMAGE_BYTES, Math.max(LEGACY_IMAGE_BYTES, rawFits(body)));
}

/** 附件每段原始字节：64 KiB 的整数倍 */
export function partBytes(body: number = bodyBytes()): number {
  if (body <= MIB) return LEGACY_PART_BYTES;
  const n: number = Math.min(MAX_PART_BYTES, Math.max(LEGACY_PART_BYTES, rawFits(body)));
  return Math.floor(n / SLACK) * SLACK;
}

let cgroupMb: number | null = null;
/** 容器的内存上限（MB）：cgroup v2 的 memory.max，v1 的 memory.limit_in_bytes；没有或是 max 是 0。只读一次 */
export function memLimitMb(read: (p: string) => string = (p: string) => readFileSync(p, 'utf8')): number {
  if (cgroupMb !== null) return cgroupMb;
  let mb = 0;
  for (const p of ['/sys/fs/cgroup/memory.max', '/sys/fs/cgroup/memory/memory.limit_in_bytes']) {
    try {
      const n = Number(read(p).trim());
      // v1 没限时是一个接近 2^63 的数
      if (Number.isFinite(n) && n > 0 && n < 2 ** 50) {
        mb = Math.round(n / MIB);
        break;
      }
    } catch {
      /* 没有这个文件 */
    }
  }
  cgroupMb = mb;
  return mb;
}

export function heapLimitMb(): number {
  try {
    return Math.round(getHeapStatistics().heap_size_limit / MIB);
  } catch {
    return 0;
  }
}

export function rssMb(): number {
  try {
    return Math.round(process.memoryUsage.rss() / MIB);
  } catch {
    return 0;
  }
}
