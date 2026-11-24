/** 侧栏的状态分组（T753，学 Cursor 的 Agents 窗口）：「要你处理」和「在做」两组排在专项上面，每行两行字：
 *  头一行是谁（话题的 T 号头像加标题，管家、负责人用头像），第二行灰字写要你定什么、停在哪、现在在做什么，右边是等了多久或做到第几步。
 *  要你处理和看板、侧栏角标同一口径（projectData.ts asks）：等你 → 停住了（含护栏停住的专项）→ 可能卡住。纯函数，单测在 scripts/status-groups.test.mjs。 */
import type { QuestionView, SnapshotProject, SnapshotResponse, SnapshotTopic } from '@shared/api.interface';
import type { Asks } from './projectData';
import { splitTitle } from './topicText';

export type GroupTone = 'waiting' | 'stopped' | 'stuck' | 'running';

export interface StatusRow {
  key: string;
  /** 点了去哪：话题页、大厅（管家）或专项页（负责人、护栏停住的专项） */
  to: string;
  kind: 'topic' | 'butler' | 'lead' | 'project';
  tone: GroupTone;
  title: string;
  /** 第二行灰字 */
  sub: string;
  number: number | null;
  /** 负责人、专项的头像名 */
  avatar?: string;
  /** 从什么时候等起（秒），右边写等了多久 */
  since?: number;
  /** 在做的：第几步/共几步 */
  plan?: string;
}

export interface StatusGroups {
  act: StatusRow[];
  running: StatusRow[];
}

type Snap = Pick<SnapshotResponse, 'topics' | 'projects' | 'questions'>;

const topicTo = (t: SnapshotTopic): string =>
  t.kind === 'butler' ? '/butler' : t.kind === 'lead' && t.project_key ? `/projects/${encodeURIComponent(t.project_key)}` : `/topics/${encodeURIComponent(t.key)}`;

function row(t: SnapshotTopic, tone: GroupTone, snap: Snap, qBy: Map<string, QuestionView>): StatusRow {
  const p: SnapshotProject | undefined = snap.projects.find((x: SnapshotProject) => x.key === t.project_key);
  const kind = t.kind === 'butler' ? 'butler' : t.kind === 'lead' ? 'lead' : 'topic';
  const title: string = kind === 'butler' ? '管家' : kind === 'lead' ? `${p?.title ?? '专项'} · 负责人` : t.title;
  const q: QuestionView | undefined = qBy.get(t.key);
  const phase: string = t.progress?.phase ?? '';
  let sub: string;
  let since: number | undefined = t.updated_at;
  if (tone === 'waiting') {
    sub = q?.questions[0]?.question ? `要你定：${q.questions[0].question}` : '在等你';
    since = q?.asked_at ?? t.updated_at;
  } else if (tone === 'stopped') {
    sub = `停住了：${t.latest_failure ? splitTitle(t.latest_failure.title)[0] : '上一轮没做完'}`;
  } else if (tone === 'stuck') {
    sub = phase ? `可能卡住 · ${phase}` : '可能卡住';
    since = t.progress?.last_activity_at ?? t.updated_at;
  } else {
    sub = phase || '在做';
    since = undefined;
  }
  const plan: string | undefined = tone === 'running' && t.progress?.plan_total ? `${t.progress.plan_done ?? 0}/${t.progress.plan_total}` : undefined;
  return { key: t.key, to: topicTo(t), kind, tone, title, sub, number: kind === 'topic' ? t.number ?? null : null, avatar: kind === 'lead' ? p?.avatar : undefined, since, plan };
}

/** 两组的行。running 由调用方给（话题自己的状态口径在 lib.ts toneOf，这里不重算） */
export function statusGroups(a: Asks, snap: Snap, running: SnapshotTopic[]): StatusGroups {
  const qBy = new Map<string, QuestionView>(snap.questions.filter((q: QuestionView) => q.state === 'open').map((q: QuestionView) => [q.topic_key, q]));
  const halted: StatusRow[] = a.projects.map((p: SnapshotProject): StatusRow => ({
    key: `p:${p.key}`, to: `/projects/${encodeURIComponent(p.key)}`, kind: 'project', tone: 'stopped', title: p.title,
    sub: `停住了：${p.status_reason || '护栏停住了'}`, number: null, avatar: p.avatar, since: p.updated_at,
  }));
  return {
    act: [
      ...a.waiting.map((t: SnapshotTopic) => row(t, 'waiting', snap, qBy)),
      ...a.stopped.map((t: SnapshotTopic) => row(t, 'stopped', snap, qBy)),
      ...halted,
      ...a.stuck.map((t: SnapshotTopic) => row(t, 'stuck', snap, qBy)),
    ],
    running: running.filter((t: SnapshotTopic) => !qBy.has(t.key)).map((t: SnapshotTopic) => row(t, 'running', snap, qBy)),
  };
}

/** 右边的“等了多久”：刚刚、N 分、N 小时、N 天 */
export function sinceWords(sec: number): string {
  if (sec < 60) return '刚刚';
  if (sec < 3600) return `${Math.floor(sec / 60)} 分`;
  if (sec < 86400) return `${Math.floor(sec / 3600)} 小时`;
  return `${Math.floor(sec / 86400)} 天`;
}
