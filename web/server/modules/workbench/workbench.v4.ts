/* 数据约定 v4 的可选字段：话题要点 gist、进度 progress、问题卡的回答 answers、没做成的一轮 failure。
 * Covey 推来的是 jsonb，形状不对就当没有（返回 undefined），页面拿不到就不画那一块。 */
import {
  FAILURE_ACTIONS,
  type FailureAction,
  type TopicConfig,
  type TopicGist,
  type TopicProgress,
  type TurnAnswer,
  type TurnFailure,
} from '@shared/api.interface';
import { obj, str } from './workbench.util';

const isObj = (v: unknown): boolean => !!v && typeof v === 'object' && !Array.isArray(v);
const finite = (v: unknown): number | undefined => (typeof v === 'number' && Number.isFinite(v) ? v : undefined);

export function gistOf(v: unknown): TopicGist | undefined {
  if (!isObj(v)) return undefined;
  const d: Record<string, unknown> = obj(v);
  const g: TopicGist = {};
  for (const k of ['essence', 'goal', 'involves', 'changed'] as const) {
    const s: string = str(d[k]).trim();
    if (s) g[k] = s;
  }
  if (Array.isArray(d.related)) {
    const rel: number[] = d.related.map((x: unknown) => (typeof x === 'string' ? Number(x.replace(/^T/iu, '')) : x)).filter((x: unknown): x is number => typeof x === 'number' && Number.isInteger(x) && x > 0);
    if (rel.length) g.related = rel.slice(0, 20);
  }
  const at: number | undefined = finite(d.updated_at);
  if (at !== undefined) g.updated_at = at;
  return Object.keys(g).length ? g : undefined;
}

export function progressOf(v: unknown): TopicProgress | undefined {
  if (!isObj(v)) return undefined;
  const d: Record<string, unknown> = obj(v);
  const p: TopicProgress = {};
  const phase: string = str(d.phase).trim();
  if (phase) p.phase = phase;
  const done: number | undefined = finite(d.plan_done);
  const total: number | undefined = finite(d.plan_total);
  if (total !== undefined && total > 0) {
    p.plan_total = Math.round(total);
    p.plan_done = Math.max(0, Math.min(Math.round(done ?? 0), p.plan_total));
  }
  const lastAt: number | undefined = finite(d.last_activity_at);
  if (lastAt !== undefined && lastAt > 0) p.last_activity_at = lastAt;
  const last: string = str(d.last_activity).trim();
  if (last) p.last_activity = last;
  if ('eta_seconds' in d) {
    const eta: number | undefined = finite(d.eta_seconds);
    p.eta_seconds = eta !== undefined && eta >= 0 ? eta : null;
  }
  if (d.maybe_stuck === true) p.maybe_stuck = true;
  return Object.keys(p).length ? p : undefined;
}

export function answersOf(v: unknown): TurnAnswer[] | undefined {
  if (!Array.isArray(v)) return undefined;
  const out: TurnAnswer[] = [];
  for (const x of v) {
    const d: Record<string, unknown> = obj(x);
    const question: string = str(d.question).trim();
    const choice: string = str(d.choice).trim();
    if (question || choice) out.push({ question, choice: choice || '没答' });
  }
  return out.length ? out.slice(0, 40) : undefined;
}

export function failureOf(v: unknown): TurnFailure | undefined {
  if (!isObj(v)) return undefined;
  const d: Record<string, unknown> = obj(v);
  const title: string = str(d.title).trim();
  if (!title) return undefined;
  const actions: FailureAction[] = Array.isArray(d.actions)
    ? d.actions.filter((a: unknown): a is FailureAction => typeof a === 'string' && (FAILURE_ACTIONS as readonly string[]).includes(a))
    : [];
  const detail: string = str(d.detail).trim();
  return { title, ...(detail ? { detail } : {}), actions: [...new Set(actions)] };
}

/** v20：话题现在的配置。model、workspace 必须有；别的缺了按空串、direct、off 补，页面按它预选换配置面板 */
export function configOf(v: unknown): TopicConfig | undefined {
  if (!isObj(v)) return undefined;
  const d: Record<string, unknown> = obj(v);
  const model: string = str(d.model).trim();
  const workspace: string = str(d.workspace).trim();
  if (!model || !workspace) return undefined;
  return {
    model,
    effort: str(d.effort),
    work_mode: str(d.work_mode),
    workspace,
    run_mode: d.run_mode === 'worktree' ? 'worktree' : 'direct',
    redaction: d.redaction === 'on' ? 'on' : 'off',
  };
}
