import React from 'react';
import { Link } from 'react-router-dom';
import { ChevronRight } from 'lucide-react';
import type { MemoryEntry, MemoryIndex, MemoryProjectData, MemoryTopicsData } from '@shared/api.interface';
import { useMemoryIndex, useMemoryKey } from '@client/src/hooks/use-workbench';
import { briefLine, briefOf, codeHref, type Brief } from './memoryCenter';
import './memorycenter.css';

/* 专项页、话题页右栏的精简记忆（数据约定 v43）：一行“记忆 · 规矩 6 · 在办决定 4 · 资料 31 ›”（点了去记忆中心那个范围），
   下面只列规矩和在办决定，各至多 6 条，每条点了去记忆中心那一条。数字口径同记忆中心（memoryCenter.ts briefOf）。
   没收到 memory:index（旧 Covey）时 useV43ProjectEntries / useV43TopicEntries 返回 null，调用方照旧画 v37 的面板。 */

/** 专项 id 的 v43 条目：index 里有 memory:p:<id> 就取，取到前是 undefined；不是 v43（或没这个专项的键）是 null */
export function useV43ProjectEntries(projectKey: string | null | undefined): MemoryEntry[] | null | undefined {
  const idx = useMemoryIndex();
  const index: MemoryIndex | null = idx.data?.data ?? null;
  const key: string = projectKey ? `memory:p:${projectKey}` : '';
  const rev: string | undefined = key ? index?.revs[key] : undefined;
  const q = useMemoryKey<MemoryProjectData>(rev ? key : null, rev);
  if (!index || !index.on || !rev) return idx.isLoading ? undefined : null;
  return q.data?.data?.entries ?? (q.isLoading ? undefined : []);
}

/** 话题的 v43 条目：从 memory:topics 里挑这个话题的（近 30 天有记忆的话题才在里面；不在里面是空数组） */
export function useV43TopicEntries(topicKey: string | null | undefined): MemoryEntry[] | null | undefined {
  const idx = useMemoryIndex();
  const index: MemoryIndex | null = idx.data?.data ?? null;
  const rev: string | undefined = index?.revs['memory:topics'];
  const q = useMemoryKey<MemoryTopicsData>(rev ? 'memory:topics' : null, rev);
  if (!index || !index.on) return idx.isLoading ? undefined : null;
  if (!rev) return [];
  const t = q.data?.data?.topics.find((x) => x.topic_key === topicKey);
  return t ? t.entries : q.isLoading ? undefined : [];
}

const Rows: React.FC<{ title: string; rows: MemoryEntry[]; total: number; more: string }> = ({ title, rows, total, more }) =>
  rows.length ? (
    <>
      <p className="ml-sec">{title}</p>
      {rows.map((e: MemoryEntry) => (
        <Link key={e.key} to={codeHref(e.code)} className="ml-row" title={e.text}>
          <span className="ml-t">{e.title}</span>
          {!e.carried_next ? <span className="mc-off short">下一轮不带</span> : null}
        </Link>
      ))}
      {total > rows.length ? <Link to={more} className="ml-more">全部 {total} 条 ›</Link> : null}
    </>
  ) : null;

/** 精简清单：scope 是记忆中心的范围（p:<专项 id> 或 topics） */
export const MemoryList: React.FC<{ entries: MemoryEntry[]; scope: string; title?: string }> = ({ entries, scope, title = '记忆' }) => {
  const b: Brief = briefOf(entries);
  const href: string = `/memory?scope=${encodeURIComponent(scope)}`;
  const line: string = briefLine(b);
  return (
    <div className="ml" data-testid="memory-list">
      <Link to={href} className="ml-head" title="在记忆中心看全部">
        <b>{title}</b>
        <span>{line || '还没有'}</span>
        <ChevronRight />
      </Link>
      <Rows title="规矩" rows={b.rules} total={b.counts.rules} more={`/memory/rules?scope=${encodeURIComponent(scope)}`} />
      <Rows title="在办的决定" rows={b.decisions} total={b.counts.decisions} more={`/memory/decisions?scope=${encodeURIComponent(scope)}`} />
    </div>
  );
};
