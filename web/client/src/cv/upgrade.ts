/* 「版本与更新」（数据约定 v39，Covey 推的设置条目 upgrade）：从条目算出页面上的每一句话、按钮能不能点。纯函数，单测在 scripts/upgrade.test.mjs。
 * 只在 Covey 认 upgrade 操作（settings.ops）且推过这个条目时出现；旧 Covey 两样都没有，页面上什么都不多。 */
import type { UpgradeData, UpgradeResponse } from '@shared/api.interface';
import { ago } from './topicText';
import { canDo } from './v34';

/** 设置页里的页签 */
export const UPGRADE_TAB = { key: 'upgrade', label: '更新' } as const;

/** 这台 Covey 有「版本与更新」：认 upgrade 操作，也推过条目 */
export const upgradeOn = (ops: readonly string[] | null | undefined, r: UpgradeResponse | null | undefined): boolean =>
  canDo(ops, 'upgrade') && !!r?.data?.live;

/** 侧栏底部、手机底栏「设置」旁的小标记：在升级时写“更新中”，有新版本时写“有新版本”，其余不画（空串） */
export function upgradeMark(d: UpgradeData | null | undefined): string {
  if (!d) return '';
  if (d.running) return '更新中';
  return d.available ? '有新版本' : '';
}

/** 页面顶上那一句 */
export function upgradeHeadline(d: UpgradeData): string {
  if (d.running) return '正在更新';
  if (d.checking) return '正在检查更新…';
  if (!d.checked_at) return '还没检查过更新';
  if (!d.available) return '已经是最新';
  return d.count > 0 ? `有 ${d.count} 个更新` : '网页有新版本';
}

/** 现在 → 最新 的那一行 */
export function versionLine(d: UpgradeData): string {
  if (d.latest && d.latest !== d.live) return `现在 ${d.live} → 最新 ${d.latest}`;
  return `现在 ${d.live}`;
}

/** 网页会不会跟着更新；没有网页工作台是空串 */
export function webLine(d: UpgradeData): string {
  const w = d.web;
  if (!w) return '';
  if (w.manual) return '网页不是部署脚本建的，这次不会跟着更新：照你部署时的办法更新';
  if (w.current) return '网页已经是新版，这次不动它';
  if (w.kind === 'selfhost') return '网页跟着更新：在本机重新构建，要几分钟';
  if (w.kind === 'miaoda') return '网页跟着更新：重新发布到妙搭，要几分钟';
  return '网页跟着更新';
}

/** 点「全部更新」前问的那句话：机器人会不会重启、网页会怎样 */
export function confirmWords(d: UpgradeData): string {
  const parts: string[] = [];
  if (d.bridge) parts.push('机器人会重启几秒，在跑的任务不中断');
  const w = d.web;
  if (w && !w.manual && !w.current) parts.push(`网页会${w.kind === 'selfhost' ? '重新构建' : '重新发布'}，要几分钟，之后刷新页面`);
  return parts.length ? `${parts.join('；')}。` : '';
}

/** 「全部更新」能不能点；不能点时 why 是原因（灰字写在按钮旁） */
export function runState(d: UpgradeData): { ok: boolean; why: string } {
  if (d.running) return { ok: false, why: '正在更新，等它做完' };
  if (d.checking) return { ok: false, why: '正在检查更新' };
  if (d.blocked) return { ok: false, why: d.blocked };
  if (!d.available) return { ok: false, why: d.checked_at ? '已经是最新' : '先检查更新' };
  return { ok: true, why: '' };
}

/** 「检查更新」能不能点：在查、在升级时不能 */
export const canCheck = (d: UpgradeData): boolean => !d.running && !d.checking;

/** 上次检查的那一行灰字；没查过是空串 */
export const checkedLine = (d: UpgradeData, now: number): string => (d.checked_at ? `上次检查 ${ago(d.checked_at, now)}` : '');

/** 上次从网页点的升级：结果说法和要不要标红；没有是 null */
export function lastLine(d: UpgradeData, now: number): { text: string; bad: boolean } | null {
  const l = d.last;
  if (!l) return null;
  const head: string = l.state === 'done' ? '上次更新好了' : l.state === 'partial' ? '上次只更新了机器人，网页没更新上' : '上次没更新成';
  const when: string = l.at ? `（${ago(l.at, now)}）` : '';
  const msg: string = l.message.trim();
  return { text: `${head}${when}${msg ? `：${msg}` : ''}`, bad: l.state !== 'done' };
}

/** 列出来的之外还有几个新提交（count 是两个库合计） */
export const moreChanges = (d: UpgradeData): number => Math.max(0, d.count - d.changes.length);
