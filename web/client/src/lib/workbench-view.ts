import type { SnapshotProject, SnapshotResponse, SnapshotTopic } from '@shared/api.interface';

/** 专项里的话题：负责人排第一，其余按最近更新 */
export function projectTopics(snap: SnapshotResponse, p: SnapshotProject): SnapshotTopic[] {
  const own: SnapshotTopic[] = snap.topics.filter((t: SnapshotTopic) => t.project_key === p.key);
  return own.sort((a: SnapshotTopic, b: SnapshotTopic) => {
    if (a.key === p.lead_topic_key) return -1;
    if (b.key === p.lead_topic_key) return 1;
    return b.updated_at - a.updated_at;
  });
}

/** 默认选中：先等你的，再在做的，再最近更新的 */
export function defaultTopic(own: SnapshotTopic[]): SnapshotTopic | undefined {
  const byTime = (a: SnapshotTopic, b: SnapshotTopic): number => b.updated_at - a.updated_at;
  const pick = (state: string): SnapshotTopic | undefined => own.filter((t: SnapshotTopic) => t.state === state).sort(byTime)[0];
  return pick('等你') ?? pick('在做') ?? [...own].sort(byTime)[0];
}

/** 不属于任何（现存）专项的话题，新的在前；管家不算 */
export function looseTopics(snap: SnapshotResponse): SnapshotTopic[] {
  const keys = new Set<string>(snap.projects.map((p: SnapshotProject) => p.key));
  return snap.topics
    .filter((t: SnapshotTopic) => t.kind === 'topic' && (!t.project_key || !keys.has(t.project_key)))
    .sort((a: SnapshotTopic, b: SnapshotTopic) => b.updated_at - a.updated_at);
}

/** 等你：状态是等你的话题，加上有 open 问题的话题 */
export function waitingTopics(snap: SnapshotResponse): SnapshotTopic[] {
  const asked = new Set<string>(snap.questions.map((q) => q.topic_key));
  return snap.topics.filter((t: SnapshotTopic) => t.kind === 'topic' && (t.state === '等你' || asked.has(t.key)));
}
