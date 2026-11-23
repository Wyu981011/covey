/* 数据约定 v34 的几样在网页上怎么说（纯函数，单测在 scripts/v34.test.mjs）：Covey 定时回看、代发草稿、完成标准与改动两行（和飞书答案卡同义）、
 * 这个 Covey 认不认某个网页操作。 */
import type { OwnerSendDraft, TopicRevisit, TurnCriterion, TurnDelivery } from '@shared/api.interface';

/** 这个 Covey 认这个操作吗（v34 settings.ops）；旧 Covey 不推 ops，新按钮一律不画，照旧只读 */
export const canDo = (ops: readonly string[] | null | undefined, kind: string): boolean => Array.isArray(ops) && ops.includes(kind);

const clock = (sec: number): string =>
  new Date(sec * 1000).toLocaleTimeString('zh-CN', { hour12: false, hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Shanghai' });
const day = (sec: number): string =>
  new Date(sec * 1000).toLocaleDateString('zh-CN', { timeZone: 'Asia/Shanghai', month: '2-digit', day: '2-digit' }).replace(/\//gu, '-');

/** 主语是 Covey（回看是 Covey 到点自己去做的，不是等你回来看）：“Covey 将于 21:40 自动回看：CI 跑完没有”；不是今天的写上日期；
 * 时间过了还没排出去写“已到点，Covey 即将自动回看”；Covey 已经在回看（running）写“Covey 正在自动回看” */
export function revisitWords(r: TopicRevisit, now: number): string {
  const when: string = day(r.at) === day(now) ? clock(r.at) : `${day(r.at)} ${clock(r.at)}`;
  const what: string = r.what ? `：${r.what}` : '';
  if (r.running) return `Covey 正在自动回看${what}`;
  return r.at <= now ? `已到点，Covey 即将自动回看${what}` : `Covey 将于 ${when} 自动回看${what}`;
}

/** 这条定时回看页面上能不能取消：Covey 认 revisit_cancel（settings.ops）、带 set_at（v35）、Covey 还没开始回看 */
export const canCancelRevisit = (ops: readonly string[] | null | undefined, r: TopicRevisit | undefined): boolean =>
  canDo(ops, 'revisit_cancel') && !!r && typeof r.set_at === 'number' && r.set_at > 0 && !r.running;

/** 页面上刚取消掉的定时回看的标识（话题 + 预约时刻）：Covey 办好后再推新数据之前也不画它 */
export const revisitMark = (topicKey: string, setAt: number | undefined): string => `${topicKey}@${setAt ?? ''}`;

/** 一条代发草稿的那句话：“→ 张三：周报已更新…”，没发出去的说一声 */
export function draftWords(d: OwnerSendDraft): string {
  const to: string = d.to ? `→ ${d.to}` : '→ 收件人待定';
  const head: string = d.preview ? `：${d.preview.length > 40 ? `${d.preview.slice(0, 40)}…` : d.preview}` : '';
  return d.state === 'failed' ? `${to}${head}（没发出去，要在卡上再点一次）` : `${to}${head}`;
}

/** 完成标准那一行的摘要：“2/3 满足 · 1 条没满足”；全满足是“3/3 满足”；没有就是空串 */
export function criteriaSummary(list: readonly TurnCriterion[] | undefined): { text: string; unmet: number } {
  if (!list || !list.length) return { text: '', unmet: 0 };
  const met: number = list.filter((c: TurnCriterion) => c.state === '满足').length;
  const no: number = list.filter((c: TurnCriterion) => c.state === '没满足').length;
  const unchecked: number = list.length - met - no;
  const rest: string[] = [no ? `${no} 条没满足` : '', unchecked ? `${unchecked} 条没查` : ''].filter(Boolean);
  return { text: `${met}/${list.length} 满足${rest.length ? ` · ${rest.join(' · ')}` : ''}`, unmet: no + unchecked };
}

/** 改动那一行的几项（同飞书答案卡“改动 提交号 ｜ 第 N 代 ｜ 已自检”）：提交号取前 7 位，几个提交都列；部署写到哪；自检有话就写“已自检” */
export function deliveryBits(d: TurnDelivery | undefined): string[] {
  if (!d) return [];
  const commits: string[] = String(d.commit ?? '').split(/[\s,，、]+/u).filter(Boolean)
    .map((c: string) => (/^[0-9a-f]{8,40}$/iu.test(c) ? c.slice(0, 7) : c));
  return [commits.length ? `提交 ${commits.join(' ')}` : '', d.deployed ? `已部署：${d.deployed}` : '', d.verified ? '已自检' : ''].filter(Boolean);
}
