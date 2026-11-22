import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Search, Users } from 'lucide-react';
import { useSnapshot } from '@client/src/hooks/use-workbench';
import { TOPIC } from '@shared/collab';
import { candidates, mentionInfo, searchCandidates, type Candidate } from './collab';
import { requestMention } from './MentionNode';
import { Who } from './RoomBits';
import './collab.css';

/** 没搜的时候“最近话题”列几个 */
const RECENT = 12;

/**
 * 大厅页头右侧的「成员 N」：点开有搜索框，分组列管家、各专项负责人、最近话题（头像、状态）；
 * 点一位就在输入框光标处插入一枚 @ 胶囊（交给 Conversation 的输入框）。N 是管家加没结束的专项的负责人。
 */
export const MemberMenu: React.FC = () => {
  const { data: snap } = useSnapshot();
  const [open, setOpen] = useState<boolean>(false);
  const [q, setQ] = useState<string>('');
  const box = useRef<HTMLDivElement>(null);
  const field = useRef<HTMLInputElement>(null);
  const list: Candidate[] = useMemo(() => candidates(snap), [snap]);
  const butler: string | null = snap?.butler_key ?? null;
  const close = useCallback(() => {
    setOpen(false);
    setQ('');
  }, []);
  useEffect(() => {
    if (!open) return undefined;
    field.current?.focus();
    const away = (e: MouseEvent): void => {
      if (!box.current?.contains(e.target as Node)) close();
    };
    const esc = (e: KeyboardEvent): void => {
      if (e.key === 'Escape') close();
    };
    document.addEventListener('mousedown', away);
    document.addEventListener('keydown', esc);
    return () => {
      document.removeEventListener('mousedown', away);
      document.removeEventListener('keydown', esc);
    };
  }, [open, close]);
  const people: Candidate[] = list.filter((c: Candidate) => c.role !== TOPIC);
  const shown: Candidate[] = q.trim() ? searchCandidates(list, q, 40) : [...people, ...list.filter((c: Candidate) => c.role === TOPIC).slice(0, RECENT)];
  const groups: { name: string; rows: Candidate[] }[] = [
    { name: '管家', rows: shown.filter((c: Candidate) => c.role === 'butler') },
    { name: '专项负责人', rows: shown.filter((c: Candidate) => c.role === 'lead') },
    { name: q.trim() ? '话题' : '最近话题', rows: shown.filter((c: Candidate) => c.role === TOPIC) },
  ].filter((g: { rows: Candidate[] }) => g.rows.length > 0);
  const pick = (c: Candidate): void => {
    const i = mentionInfo(c.key, snap, butler);
    requestMention({ key: c.key, kind: i.kind, label: i.label, ...(i.avatar ? { avatar: i.avatar } : {}), number: i.number ?? null });
    close();
  };
  if (!snap) return null;
  return (
    <div className="mm" ref={box}>
      <button
        type="button"
        className={`mm-btn${open ? ' on' : ''}`}
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        aria-haspopup="dialog"
        title="成员：点一位，在输入框里 @ 它"
        data-testid="member-btn"
      >
        <Users />成员<span className="mm-n">{people.length}</span>
      </button>
      {open ? (
        <div className="mm-pop" role="dialog" aria-label="成员" data-testid="member-pop">
          <label className="mm-search">
            <Search />
            <input ref={field} value={q} onChange={(e: React.ChangeEvent<HTMLInputElement>) => setQ(e.target.value)} placeholder="找人：名字，话题按 T 号或标题" aria-label="找成员" />
          </label>
          <div className="mm-list">
            {groups.length ? groups.map((g: { name: string; rows: Candidate[] }) => (
              <div className="mm-grp" key={g.name}>
                <div className="mm-gh">{g.name}</div>
                {g.rows.map((c: Candidate) => (
                  <button type="button" className={`mm-row${c.dim ? ' dim' : ''}`} key={c.key} onClick={() => pick(c)} data-key={c.key}>
                    <Who info={mentionInfo(c.key, snap, butler)} />
                    <span className="mm-t">{c.role === TOPIC ? c.title : ''}</span>
                    <span className="mm-s t3">{c.role === TOPIC ? c.state : c.dim ? '收起了' : ''}</span>
                  </button>
                ))}
              </div>
            )) : <p className="t3 mm-none">没找到：管家、负责人按名字，话题按 T 号或标题找</p>}
          </div>
        </div>
      ) : null}
    </div>
  );
};
