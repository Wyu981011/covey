import React, { useEffect } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { ArrowRight } from 'lucide-react';
import type { SearchHit, SnapshotTopic } from '@shared/api.interface';
import { prefetchTurns, useSearch, useSnapshot } from '@client/src/hooks/use-workbench';
import { shortTime } from '@client/src/lib/workbench-format';
import { Head } from './Shell';
import { Dot } from './ui';
import { toneOf, toneWord, topicNumberOf } from './lib';

const Marked: React.FC<{ text: string; q: string }> = ({ text, q }) => {
  const i: number = q ? text.toLowerCase().indexOf(q.toLowerCase()) : -1;
  if (i < 0) return <>{text}</>;
  return <>{text.slice(0, i)}<mark style={{ background: 'color-mix(in srgb,var(--wait) 30%,transparent)', color: 'inherit', borderRadius: 3 }}>{text.slice(i, i + q.length)}</mark>{text.slice(i + q.length)}</>;
};

const hitPath = (h: SearchHit): string => {
  const base: string = h.kind === 'butler' ? '/butler' : `/topics/${encodeURIComponent(h.topic_key)}`;
  return h.seq === null ? base : `${base}?seq=${h.seq}`;
};

/** 搜索：T 号直达那个话题；标题命中的话题排在前面，消息在后面。每条都是真实链接，能新标签打开 */
const SearchPage: React.FC = () => {
  const [params] = useSearchParams();
  const term: string = (params.get('q') ?? '').trim();
  const { data, isFetching } = useSearch(term);
  const { data: snap } = useSnapshot();
  const nav = useNavigate();
  const qc = useQueryClient();
  const num: number | null = topicNumberOf(term);
  const direct: SnapshotTopic | undefined = num === null ? undefined : snap?.topics.find((t: SnapshotTopic) => t.kind === 'topic' && t.number === num);
  const byKey = new Map<string, SnapshotTopic>((snap?.topics ?? []).map((t: SnapshotTopic) => [t.key, t]));
  const hits: SearchHit[] = (data ?? []).filter((h: SearchHit) => !(direct && h.seq === null && h.topic_key === direct.key));
  const topicHits: SearchHit[] = hits.filter((h: SearchHit) => h.seq === null);
  const msgHits: SearchHit[] = hits.filter((h: SearchHit) => h.seq !== null);
  const total: number = hits.length + (direct ? 1 : 0);
  // 页面上（不在输入框里）按回车：打开直达的那个话题
  useEffect(() => {
    if (!direct) return undefined;
    const on = (e: KeyboardEvent): void => {
      const tag: string = (e.target as HTMLElement | null)?.tagName ?? '';
      if (e.key === 'Enter' && tag !== 'INPUT' && tag !== 'TEXTAREA' && tag !== 'A' && tag !== 'BUTTON') nav(`/topics/${encodeURIComponent(direct.key)}`);
    };
    window.addEventListener('keydown', on);
    return () => window.removeEventListener('keydown', on);
  }, [direct, nav]);
  const state = (key: string): React.ReactNode => {
    const t: SnapshotTopic | undefined = byKey.get(key);
    if (!t) return null;
    const tn = toneOf(t);
    return <span className="a-sst"><Dot tone={tn} />{toneWord(tn)}</span>;
  };
  return (
    <div style={{ display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0 }}>
      <Head title="搜索" sub={term ? `“${term}” · ${isFetching && !data ? '搜索中…' : `${total} 条`}` : undefined} back={undefined} />
      <div className="scroll">
        <div className="col" style={{ paddingTop: 12 }}>
          {!term ? <p className="t3" style={{ padding: 24, textAlign: 'center' }}>输入关键词搜索话题标题和对话内容；输入 T 号（如 T514）回车直接打开那个话题。</p> : null}
          {direct ? (
            <Link
              to={`/topics/${encodeURIComponent(direct.key)}`}
              className="a-sdirect"
              onMouseEnter={() => prefetchTurns(qc, direct.key)}
              onTouchStart={() => prefetchTurns(qc, direct.key)}
            >
              <span className="a-sdl">打开</span>
              <span className="mono">T{direct.number}</span>
              <b>{direct.title}</b>
              {state(direct.key)}
              <ArrowRight />
              <span className="a-sdk">回车</span>
            </Link>
          ) : null}
          {data && !total && !isFetching ? <p className="t3" style={{ padding: 24, textAlign: 'center' }}>没有找到。</p> : null}
          {topicHits.length ? <h3 className="a-ssec">话题<em>{topicHits.length}</em></h3> : null}
          {topicHits.map((h: SearchHit, i: number) => (
            <Link key={`t:${h.topic_key}:${i}`} to={hitPath(h)} className="old a-shit" onMouseEnter={() => prefetchTurns(qc, h.topic_key)} onTouchStart={() => prefetchTurns(qc, h.topic_key)}>
              <div className="tl1">
                {h.number ? <span className="mono">T{h.number}</span> : null}
                <b><Marked text={h.title} q={term} /></b>
                {state(h.topic_key)}
                <span>{shortTime(h.at)}</span>
              </div>
            </Link>
          ))}
          {msgHits.length && (topicHits.length || direct) ? <h3 className="a-ssec">对话里提到<em>{msgHits.length}</em></h3> : null}
          {msgHits.map((h: SearchHit, i: number) => (
            <Link key={`m:${h.topic_key}:${h.seq}:${i}`} to={hitPath(h)} className="old a-shit" onMouseEnter={() => prefetchTurns(qc, h.topic_key)} onTouchStart={() => prefetchTurns(qc, h.topic_key)}>
              <div className="tl1">
                {h.number ? <span className="mono">T{h.number}</span> : null}
                <b>{h.title}</b>
                <span>{shortTime(h.at)}</span>
              </div>
              <p>{h.role === 'owner' ? (h.by === 'lead' ? '负责人：' : h.by === 'butler' ? '管家：' : '你：') : ''}<Marked text={h.snippet.replace(/[*`#>]+/gu, '')} q={term} /></p>
            </Link>
          ))}
        </div>
      </div>
    </div>
  );
};
export default SearchPage;
