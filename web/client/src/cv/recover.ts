/* 没成功的一轮上的按钮（T647 P0-5，Covey 数据约定 v33）：和飞书任务卡、恢复卡做同一件事。
 * - 字照 failure.labels（“检查并继续”，结果没发出去时是“重新投递结果”；“现在重试”）；
 * - 做法照 failure.how：recover 发 recover 操作（Covey 照任务卡的同名按钮办：结果保存了没发出去的只重发保存的那份，不跑模型），
 *   switch 打开同页的换配置，feishu 只有飞书能做（管家、负责人的换个模型）；
 * - 排着自动重试时只给“现在重试”“停止自动重试”和别的，都不做主按钮，免得和排好的那次并排再开一轮。
 * 纯函数，单测在 scripts/recover.test.mjs。 */
import type { FailureAction, FailureButton, FailureHow, RecoverAction, TurnAutoRetry, TurnFailure } from '@shared/api.interface';

/** 按钮的默认叫法（covey core/failure.py LABELS，docs/ui.md 第 6 节）：旧数据没有 labels 时用 */
export const BUTTON_LABEL: Record<FailureButton, string> = {
  continue: '检查并继续',
  retry: '现在重试',
  diagnose: '看原因',
  split: '拆小再试',
  switch_model: '换个模型',
  stop_auto_retry: '停止自动重试',
};

export interface RecoverButton {
  key: FailureButton;
  label: string;
  how: FailureHow;
  /** 实心靛色的主按钮；一块最多一个，排着自动重试时没有 */
  primary: boolean;
}

export interface RecoverPlan {
  buttons: RecoverButton[];
  /** 排着的自动重试（有它时上面没有主按钮） */
  auto: TurnAutoRetry | null;
}

/** 换个模型在网页上能不能自己做：普通话题、带着 config、设置里有模型目录时能（同页的换配置面板） */
export interface PlanContext {
  canSwitch: boolean;
}

const RECOVERS: readonly string[] = ['continue', 'retry', 'diagnose', 'split', 'stop_auto_retry'];
export const isRecoverAction = (k: string): k is RecoverAction => RECOVERS.includes(k);

/** 这一颗怎么做：Covey 说了算（v33 how）；旧数据没说时，换个模型看网页能不能换（普通话题能，管家、负责人不能），其余发 recover。
 * 说是 switch、页面上却没有能换的面板（旧数据没有 config）时，点的时候再说去飞书（RecoverBits） */
export function howOf(f: TurnFailure, key: FailureButton, ctx: PlanContext): FailureHow {
  const said: FailureHow | undefined = f.how?.[key];
  if (said) return said;
  if (key === 'switch_model') return ctx.canSwitch ? 'switch' : 'feishu';
  return 'recover';
}

export const labelOf = (f: TurnFailure, key: FailureButton): string => f.labels?.[key] || BUTTON_LABEL[key];

/** 画哪几颗、谁是主按钮。actions 为空就是现在没有能点的（Covey 故意不给：换旧模型重试、重启后的自动接着做已经排好），不补「检查并继续」 */
export function recoverPlan(f: TurnFailure, ctx: PlanContext): RecoverPlan {
  const auto: TurnAutoRetry | null = f.auto_retry?.state === 'pending' ? f.auto_retry : null;
  const keys: FailureButton[] = auto
    ? [auto.now, 'stop_auto_retry', ...f.actions.filter((a: FailureAction) => a !== 'continue' && a !== 'retry')]
    : [...f.actions];
  const seen = new Set<FailureButton>();
  const buttons: RecoverButton[] = [];
  for (const key of keys) {
    if (seen.has(key)) continue;
    seen.add(key);
    const label: string = auto && key === auto.now ? (f.labels?.[key] && key !== 'continue' ? f.labels[key] as string : BUTTON_LABEL.retry) : labelOf(f, key);
    buttons.push({ key, label, how: howOf(f, key, ctx), primary: false });
  }
  // 一块最多一个主按钮：第一颗接着做的（检查并继续、现在重试、重新投递结果）；排着自动重试时一个都没有
  if (!auto) {
    const main: RecoverButton | undefined = buttons.find((b: RecoverButton) => b.key === 'continue' || b.key === 'retry') ?? buttons[0];
    if (main) main.primary = true;
  }
  return { buttons, auto };
}

/** 自动重试的倒计时：“约 3 分钟后自动重试（第 2/5 次）”；时间到了还没开始是“马上自动重试”。at 是秒。
 * title：那一轮的原因那句，Covey 已经在里面写了第几次时就不再重复 */
export function autoRetryWords(a: TurnAutoRetry, now: number, title = ''): string {
  const said: boolean = !!a.attempt && title.includes(`第 ${a.attempt}`);
  const nth: string = a.attempt && !said ? (a.total ? `（第 ${a.attempt}/${a.total} 次）` : `（第 ${a.attempt} 次）`) : '';
  if (!a.at) return `已排好自动重试${nth}`;
  const left: number = a.at - now;
  if (left <= 30) return `马上自动重试${nth}`;
  if (left < 3600) return `约 ${Math.max(1, Math.round(left / 60))} 分钟后自动重试${nth}`;
  const h: number = Math.floor(left / 3600);
  const m: number = Math.round((left % 3600) / 60);
  return `约 ${h} 小时${m ? ` ${m} 分钟` : ''}后自动重试${nth}`;
}

/** recover 操作的 payload；这一轮没有任务号（旧数据）就发不了，返回 null */
export function recoverPayload(jobId: string | null | undefined, key: FailureButton): { job_id: string; action: RecoverAction } | null {
  const job: string = String(jobId ?? '').trim();
  if (!/^\d{1,12}$/u.test(job) || !isRecoverAction(key)) return null;
  return { job_id: job, action: key };
}

/** 没有 failure 字段的旧数据：只说停住了，不编按钮（在下面写一句就开下一轮） */
export const OLD_FAILURE_TITLE = '这一轮停住了，原因没推过来';
