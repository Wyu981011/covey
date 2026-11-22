import { useSyncExternalStore } from 'react';

/** 每个对话在页面里的小状态：滚动位置、草稿、刚发出还没回来的话。切换对话不丢；草稿另存进 localStorage。 */

export interface ScrollState {
  top: number;
  bottom: boolean;
}
const scrolls = new Map<string, ScrollState>();
export const getScroll = (key: string): ScrollState | undefined => scrolls.get(key);
export const setScroll = (key: string, s: ScrollState): void => {
  scrolls.set(key, s);
};

/** 草稿（T616）：内存里一份，另存进 localStorage，切换对话、刷新页面、关了再开都在；发出去或清空就删 */
const DRAFT_PREFIX = 'covey.draft.';
const DRAFT_DAYS = 14;
const drafts = new Map<string, string>();
function readStored(key: string): string {
  try {
    const raw: string | null = window.localStorage.getItem(DRAFT_PREFIX + key);
    if (!raw) return '';
    const v = JSON.parse(raw) as { text?: unknown; at?: unknown };
    if (typeof v.text !== 'string' || typeof v.at !== 'number' || Date.now() - v.at > DRAFT_DAYS * 86400000) return '';
    return v.text;
  } catch {
    return '';
  }
}
export const getDraft = (key: string): string => {
  if (!drafts.has(key)) drafts.set(key, readStored(key));
  return drafts.get(key) ?? '';
};
export const setDraft = (key: string, v: string): void => {
  drafts.set(key, v);
  try {
    if (v.trim()) window.localStorage.setItem(DRAFT_PREFIX + key, JSON.stringify({ text: v, at: Date.now() }));
    else window.localStorage.removeItem(DRAFT_PREFIX + key);
  } catch {
    /* 存不下（隐私模式、满了）就只在内存里 */
  }
};

/** 每个会话只发一次 seen */
const seenSent = new Set<string>();
export const markSeenSent = (key: string): boolean => {
  if (seenSent.has(key)) return false;
  seenSent.add(key);
  return true;
};

export interface Pending {
  id: string;
  text: string;
  at: number;
  /** 发出时这个话题已有的最大 seq；之后出现同文的 owner 轮就算回来了 */
  baseSeq: number;
  phase: 'sending' | 'sent' | 'failed';
  error?: string;
  /** v20：带的附件（只用来在气泡里列名字） */
  files?: { name: string; mime: string }[];
}

const EMPTY: Pending[] = [];
const pending = new Map<string, Pending[]>();
const listeners = new Set<() => void>();
const emit = (): void => listeners.forEach((l: () => void) => l());

export function addPending(key: string, p: Pending): void {
  pending.set(key, [...(pending.get(key) ?? EMPTY), p]);
  emit();
}
export function patchPending(key: string, id: string, patch: Partial<Pending>): void {
  const cur: Pending[] = pending.get(key) ?? EMPTY;
  pending.set(
    key,
    cur.map((p: Pending) => (p.id === id ? { ...p, ...patch } : p)),
  );
  emit();
}
export function removePending(key: string, ids: string[]): void {
  const cur: Pending[] = pending.get(key) ?? EMPTY;
  const next: Pending[] = cur.filter((p: Pending) => !ids.includes(p.id));
  if (next.length === cur.length) return;
  pending.set(key, next);
  emit();
}

export function usePending(key: string): Pending[] {
  return useSyncExternalStore(
    (cb: () => void) => {
      listeners.add(cb);
      return () => listeners.delete(cb);
    },
    () => pending.get(key) ?? EMPTY,
  );
}
