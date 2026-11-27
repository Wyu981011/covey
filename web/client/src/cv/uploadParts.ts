/* 附件分段（数据约定 v20，T876 v44）：开上传时新服务端回 part_bytes（每段原始字节，按它的请求体上限放大），按它切；
 * 旧服务端不带，照 UPLOAD_PART_BYTES（512 KiB）切，和以前一样。纯函数，单测在 scripts/calib.test.mjs。 */
import { UPLOAD_PART_BYTES } from '@shared/api.interface';

/** 每段多大：服务端给的 part_bytes 是正整数、且按它切出来的段数和它说的 parts 对得上才用它，否则照 UPLOAD_PART_BYTES */
export function partBytesOf(res: { parts: number; part_bytes?: number }, size: number): number {
  const b: unknown = res.part_bytes;
  if (typeof b === 'number' && Number.isInteger(b) && b > 0 && Math.ceil(size / b) === res.parts) return b;
  return UPLOAD_PART_BYTES;
}

/** 第 n 段在文件里的起止（[start, end)，最后一段可以短） */
export const partRange = (n: number, partBytes: number, size: number): [number, number] => [n * partBytes, Math.min(size, (n + 1) * partBytes)];
