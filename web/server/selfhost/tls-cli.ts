/**
 * 命令行：保证自签证书在（安装器和 web_selfhost.py 在服务起来前就生成它，好把指纹告诉主人）。
 *   node tls-cli.js --dir <tls 目录> --names a,b
 * stdout 一行 JSON：{cert,key,fingerprint,not_after,names,generated}；出错退出 1，原因写 stderr。
 */
import { ensureSelfSigned, normalizeNames } from './tls';

function arg(name: string): string {
  const i: number = process.argv.indexOf(name);
  return i >= 0 ? (process.argv[i + 1] ?? '') : '';
}

try {
  const dir: string = arg('--dir');
  const names: string[] = normalizeNames(arg('--names').split(','));
  if (!dir) throw new Error('缺 --dir');
  if (names.length === 0) throw new Error('缺 --names');
  const m = ensureSelfSigned(dir, names);
  process.stdout.write(`${JSON.stringify({ cert: m.certPath, key: m.keyPath, fingerprint: m.fingerprint, not_after: m.notAfter.toISOString(), names: m.names, generated: m.generated })}\n`);
} catch (e) {
  process.stderr.write(`${e instanceof Error ? e.message : String(e)}\n`);
  process.exit(1);
}
