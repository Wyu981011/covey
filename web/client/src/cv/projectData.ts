import type { ReportResponse, ReportTurn, SnapshotProject, SnapshotResponse, SnapshotTopic } from '@shared/api.interface';
import { cacheShare, closedAt, sinceOf } from './reportData';
import { PRESSING, type ToneKey } from './look.gen';
import { toneOf } from './lib';

export function leadOf(snap: SnapshotResponse, p: SnapshotProject): SnapshotTopic | undefined {
  return (
    snap.topics.find((t: SnapshotTopic) => t.kind === 'lead' && t.key === p.lead_topic_key) ??
    snap.topics.find((t: SnapshotTopic) => t.kind === 'lead' && t.project_key === p.key)
  );
}
export const ownTopics = (snap: SnapshotResponse, p: SnapshotProject): SnapshotTopic[] =>
  snap.topics.filter((t: SnapshotTopic) => t.kind === 'topic' && t.project_key === p.key);

export interface PerTopic {
  seconds: number;
  tokens: number;
}
export interface ProjectMetrics {
  work: number;
  tokens: number;
  cachePct: number | null;
  avgWait: number | null;
  questions: number;
  startedAt: number | null;
  per: Map<string, PerTopic>;
}

export function metrics(rep: ReportResponse | undefined, p: SnapshotProject, topics: SnapshotTopic[] = []): ProjectMetrics {
  const per = new Map<string, PerTopic>();
  let work = 0;
  let tokens = 0;
  let cache = 0;
  let inp = 0;
  let first: number | null = null;
  // 挂进专项的已有话题带着以前的轮次：话题算进专项（专项开始、它加入里晚的那个）以前就结束的不算（和报告、专项卡一致）
  const since: number | null = p.started_at;
  const byKey = new Map<string, SnapshotTopic>(topics.map((t: SnapshotTopic) => [t.key, t]));
  const ours = (x: ReportTurn): boolean => {
    const from: number | null = sinceOf(since, byKey.get(x.topic_key));
    return x.role !== 'owner' && (!from || !x.ended_at || x.ended_at >= from);
  };
  for (const t of (rep?.turns ?? []).filter(ours)) {
    const sec: number = t.seconds || (t.started_at && t.ended_at ? t.ended_at - t.started_at : 0);
    const tok: number = t.usage?.total ?? 0;
    const cur: PerTopic = per.get(t.topic_key) ?? { seconds: 0, tokens: 0 };
    cur.seconds += sec;
    cur.tokens += tok;
    per.set(t.topic_key, cur);
    if (t.kind !== 'lead') work += sec;
    tokens += tok;
    cache += t.usage?.cache_read ?? 0;
    inp += t.usage?.input ?? 0;
    if (t.started_at && (first === null || t.started_at < first)) first = t.started_at;
  }
  // 你答过的题各等了多久（负责人代答、关掉的不算你回得慢）
  const waits: number[] = (rep?.questions ?? [])
    .filter((q) => q.asked_at && closedAt(q) && ['owner', 'feedback', 'skipped'].includes(q.closed_by || (q.answered_at ? 'owner' : '')))
    .map((q) => (closedAt(q) ?? 0) - (q.asked_at ?? 0));
  return {
    work,
    tokens,
    cachePct: cacheShare(cache, inp),
    avgWait: waits.length ? waits.reduce((a: number, b: number) => a + b, 0) / waits.length : null,
    questions: rep?.questions.length ?? 0,
    startedAt: p.started_at ?? first,
    per,
  };
}

/** 专项的胶囊：话题里最急的那件（look 的 PRESSING；话题按列表里的颜色传进来，负责人按它自己的）；都不急时是专项自己的状态，灰色 */
export function projectPill(p: SnapshotProject, tones: ToneKey[], lead: SnapshotTopic | undefined): { tone: ToneKey; text: string | undefined } {
  const all: ToneKey[] = lead ? [...tones, toneOf(lead)] : tones;
  const tone: ToneKey = PRESSING.find((k: ToneKey) => all.includes(k)) ?? 'idle';
  return { tone, text: tone === 'idle' ? p.status : undefined };
}

/** 按状态数话题：要紧的在前、做完在后，已停止、空闲、排队不单列；只留有的 */
const COUNTED: readonly ToneKey[] = ['waiting', 'stopped', 'stuck', 'result', 'running', 'done'];
export function toneCounts(tones: ToneKey[]): [ToneKey, number][] {
  return COUNTED.map((k: ToneKey): [ToneKey, number] => [k, tones.filter((v: ToneKey) => v === k).length]).filter(([, n]) => n > 0);
}

export type { ReportTurn };
