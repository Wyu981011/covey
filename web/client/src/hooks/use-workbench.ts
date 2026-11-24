import { keepPreviousData, useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query';
import { useEffect, useMemo } from 'react';
import type {
  OutboxRequest,
  OutboxResponse,
  ReportResponse,
  RoomResponse,
  SearchHit,
  SettingsResponse,
  TidyResponse,
  StatsResponse,
  UsageResponse,
  SnapshotResponse,
  SnapshotTopic,
  TurnView,
  TurnsResponse, MainMemoryResponse } from '@shared/api.interface';
import { fetchMe, fetchReport, fetchRoom, fetchSearch, fetchSettings, fetchStats, fetchTidy, fetchMemory, fetchSnapshot, fetchTurns, fetchUsage, postOutbox } from '@client/src/api/workbench';
import { mergeCollabs } from '@client/src/cv/collab';

/** 所有列表来自同一份快照，每 2 秒轮询一次 */
export const POLL_MS = 2000;
const KEEP_MS = 30 * 60 * 1000;

export const SNAPSHOT_KEY = ['snapshot'] as const;
export const turnsKey = (key: string): readonly unknown[] => ['turns', key];

/** 当前登录的人（头像用）；取不到就是 null，页面画中性图标 */
export const useMe = () =>
  useQuery<{ name: string | null }>({ queryKey: ['me'], queryFn: fetchMe, staleTime: Infinity, gcTime: Infinity, retry: 1 });

export const useSnapshot = () =>
  useQuery<SnapshotResponse>({
    queryKey: SNAPSHOT_KEY,
    queryFn: fetchSnapshot,
    refetchInterval: POLL_MS,
    staleTime: 1000,
    gcTime: KEEP_MS,
  });

/** 编号 → 话题（正文里 T12 链到它） */
export function useTopicByNumber(): Map<number, SnapshotTopic> {
  const { data } = useSnapshot();
  return useMemo(() => {
    const m = new Map<number, SnapshotTopic>();
    for (const t of data?.topics ?? []) if (t.number !== null && t.kind === 'topic') m.set(t.number, t);
    return m;
  }, [data]);
}

/** 增量取数的起点：最大 seq；最近几轮里还有在跑/等回答的，从它前一轮开始，好让它的最终正文覆盖旧的 */
export function afterOf(prev: TurnsResponse | undefined): number | null {
  if (!prev || !prev.turns.length) return null;
  const turns: TurnView[] = prev.turns;
  const maxSeq: number = turns[turns.length - 1].seq;
  const live: TurnView | undefined = turns.slice(-5).find((t: TurnView) => t.status === 'running' || t.status === 'waiting');
  return live ? Math.min(maxSeq, live.seq - 1) : maxSeq;
}

export async function fetchMerged(qc: QueryClient, key: string): Promise<TurnsResponse> {
  const prev: TurnsResponse | undefined = qc.getQueryData<TurnsResponse>(turnsKey(key));
  const res: TurnsResponse = await fetchTurns(key, afterOf(prev));
  if (!prev) return res;
  const byKey = new Map<string, TurnView>(prev.turns.map((t: TurnView) => [t.key, t]));
  for (const t of res.turns) byKey.set(t.key, t);
  const turns: TurnView[] = [...byKey.values()].sort((a: TurnView, b: TurnView) => a.seq - b.seq);
  // v31：协作增量只带还开着的和最近动过的：按 key 合并进上一份
  const collabs = prev.collabs || res.collabs ? mergeCollabs(prev.collabs, res.collabs) : undefined;
  return { ...res, turns, ...(collabs?.length ? { collabs } : {}) };
}

/** 一个话题的对话：合并进每话题自己的缓存；没有缓存时先拿快照里的头部当占位，不出骨架 */
export function useTurns(key: string) {
  const qc: QueryClient = useQueryClient();
  return useQuery<TurnsResponse>({
    queryKey: turnsKey(key),
    queryFn: () => fetchMerged(qc, key),
    refetchInterval: POLL_MS,
    staleTime: 1000,
    gcTime: KEEP_MS,
    placeholderData: (prev: TurnsResponse | undefined): TurnsResponse | undefined => {
      if (prev && prev.topic.key === key) return prev;
      const snap: SnapshotResponse | undefined = qc.getQueryData<SnapshotResponse>(SNAPSHOT_KEY);
      const t: SnapshotTopic | undefined = snap?.topics.find((x: SnapshotTopic) => x.key === key);
      if (!t) return undefined;
      return { topic: { ...t, workspace: '', project_title: null }, turns: [], question: null, outbox: [] };
    },
  });
}

export const ROOM_KEY = ['room'] as const;

/** 大厅的几路轮次：按 cursor 增量取，按 key 合并（同一轮的新内容覆盖旧的），发件取最新的 */
export function useRoomTurns(enabled = true) {
  const qc: QueryClient = useQueryClient();
  return useQuery<RoomResponse>({
    queryKey: ROOM_KEY,
    queryFn: async (): Promise<RoomResponse> => {
      const prev: RoomResponse | undefined = qc.getQueryData<RoomResponse>(ROOM_KEY);
      const res: RoomResponse = await fetchRoom(prev?.cursor ?? null);
      if (!prev || prev.butler_key !== res.butler_key) return res;
      const byKey = new Map<string, TurnView>(prev.turns.map((t: TurnView) => [t.key, t]));
      for (const t of res.turns) byKey.set(t.key, t);
      const collabs = prev.collabs || res.collabs ? mergeCollabs(prev.collabs, res.collabs) : undefined;
      return { ...res, turns: [...byKey.values()], cursor: res.cursor ?? prev.cursor, ...(collabs?.length ? { collabs } : {}) };
    },
    enabled,
    refetchInterval: POLL_MS,
    staleTime: 1000,
    gcTime: KEEP_MS,
  });
}

/** 鼠标移上去、手指一按就先取，点进去时已经在缓存里 */
export function prefetchTurns(qc: QueryClient, key: string): void {
  if (!key) return;
  void qc.prefetchQuery({ queryKey: turnsKey(key), queryFn: () => fetchMerged(qc, key), staleTime: 5000, gcTime: KEEP_MS });
}

/** 快照一到就把要紧的话题先取好（等你、在做、没看过的、最近的几个），点进去时已在缓存里 */
export function useWarmup(): void {
  const qc: QueryClient = useQueryClient();
  const { data } = useSnapshot();
  const keys: string = useMemo(() => {
    const ts: SnapshotTopic[] = [...(data?.topics ?? [])].sort((a: SnapshotTopic, b: SnapshotTopic) => b.updated_at - a.updated_at);
    const hot: SnapshotTopic[] = ts.filter((t: SnapshotTopic) => t.state === '等你' || t.state === '在做' || t.unseen || t.kind === 'butler');
    const rest: SnapshotTopic[] = ts.filter((t: SnapshotTopic) => !hot.includes(t)).slice(0, 8);
    return [...hot, ...rest].slice(0, 24).map((t: SnapshotTopic) => t.key).join(',');
  }, [data]);
  useEffect(() => {
    const list: string[] = keys.split(',').filter(Boolean);
    const timers: number[] = list.map((k: string, i: number) => window.setTimeout(() => prefetchTurns(qc, k), 150 * i));
    return () => timers.forEach((t: number) => window.clearTimeout(t));
  }, [keys, qc]);
}

export const useSearch = (q: string) =>
  useQuery<SearchHit[]>({
    queryKey: ['search', q],
    queryFn: () => fetchSearch(q),
    enabled: q.trim().length > 0,
    placeholderData: keepPreviousData,
    staleTime: 10000,
  });

export const useSendOutbox = () => {
  const qc: QueryClient = useQueryClient();
  return useMutation<OutboxResponse, Error, OutboxRequest>({
    mutationFn: (body: OutboxRequest) => postOutbox(body),
    retry: false,
    onSuccess: (_res: OutboxResponse, vars: OutboxRequest) => {
      // 只刷这个话题和快照，不动别的
      if (vars.topic_key) void qc.invalidateQueries({ queryKey: turnsKey(vars.topic_key) });
      if (vars.payload?.room === true) void qc.invalidateQueries({ queryKey: ROOM_KEY });
      void qc.invalidateQueries({ queryKey: SNAPSHOT_KEY });
    },
  });
};

export function newOpId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
}

/** 不在乎结果的一次性发件（seen）：失败了也不打扰 */
export function postOutboxQuiet(body: OutboxRequest): void {
  postOutbox(body).catch(() => undefined);
}

export const useStats = () =>
  useQuery<StatsResponse>({ queryKey: ['stats'], queryFn: fetchStats, refetchInterval: 15000, staleTime: 10000, gcTime: KEEP_MS });

/** v26：按天的用量。Covey 每分钟推一次，这里一分钟取一次 */
export const useUsage = () =>
  useQuery<UsageResponse | null>({ queryKey: ['usage'], queryFn: fetchUsage, refetchInterval: 60000, staleTime: 30000, gcTime: KEEP_MS });

export const useReport = (key: string) =>
  useQuery<ReportResponse>({
    queryKey: ['report', key],
    queryFn: () => fetchReport(key),
    refetchInterval: 10000,
    staleTime: 5000,
    gcTime: KEEP_MS,
    placeholderData: keepPreviousData,
  });

export const SETTINGS_KEY = ['settings'] as const;
/** v7 设置页：打开时每 10 秒拉一次；改完另外隔 1.5 秒、4 秒各拉一次（见 Settings.tsx） */
export const useSettings = () =>
  useQuery<SettingsResponse | null>({
    queryKey: SETTINGS_KEY,
    queryFn: fetchSettings,
    refetchInterval: 10000,
    staleTime: 3000,
    gcTime: KEEP_MS,
  });

export const TIDY_KEY = ['tidy'] as const;
export const MEMORY_KEY = ['memory'] as const;
/** v16 整理专项的建议：看板上每 10 秒拉一次；点完按钮另外隔 1.5 秒、4 秒各拉一次（见 Tidy.tsx） */
export const useTidy = () =>
  useQuery<TidyResponse>({ queryKey: TIDY_KEY, queryFn: fetchTidy, refetchInterval: 10000, staleTime: 3000, gcTime: KEEP_MS });
/** v37：主记忆（设置页「记忆」）；改了以后 Covey 回执之前就推，页面收到 done 再取一次 */
export const useMemory = () =>
  useQuery<MainMemoryResponse | null>({ queryKey: MEMORY_KEY, queryFn: fetchMemory, refetchInterval: 30000, staleTime: 3000, gcTime: KEEP_MS });
