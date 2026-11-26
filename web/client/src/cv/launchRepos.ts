/**
 * 去工作区（v43）的纯函数：新旧两代 Covey 的判定、设备联动、仓库选择、payload 清洗、标签文字。
 * 不碰 DOM、只引类型：防回归 scripts/launch-repos.test.mjs。
 * 判定：LaunchData.workspaces 存在 = 旧 Covey（面板、联动、payload 一字不变）；不存在 = 新 Covey（没有工作区、运行方式，带设备和仓库）。
 */
import type { LaunchData, LaunchDevice, LaunchModel, LaunchPayload, LaunchRepo, SayFile, SettingsRepoItem } from '@shared/api.interface';

/** 一次最多带几个仓库（服务端 ≤10） */
export const MAX_REPOS = 10;

type WithPlace = { workspace?: string; run_mode?: string; device?: string; repos?: LaunchRepo[] };

/** 新 Covey：不推 workspaces */
export const isRepoMode = (d: LaunchData): boolean => !d.workspaces;

/** 新 Covey 且推了 ≥2 台设备才画「执行设备」、才带 device */
export const showDevice = (d: LaunchData): boolean => isRepoMode(d) && (d.devices?.length ?? 0) >= 2;

/** 设备下拉的选项文字：名字加状态后缀（正常不加） */
export function deviceText(dv: LaunchDevice): string {
  const tail: string = dv.dot === 'down' ? '（离线）' : dv.dot === 'tight' ? '（紧张）' : dv.dot === 'never' ? '（未连过）' : '';
  return `${dv.name}${tail}`;
}

/** 选了设备：当前模型的 Harness 不在设备能用的里面，就换成第一个能用的模型（同旧 pickWorkspace 的联动；withModel 由调用方传入，避免循环引用） */
export function applyDevice<S extends WithPlace & { model: string }>(d: LaunchData, sel: S, name: string, swap: (m: LaunchModel, s: S) => S): S {
  let next: S = { ...sel, device: name };
  const dv: LaunchDevice | undefined = (d.devices ?? []).find((x: LaunchDevice) => x.name === name);
  const cur: LaunchModel | undefined = d.models.find((m: LaunchModel) => m.key === sel.model);
  if (dv && dv.harnesses.length && cur && !dv.harnesses.includes(cur.harness)) {
    const m: LaunchModel | undefined = d.models.find((x: LaunchModel) => dv.harnesses.includes(x.harness));
    if (m) next = swap(m, next);
  }
  return next;
}

export type RepoMode = 'none' | 'read' | 'write';
export const repoModeOf = (repos: LaunchRepo[] | undefined, name: string): RepoMode => (repos ?? []).find((r: LaunchRepo) => r.name === name)?.mode ?? 'none';

/** 点一下轮换：不用 → 只读 → 可写 → 不用（只读仓库跳过可写）；已满 10 个时“不用”不能再加 */
export function cycleRepo(repos: LaunchRepo[] | undefined, name: string, readonly = false): LaunchRepo[] {
  const cur: LaunchRepo[] = repos ?? [];
  const mode: RepoMode = repoModeOf(cur, name);
  const rest: LaunchRepo[] = cur.filter((r: LaunchRepo) => r.name !== name);
  if (mode === 'none') return cur.length >= MAX_REPOS ? cur : [...cur, { name, mode: 'read' }];
  if (mode === 'read' && !readonly) return cur.map((r: LaunchRepo) => (r.name === name ? { name, mode: 'write' as const } : r));
  return rest;
}

/** 仓库选择行列哪些块：名单里非冻结的，加上已选但名单里没有的（话题带着、后来冻结了的，要能取消） */
export function repoChoices(items: SettingsRepoItem[], selected: LaunchRepo[] | undefined): { name: string; readonly: boolean; note: string }[] {
  const out = items
    .filter((i: SettingsRepoItem) => i.status !== 'frozen')
    .map((i: SettingsRepoItem) => ({ name: i.name, readonly: i.status === 'readonly', note: i.note }));
  for (const r of selected ?? []) if (!out.some((o) => o.name === r.name)) out.push({ name: r.name, readonly: false, note: '' });
  return out;
}

/** 两份仓库选择是否一样（不看顺序） */
export function sameRepos(a: LaunchRepo[] | undefined, b: LaunchRepo[] | undefined): boolean {
  const key = (x: LaunchRepo[] | undefined): string => (x ?? []).map((r: LaunchRepo) => `${r.name}:${r.mode}`).sort().join('|');
  return key(a) === key(b);
}

/** “仓库 a、b”，最多列 2 个，多了写“仓库 a、b 等 N 个”；没有是空串 */
export function repoLabel(repos: { name: string }[] | undefined): string {
  const names: string[] = (repos ?? []).map((r) => r.name);
  if (!names.length) return '';
  return `仓库 ${names.slice(0, 2).join('、')}${names.length > 2 ? ` 等 ${names.length} 个` : ''}`;
}

/** 新 Covey 的 payload 清洗：删掉 workspace、run_mode（不留空串、不留 undefined 键）；device 只在多设备且选了时留；repos 空就不带。
 *  emptyRepos：换配置里把仓库全取消时要明确发空数组，不然 Covey 当作没改 */
export function cleanRepoPayload<T extends WithPlace>(d: LaunchData, p: T, emptyRepos = false): T {
  const out: T = { ...p };
  delete out.workspace;
  delete out.run_mode;
  if (!showDevice(d) || !out.device) delete out.device;
  if (!out.repos?.length) {
    if (emptyRepos) out.repos = [];
    else delete out.repos;
  }
  return out;
}

/** 开新话题的 payload：旧 Covey 一字不变（含 run_mode: 设备上只能 direct），新 Covey 走清洗 */
export function launchPayload(d: LaunchData, sel: Omit<LaunchPayload, 'text'>, text: string, files: SayFile[], onDevice: boolean): LaunchPayload {
  const extra = files.length ? { files } : {};
  if (isRepoMode(d)) return cleanRepoPayload(d, { ...sel, text, ...extra });
  return { ...sel, text, run_mode: onDevice ? 'direct' : sel.run_mode, ...extra };
}

/** 换配置的 payload：旧 Covey 原样；新 Covey 清洗，并且仓库从有变成全空时发 [] */
export function switchPayload<T extends WithPlace>(d: LaunchData, cur: T, hadRepos: boolean, lead: boolean): Record<string, unknown> {
  if (!isRepoMode(d)) return { ...cur };
  return cleanRepoPayload(d, lead ? { ...cur, repos: undefined } : cur, !lead && hadRepos);
}
