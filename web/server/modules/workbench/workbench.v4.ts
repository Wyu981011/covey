/* 数据约定 v4 的可选字段：话题要点 gist、进度 progress、问题卡的回答 answers、没做成的一轮 failure。
 * Covey 推来的是 jsonb，形状不对就当没有（返回 undefined），页面拿不到就不画那一块。 */
import {
  FAILURE_ACTIONS,
  FAILURE_HOWS,
  RECOVER_ACTIONS,
  type FailureAction,
  type FailureButton,
  type FailureHow,
  type TopicCommand,
  type TopicConfig,
  type TopicGist,
  type TopicProgress,
  type TopicSlowStep,
  type TurnAnswer,
  type TurnAutoRetry,
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
  // 进度说明（docs/web.md 进度）：这步比平均慢、在等一条命令跑完。形状不对就当没有
  if ('slow_step' in d) p.slow_step = slowStepOf(d.slow_step);
  const command: TopicCommand | undefined = commandOf(d.command);
  if (command) p.command = command;
  return Object.keys(p).length ? p : undefined;
}

const seconds = (v: unknown): number | undefined => {
  const n: number | undefined = finite(v);
  return n !== undefined && n >= 0 ? n : undefined;
};
const moment = (v: unknown): number | null => {
  const n: number | undefined = finite(v);
  return n !== undefined && n > 0 ? n : null;
};

/** 当前这步比此前平均每步慢：{number, since, seconds, usual}；不是这样的对象就是 null */
function slowStepOf(v: unknown): TopicSlowStep | null {
  if (!isObj(v)) return null;
  const d: Record<string, unknown> = obj(v);
  const number: number | undefined = finite(d.number);
  const secs: number | undefined = seconds(d.seconds);
  if (number === undefined || number < 1 || secs === undefined) return null;
  const usual: number | undefined = seconds(d.usual);
  return { number: Math.round(number), since: moment(d.since), seconds: secs, usual: usual ?? null };
}

/** 最新一步是还在跑的命令：{since, seconds, long} */
function commandOf(v: unknown): TopicCommand | undefined {
  if (!isObj(v)) return undefined;
  const d: Record<string, unknown> = obj(v);
  const secs: number | undefined = seconds(d.seconds);
  if (secs === undefined) return undefined;
  return { since: moment(d.since), seconds: secs, long: d.long === true };
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

/** 按钮的 key：没成功的一轮能做的，加上排着自动重试时的“停止自动重试” */
const BUTTONS: readonly FailureButton[] = [...FAILURE_ACTIONS, 'stop_auto_retry'];

export function failureOf(v: unknown): TurnFailure | undefined {
  if (!isObj(v)) return undefined;
  const d: Record<string, unknown> = obj(v);
  const title: string = str(d.title).trim();
  if (!title) return undefined;
  const actions: FailureAction[] = Array.isArray(d.actions)
    ? d.actions.filter((a: unknown): a is FailureAction => typeof a === 'string' && (FAILURE_ACTIONS as readonly string[]).includes(a))
    : [];
  const detail: string = str(d.detail).trim();
  const out: TurnFailure = { title, ...(detail ? { detail } : {}), actions: [...new Set(actions)] };
  // v33：按钮的字、怎么做、排着的自动重试（只留认得的 key；旧 Covey 不推就没有）
  const labels: Partial<Record<FailureButton, string>> = {};
  const how: Partial<Record<FailureButton, FailureHow>> = {};
  const lo: Record<string, unknown> = obj(d.labels);
  const ho: Record<string, unknown> = obj(d.how);
  for (const k of BUTTONS) {
    const label: string = str(lo[k]).trim();
    if (label) labels[k] = Array.from(label).slice(0, 20).join('');
    if ((FAILURE_HOWS as readonly string[]).includes(str(ho[k]))) how[k] = ho[k] as FailureHow;
  }
  if (Object.keys(labels).length) out.labels = labels;
  if (Object.keys(how).length) out.how = how;
  const auto: TurnAutoRetry | undefined = autoRetryOf(d.auto_retry);
  if (auto) out.auto_retry = auto;
  return out;
}


/** v33：排着的自动重试 {state: pending, at, attempt, total, kind, now}；不在排着（或形状不对）就没有 */
function autoRetryOf(v: unknown): TurnAutoRetry | undefined {
  if (!isObj(v)) return undefined;
  const d: Record<string, unknown> = obj(v);
  if (d.state !== 'pending') return undefined;
  const whole = (x: unknown): number | null => {
    const n: number | undefined = finite(x);
    return n !== undefined && n > 0 ? Math.round(n) : null;
  };
  return {
    state: 'pending',
    at: moment(d.at),
    attempt: whole(d.attempt),
    total: whole(d.total),
    kind: str(d.kind).slice(0, 40),
    now: d.now === 'continue' ? 'continue' : 'retry',
  };
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

/** v33：recover 操作的形状（没成功的一轮上的按钮：检查并继续、现在重试、看原因、拆小再试、停止自动重试）：
 * 要 topic_key、不带 project_key，payload 只有 job_id（任务号，数字或数字串）和 action。能不能做由 Covey 按记录定，这里只挡形状不对的。
 * 对就返回规整后的任务号，不对返回原因（400 的消息） */
export function recoverShape(payload: Record<string, unknown>, topicKey: string, projectKey: string): { job_id: string } | { error: string } {
  if (!topicKey || projectKey) return { error: 'recover 要 topic_key、不带 project_key' };
  if (Object.keys(payload).some((k: string) => k !== 'job_id' && k !== 'action')) return { error: 'recover 只有 job_id 和 action' };
  const job: string = typeof payload.job_id === 'number' && Number.isInteger(payload.job_id) ? String(payload.job_id) : str(payload.job_id).trim();
  if (!/^\d{1,12}$/u.test(job)) return { error: 'recover 要任务号 job_id' };
  if (!(RECOVER_ACTIONS as readonly string[]).includes(str(payload.action))) return { error: 'recover 的 action 不合法' };
  return { job_id: job };
}
