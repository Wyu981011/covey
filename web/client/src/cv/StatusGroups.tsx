import React from 'react';
import { Link, useLocation } from 'react-router-dom';
import type { SnapshotResponse, SnapshotTopic } from '@shared/api.interface';
import { RoleAvatar, TopicBadge } from './RoleAvatar';
import { Dot } from './ui';
import type { Asks } from './projectData';
import { sinceWords, statusGroups, type StatusRow } from './statusGroups';

/** 每组最多列几行，多的写“还有 N 个”（要你处理的链到看板） */
const SHOWN = 6;

const Row: React.FC<{ r: StatusRow; now: number; on: boolean }> = ({ r, now, on }) => (
  <Link to={r.to} className={`ss-row${on ? ' on' : ''}`} title={`${r.title}\n${r.sub}`}>
    {r.kind === 'topic' ? (
      <span className="a-tlogo">
        <TopicBadge number={r.number} />
        <Dot tone={r.tone} />
      </span>
    ) : (
      <span className="ss-av">
        <RoleAvatar name={r.kind === 'butler' ? 'butler' : r.avatar} size={18} />
        <Dot tone={r.tone} />
      </span>
    )}
    <span className="ss-t">{r.title}</span>
    <span className="ss-m">{r.plan ?? (r.since ? sinceWords(Math.max(0, now - r.since)) : '')}</span>
    <span className="ss-s">{r.sub}</span>
  </Link>
);

/** 侧栏顶上的「要你处理」「在做」两组（statusGroups.ts）。两组都空时什么也不画 */
export const StatusGroups: React.FC<{ a: Asks; data: SnapshotResponse; running: SnapshotTopic[]; act: number; now: number }> = ({ a, data, running, act, now }) => {
  const loc = useLocation();
  const g = statusGroups(a, data, running);
  if (!g.act.length && !g.running.length) return null;
  const on = (r: StatusRow): boolean => loc.pathname === r.to;
  return (
    <div className="ss" aria-label="按状态">
      {g.act.length ? (
        <>
          <Link to="/" className="sec ss-h act" title="看板">
            <span>要你处理</span>
            <b>{act || g.act.length}</b>
          </Link>
          {g.act.slice(0, SHOWN).map((r: StatusRow) => <Row key={r.key} r={r} now={now} on={on(r)} />)}
          {g.act.length > SHOWN ? <Link to="/" className="ss-more">还有 {g.act.length - SHOWN} 件，在看板里</Link> : null}
        </>
      ) : null}
      {g.running.length ? (
        <>
          <div className="sec ss-h">
            <span>在做</span>
            <b>{g.running.length}</b>
          </div>
          {g.running.slice(0, SHOWN).map((r: StatusRow) => <Row key={r.key} r={r} now={now} on={on(r)} />)}
          {g.running.length > SHOWN ? <span className="ss-more">还有 {g.running.length - SHOWN} 个在做</span> : null}
        </>
      ) : null}
    </div>
  );
};
