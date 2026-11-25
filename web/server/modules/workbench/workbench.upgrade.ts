/* 数据约定 v39：版本与更新。Covey 推来的 settings 条目 upgrade（jsonb）理成页面要的形状，形状不对的字段当没有；
 * 发件 upgrade 的 payload 校验。纯函数，单测在 scripts/upgrade.test.mjs。 */
import { UPGRADE_ACTIONS, type UpgradeAction, type UpgradeChange, type UpgradeData, type UpgradeLast, type UpgradeRunning, type UpgradeWeb } from '@shared/api.interface';
import { obj, str } from './workbench.util';

const isObj = (v: unknown): boolean => !!v && typeof v === 'object' && !Array.isArray(v);
const seconds = (v: unknown): number => (typeof v === 'number' && Number.isFinite(v) && v > 0 ? v : 0);
const count = (v: unknown): number => (typeof v === 'number' && Number.isInteger(v) && v > 0 ? v : 0);
const cut = (v: unknown, n: number): string => str(v).slice(0, n);

/** 列出来的新提交最多几个，升级输出最后几行最多几行 */
export const UPGRADE_CHANGES = 20;
export const UPGRADE_TAIL = 20;

function webOf(v: unknown): UpgradeWeb | null {
  if (!isObj(v)) return null;
  const w: Record<string, unknown> = obj(v);
  return { kind: cut(w.kind, 20), current: w.current === true, manual: w.manual === true };
}

function runningOf(v: unknown): UpgradeRunning | null {
  if (!isObj(v)) return null;
  const r: Record<string, unknown> = obj(v);
  return { op_id: cut(r.op_id, 64), started_at: seconds(r.started_at), log: cut(r.log, 500) };
}

function lastOf(v: unknown): UpgradeLast | null {
  if (!isObj(v)) return null;
  const l: Record<string, unknown> = obj(v);
  const state: string = str(l.state);
  if (!state) return null;
  const tail: string[] = Array.isArray(l.tail) ? l.tail.filter((x: unknown) => typeof x === 'string').slice(-UPGRADE_TAIL).map((x: string) => x.slice(0, 400)) : [];
  return {
    state: state.slice(0, 20),
    message: cut(l.message, 600),
    at: seconds(l.at),
    ...(str(l.release) ? { release: cut(l.release, 80) } : {}),
    ...(str(l.log) ? { log: cut(l.log, 500) } : {}),
    ...(tail.length ? { tail } : {}),
  };
}

function changeOf(v: unknown): UpgradeChange | null {
  if (!isObj(v)) return null;
  const c: Record<string, unknown> = obj(v);
  const sha: string = str(c.sha);
  if (!/^[0-9a-f]{4,40}$/u.test(sha)) return null;
  return { repo: cut(c.repo, 60), sha: sha.slice(0, 12), subject: cut(c.subject, 300), at: seconds(c.at) };
}

/** settings 条目 upgrade 的 data → 页面要的形状；不是对象、或连现网 release 都没有就是 undefined（页面不画「版本与更新」） */
export function upgradeOf(v: unknown): UpgradeData | undefined {
  if (!isObj(v)) return undefined;
  const d: Record<string, unknown> = obj(v);
  const live: string = cut(d.live, 80);
  if (!live) return undefined;
  const changes: UpgradeChange[] = (Array.isArray(d.changes) ? d.changes : [])
    .map(changeOf)
    .filter((c: UpgradeChange | null): c is UpgradeChange => c !== null)
    .slice(0, UPGRADE_CHANGES);
  return {
    live,
    latest: cut(d.latest, 80),
    available: d.available === true,
    bridge: d.bridge === true,
    web: webOf(d.web),
    count: Math.max(count(d.count), changes.length),
    changes,
    checked_at: seconds(d.checked_at),
    checking: d.checking === true,
    error: cut(d.error, 600),
    blocked: cut(d.blocked, 600),
    running: runningOf(d.running),
    last: lastOf(d.last),
  };
}

/** v39：发件 upgrade：不带 topic_key、project_key，payload 只有 action（check 检查更新、run 全部更新） */
export function upgradeShape(payload: Record<string, unknown>, topicKey: string, projectKey: string): { action: UpgradeAction } | { error: string } {
  if (topicKey || projectKey) return { error: 'upgrade 不带 topic_key、project_key' };
  if (Object.keys(payload).some((k: string) => k !== 'action')) return { error: 'upgrade 只有 action' };
  const action: string = str(payload.action);
  if (!(UPGRADE_ACTIONS as readonly string[]).includes(action)) return { error: 'upgrade 的 action 只能是 check 或 run' };
  return { action: action as UpgradeAction };
}
