/* 由 scripts/gen-look.mjs 从 look.json（covey scripts/export_look.py）生成，不要手改 */
/** 状态词表的 key（core/look.py STATES，网页数据约定 v5 topic.tone） */
export type ToneKey = 'waiting' | 'stopped' | 'stuck' | 'result' | 'running' | 'queued' | 'done' | 'cancelled' | 'idle';
/** act 要你处理，tell 告诉你一声，back 背景 */
export type ToneGroup = 'act' | 'tell' | 'back';
export interface StateLook {
  word: string;
  heading: string;
  group: ToneGroup;
  web: string;
}
export const STATES: Record<ToneKey, StateLook> = {
  waiting: { word: "等你", heading: "等你", group: 'act', web: '#F5A524' },
  stopped: { word: "停住了", heading: "停住了", group: 'act', web: '#F2555A' },
  stuck: { word: "可能卡住", heading: "可能卡住", group: 'act', web: '#F5A524' },
  result: { word: "有结果", heading: "有结果没看", group: 'tell', web: '#3DD68C' },
  running: { word: "在做", heading: "在做", group: 'back', web: '#4C9AFF' },
  queued: { word: "排队", heading: "排队", group: 'back', web: '#5B6270' },
  done: { word: "做完", heading: "做完", group: 'back', web: '#5B6270' },
  cancelled: { word: "已停止", heading: "已停止", group: 'back', web: '#5B6270' },
  idle: { word: "空闲", heading: "空闲", group: 'back', web: '#5B6270' },
};
export const TONE_KEYS: readonly ToneKey[] = ['waiting', 'stopped', 'stuck', 'result', 'running', 'queued', 'done', 'cancelled', 'idle'];
/** 最急的那件在前：结论带先说它 */
export const PRESSING: readonly ToneKey[] = ['waiting', 'stopped', 'stuck', 'result', 'running'];
export const PROJECT: StateLook = { word: "专项", heading: "专项", group: 'back', web: '#A78BFA' };
export const BRAND: string = '#7C83FF';
/** 话题的身份色（core/look.py TOPIC_COLORS）：T 号头像的底色，深浅模式同一个，上面是白字；只分清是哪个话题，不说状态 */
export const TOPIC_COLORS: readonly string[] = ['#BE185D', '#C2410C', '#A16207', '#4D7C0F', '#15803D', '#0F766E', '#0369A1', '#1D4ED8', '#4F46E5', '#6D28D9', '#A21CAF', '#475569'];
/** 号码 × TOPIC_STEP 模颜色数取色：相邻的号码颜色一定不同（core/look.py topic_color） */
export const TOPIC_STEP: number = 5;
/** 话题头像（T 号）的底色，同 core/look.py topic_color：号码 × TOPIC_STEP 模 TOPIC_COLORS 的个数，相邻号码颜色一定不同、连着 12 个不重样；
 *  没有号码（null、0）是 null */
export function topicColor(number: number | null | undefined): string | null {
  if (typeof number !== 'number' || !Number.isFinite(number) || number < 1) return null;
  return TOPIC_COLORS[(Math.trunc(number) * TOPIC_STEP) % TOPIC_COLORS.length] ?? null;
}
