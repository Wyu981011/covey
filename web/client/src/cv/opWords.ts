/* 网页发给 Covey 的操作（发件箱）从点下去到有回执，各处用同一套说法和同一个等法（T647 P1-C2）：
 * 发送中 → 已发出，等 Covey → Covey 回的那句（办好了）/ 没办成：原因；等满 OP_WAIT_MS 还没回音不算失败，
 * 操作留在发件箱里，Covey 回来会接着办。纯函数，单测在 scripts/words.test.mjs。 */
import type { OutboxView } from '@shared/api.interface';

/** 一条操作走到哪了：unsent 是请求本身没发出去（网络、校验），timeout 是等满了还没回音（不是失败） */
export type OpPhase = 'sending' | 'waiting' | 'done' | 'failed' | 'unsent' | 'timeout';

/** 等回执最多等多久；Covey 每半秒取一次发件，通常一两秒就回 */
export const OP_WAIT_MS = 60000;
/** 第 i 次问之前隔多久：头三次 0.7 秒，之后 1.5 秒 */
export const opDelay = (i: number): number => (i < 3 ? 700 : 1500);
/** 等满 OP_WAIT_MS 要问几次 */
export const OP_TRIES: number = (() => {
  let ms = 0;
  let n = 0;
  while (ms < OP_WAIT_MS) {
    ms += opDelay(n);
    n += 1;
  }
  return n;
})();

/** 回执里给人看的那句：去掉开关名这类内部词（“整理专项没有开（COVEY_PROJECT_TIDY）”→“整理专项没有开”），多余的空白收成一个 */
export function plainReceipt(message: string | null | undefined): string {
  return String(message ?? '')
    // 旧 Covey 的「不管了」没开看板时说“只记在这台设备上”：网页已不在本机另记（P1-C3），照实说拿不掉
    .replace(/[，,]\s*只记在这台设备上/gu, '，Covey 拿不掉它')
    .replace(/\s*[（(][^（）()]*\b(?:COVEY|LARK_BRIDGE)_[A-Z0-9_]+[^（）()]*[）)]/gu, '')
    .replace(/\b(?:COVEY|LARK_BRIDGE)_[A-Z0-9_]+(?:=\S+)?/gu, '')
    .replace(/[ \t]{2,}/gu, ' ')
    .replace(/\s+([，。；：])/gu, '$1')
    .trim();
}

/** 一条操作此刻的那句话。message：done、failed 时是 Covey 的回执，unsent 时是请求失败的原因 */
export function opWords(phase: OpPhase, message?: string | null): string {
  const said: string = plainReceipt(message);
  switch (phase) {
    case 'sending':
      return '发送中…';
    case 'waiting':
      return '已发出，等 Covey 处理…';
    case 'done':
      return said || '已执行';
    case 'failed':
      return `没办成：${said || 'Covey 没写原因'}`;
    case 'unsent':
      return `没发出去：${said || '网络出错'}`;
    default:
      return 'Covey 还没回音：操作留在发件箱里，Covey 回来会接着办';
  }
}

/** 发件箱一行的状态换成 OpPhase（new 还在等） */
export const rowPhase = (state: string): OpPhase => (state === 'done' ? 'done' : state === 'failed' ? 'failed' : 'waiting');

/** 话题页“动作”的名字：结果行写“停止：已执行”“作废记忆：没办成：…” */
export const OP_NAME: Record<string, string> = {
  answer: '回答',
  stop: '停止',
  reopen: '继续专项',
  forget: '作废记忆',
  switch: '换配置',
  memory_fix: '纠正记忆',
  recover: '接着做',
  dismiss: '不管了',
  tidy: '整理',
  tidy_decide: '整理建议',
  project_finish: '收尾专项',
  project_stop: '停止专项',
  memory_undo: '撤销记忆',
  revisit_cancel: '取消定时回看',
};

/** 话题页里一条动作（回答、补充说明、停止、换配置、恢复…）的结果行。换配置、恢复办好时直接写 Covey 的回执（从什么换成什么、任务几号） */
export function opLine(o: Pick<OutboxView, 'kind' | 'payload' | 'state' | 'message'>): string {
  const p: Record<string, unknown> = o.payload ?? {};
  const lesser: string = o.kind !== 'answer' ? '' : p.skip === true ? '补充说明' : p.ask === true ? '先问一句' : p.aside === true ? '不处理' : p.restore === true ? '撤销不处理' : '';
  const what: string = lesser || (o.kind === 'stop' && p.collab ? '停止本次协作' : OP_NAME[o.kind] ?? o.kind);
  const phase: OpPhase = rowPhase(o.state);
  if ((o.kind === 'switch' || o.kind === 'recover' || o.kind === 'memory_undo' || o.kind === 'revisit_cancel') && phase === 'done' && plainReceipt(o.message)) return plainReceipt(o.message);
  return `${what}：${opWords(phase, o.message)}`;
}
