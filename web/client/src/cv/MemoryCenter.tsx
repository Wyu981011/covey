import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { Check, ChevronRight, Eye, Import, MoreHorizontal, Plus, Search, X } from 'lucide-react';
import type {
  MemoryEditPayloadV43,
  MemoryEntry,
  MemoryGlobalData,
  MemoryImportItem,
  MemoryImportPage,
  MemoryIndex,
  MemoryKind,
  MemoryLogItem,
  MemoryPreview,
  MemoryPreviewsData,
  MemoryProjectData,
  MemoryReviewItem,
  MemoryScopeSummary,
  MemoryTab,
  MemoryTopicsData,
} from '@shared/api.interface';
import { newOpId, useMemoryIndex, useMemoryKeys, useMemoryMode } from '@client/src/hooks/use-workbench';
import { Head } from './Shell';
import { MainMemory } from './MainMemory';
import { sendOp, type OpResult } from './sendOp';
import { opWords } from './opWords';
import {
  HEALTH_OK, KIND_WORD, TABS, TAB_KIND, TAB_NOTE, TAB_WORD,
  acceptOp, allOp, archiveOp, decisionCounts, defaultTab, draftProblem, editOp, healthRows, ignoreOp, importChecked, importGroups, importMeta,
  importOp, isTab, keepOp, keysToLoad, limitsOf, locate, logLine, metaLine, mmdd, moveOp, poolOf, previewSections, projectKeyOf, promoteOp,
  promoteTarget, rejectOp, restoreOp, reviewItems, reviewMeta, roomOf, scopeOptions, shelved, tabEntries, titleIndex, undoOp, voidOp, addOp,
  charCount, headCounts, type DecisionView, type HealthRow, type Place, type Pool, type ScopeFilter,
} from './memoryCenter';
import './memorycenter.css';

/* 记忆中心（数据约定 v43，路由 /memory、/memory/:tab）。侧栏「记忆」只轮询小键 memory:index（角标是待审核数）；这一页按 index.revs
   取 memory:global、memory:topics、各 memory:p:<专项>，打开预览才取 memory:previews，打开导入才取那一页 memory:import:<页>。
   没收到 memory:index（旧 Covey 只推 v37 的 memory）时整页退回原来的主记忆页（MainMemory）。
   做减法（FINAL-SPEC 修订 11）：5 个页签，「导入」在顶栏；体检只画非 0 项；决定默认只看在办；灰字不重复页签说过的；行尾只有「改」和 ⋯。 */

/* ---------- 发一条 memory_edit ---------- */
interface Receipt {
  phase: 'sending' | 'done' | 'failed';
  message: string;
}
function useMemoryOp(): (payload: MemoryEditPayloadV43) => Promise<OpResult> {
  const qc = useQueryClient();
  return useCallback(async (payload: MemoryEditPayloadV43): Promise<OpResult> => {
    // 回执后跟踪器重取 ['memory', …] 下所有开着的查询（index 和各数据键）；等取回来再返回，页面上已经是新的
    const r: OpResult = await sendOp({ op_id: newOpId(), kind: 'memory_edit', payload: payload as unknown as Record<string, unknown> }, qc);
    if (r.settled) await r.settled;
    return r;
  }, [qc]);
}
const failWords = (r: OpResult): string => (r.phase === 'done' ? '' : opWords(r.phase === 'timeout' ? 'timeout' : r.phase, r.message));

/** 页面里共用的：池子、范围、发操作、回执、页面级提示（带撤销） */
interface Ctx {
  pool: Pool;
  index: MemoryIndex;
  scope: ScopeFilter;
  view: DecisionView;
  receipts: Record<string, Receipt>;
  run: (id: string, payload: MemoryEditPayloadV43, notice?: string) => Promise<boolean>;
  focus: string;
  editing: string;
  setEditing: (key: string) => void;
}

/* ---------- 零件 ---------- */
const Counter: React.FC<{ n: number; max: number }> = ({ n, max }) => <span className={`mc-count${n > max ? ' over' : ''}`}>{n}/{max}</span>;

const ReceiptLine: React.FC<{ r?: Receipt }> = ({ r }) => {
  if (!r) return null;
  if (r.phase === 'sending') return <div className="mc-rc">发送中…</div>;
  return <div className={`mc-rc${r.phase === 'failed' ? ' bad' : ''}`} role={r.phase === 'failed' ? 'alert' : 'status'}>{r.message}</div>;
};

/** 标题、正文、原因的编辑框；add 时多两个下拉（类别、范围）。⌘/Ctrl+Enter 存，Esc 取消 */
const Editor: React.FC<{
  index: MemoryIndex;
  init: { title: string; text: string; why?: string; kind: MemoryKind };
  places?: { value: string; label: string }[];
  place?: string;
  saveWord: string;
  busy: boolean;
  onSave: (d: { title: string; text: string; why: string; kind: MemoryKind; place: string }) => void;
  onCancel: () => void;
}> = ({ index, init, places, place, saveWord, busy, onSave, onCancel }) => {
  const [title, setTitle] = useState<string>(init.title);
  const [text, setText] = useState<string>(init.text);
  const [why, setWhy] = useState<string>(init.why ?? '');
  const [kind, setKind] = useState<MemoryKind>(init.kind);
  const [to, setTo] = useState<string>(place ?? 'global');
  const [whyOpen, setWhyOpen] = useState<boolean>(!!init.why);
  const lim = limitsOf(index, kind);
  const problem: string = draftProblem({ title, text, why }, lim);
  const save = (): void => {
    if (!problem && !busy) onSave({ title, text, why, kind, place: to });
  };
  const keys = (e: React.KeyboardEvent): void => {
    if (e.key === 'Escape') onCancel();
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) save();
  };
  return (
    <div className="mc-ed" onKeyDown={keys}>
      {places ? (
        <div className="mc-ed-row">
          <select className="mc-sel" value={kind} onChange={(e: React.ChangeEvent<HTMLSelectElement>) => setKind(e.target.value as MemoryKind)} aria-label="记成">
            {(['rule', 'decision', 'note'] as MemoryKind[]).map((k: MemoryKind) => <option key={k} value={k}>{KIND_WORD[k]}</option>)}
          </select>
          <select className="mc-sel" value={to} onChange={(e: React.ChangeEvent<HTMLSelectElement>) => setTo(e.target.value)} aria-label="记在哪">
            {places.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
          </select>
        </div>
      ) : null}
      <label className="mc-field">
        <input value={title} autoFocus maxLength={lim.title + 20} placeholder="标题（一句话说清是什么）" aria-label="标题" onChange={(e: React.ChangeEvent<HTMLInputElement>) => setTitle(e.target.value)} />
        <Counter n={charCount(title.trim())} max={lim.title} />
      </label>
      <label className="mc-field area">
        <textarea value={text} rows={3} placeholder="正文" aria-label="正文" onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) => setText(e.target.value)} />
        <Counter n={charCount(text.trim())} max={lim.text} />
      </label>
      {whyOpen ? (
        <label className="mc-field">
          <input value={why} placeholder="为什么（可不写）" aria-label="原因" onChange={(e: React.ChangeEvent<HTMLInputElement>) => setWhy(e.target.value)} />
          <Counter n={charCount(why.trim())} max={lim.why} />
        </label>
      ) : null}
      <div className="mc-ed-foot">
        {whyOpen ? null : <button type="button" className="mc-link" onClick={() => setWhyOpen(true)}>加原因</button>}
        <span className="mc-why">{problem && (title || text) ? problem : ''}</span>
        <button type="button" className="mc-btn" onClick={onCancel} disabled={busy}>取消</button>
        <button type="button" className="mc-btn pri" onClick={save} disabled={!!problem || busy} data-testid="memory-save">{busy ? '发送中…' : saveWord}</button>
      </div>
    </div>
  );
};

/** ⋯ 菜单：点外面、Esc 收起 */
const More: React.FC<{ items: { word: string; danger?: boolean; on: () => void }[]; label: string }> = ({ items, label }) => {
  const [open, setOpen] = useState<boolean>(false);
  const box = useRef<HTMLSpanElement | null>(null);
  useEffect(() => {
    if (!open) return undefined;
    const away = (e: MouseEvent): void => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    };
    const esc = (e: KeyboardEvent): void => {
      if (e.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', away);
    document.addEventListener('keydown', esc);
    return () => {
      document.removeEventListener('mousedown', away);
      document.removeEventListener('keydown', esc);
    };
  }, [open]);
  if (!items.length) return null;
  return (
    <span className="mc-more" ref={box}>
      <button type="button" className="mc-ic" aria-label={label} aria-expanded={open} onClick={() => setOpen(!open)}><MoreHorizontal /></button>
      {open ? (
        <span className="mc-menu" role="menu">
          {items.map((it) => (
            <button key={it.word} type="button" role="menuitem" className={it.danger ? 'danger' : ''} onClick={() => { setOpen(false); it.on(); }}>{it.word}</button>
          ))}
        </span>
      ) : null}
    </span>
  );
};

/** 记在哪的选项：全局、各专项（话题范围的条目只能从话题里记，这里不列） */
function placeOptions(pool: Pool, index: MemoryIndex): { value: string; label: string }[] {
  const out: { value: string; label: string }[] = [{ value: 'global', label: '全局' }];
  for (const s of index.scopes) if (s.key.startsWith('p:')) out.push({ value: s.key, label: s.title || pool.projects[s.key.slice(2)] || s.key });
  return out;
}
const placeFromValue = (v: string): Place => (v.startsWith('p:') ? { scope: 'project', project_key: v.slice(2) } : { scope: 'global' });
const placeValue = (e: Pick<MemoryEntry, 'scope' | 'project_key'>): string => (e.scope === 'project' ? `p:${e.project_key ?? ''}` : e.scope === 'global' ? 'global' : 'topic');

/* ---------- 一条 ---------- */
const EntryRow: React.FC<{ e: MemoryEntry; ctx: Ctx; shelf?: boolean }> = ({ e, ctx, shelf }) => {
  const [open, setOpen] = useState<boolean>(ctx.focus === e.code);
  const [moving, setMoving] = useState<boolean>(false);
  const editing: boolean = ctx.editing === e.key;
  const r: Receipt | undefined = ctx.receipts[e.key];
  const busy: boolean = r?.phase === 'sending';
  const meta: string[] = metaLine(e, { scope: ctx.scope, view: ctx.view, pool: ctx.pool });
  const up: Place | null = promoteTarget(e);
  const upWord: string = up ? (up.scope === 'global' ? '提到全局' : `提到专项「${ctx.pool.projects[up.project_key ?? ''] || '专项'}」`) : '';
  const items = shelf
    ? [{ word: '放回', on: () => void ctx.run(e.key, restoreOp(e), '已放回') }]
    : [
        ...(up ? [{ word: upWord, on: () => void ctx.run(e.key, promoteOp(e, up), '已换范围') }] : []),
        ...(e.scope !== 'topic' ? [{ word: '换范围…', on: () => setMoving(true) }] : []),
        { word: '归档', on: () => void ctx.run(e.key, archiveOp(e), '已归档') },
        { word: '作废', danger: true, on: () => void ctx.run(e.key, voidOp(e), '已作废') },
      ];
  useEffect(() => {
    if (ctx.focus === e.code) {
      setOpen(true);
      window.requestAnimationFrame(() => document.getElementById(`mc-${e.code}`)?.scrollIntoView({ block: 'center' }));
    }
  }, [ctx.focus, e.code]);
  return (
    <li className={`mc-row${ctx.focus === e.code ? ' hit' : ''}${shelf ? ' shelf' : ''}`} id={`mc-${e.code}`}>
      <div className="mc-line">
        <button type="button" className="mc-main" aria-expanded={open} onClick={() => setOpen(!open)}>
          <span className="mc-t1">
            <span className="mc-title">{e.title}</span>
            {!e.carried_next && !shelf ? <span className="mc-off short">下一轮不带</span> : null}
            {shelf ? <span className="mc-off short">{e.status === 'void' ? '已作废' : '已归档'}</span> : null}
          </span>
          <span className="mc-meta">{meta.join(' · ')}</span>
        </button>
        <span className="mc-acts">
          {shelf ? null : <button type="button" className="mc-act" disabled={busy} onClick={() => ctx.setEditing(editing ? '' : e.key)}>改</button>}
          <More items={items} label={`${e.title} 的更多操作`} />
        </span>
      </div>
      {open && !editing ? (
        <div className="mc-body">
          <p className="mc-text">{e.text}</p>
          {e.why ? <p className="mc-sub">为什么：{e.why}</p> : null}
          {e.origin?.quote && !e.text.includes(e.origin.quote.replace(/[。，,.\s]+$/u, '')) ? <p className="mc-sub">原话：“{e.origin.quote}”</p> : null}
          <p className="mc-sub mono">{[e.code, e.repos?.length ? `仓库 ${e.repos.join('、')}` : '', e.origin?.at ? `记于 ${mmdd(e.origin.at)}` : ''].filter(Boolean).join(' · ')}</p>
        </div>
      ) : null}
      {moving ? (
        <div className="mc-ed-row mc-move">
          <span className="mc-sub">挪到</span>
          <select
            className="mc-sel"
            defaultValue={placeValue(e)}
            aria-label="挪到哪个范围"
            onChange={(ev: React.ChangeEvent<HTMLSelectElement>) => {
              setMoving(false);
              if (ev.target.value !== placeValue(e)) void ctx.run(e.key, moveOp(e, placeFromValue(ev.target.value)), '已换范围');
            }}
          >
            {placeOptions(ctx.pool, ctx.index).map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
          </select>
          <button type="button" className="mc-link" onClick={() => setMoving(false)}>取消</button>
        </div>
      ) : null}
      {editing ? (
        <Editor
          index={ctx.index}
          init={{ title: e.title, text: e.text, why: e.why, kind: e.kind }}
          saveWord="保存"
          busy={busy}
          onCancel={() => ctx.setEditing('')}
          onSave={(d) => {
            void ctx.run(e.key, editOp(e, d)).then((ok: boolean) => {
              if (ok) ctx.setEditing('');
            });
          }}
        />
      ) : null}
      <ReceiptLine r={r} />
    </li>
  );
};

const EntryList: React.FC<{ rows: MemoryEntry[]; ctx: Ctx; empty: string }> = ({ rows, ctx, empty }) =>
  rows.length ? <ul className="mc-list">{rows.map((e: MemoryEntry) => <EntryRow key={e.key} e={e} ctx={ctx} />)}</ul> : <p className="mc-empty">{empty}</p>;

/** 列表底下“已收起 N 条”：归档、作废的，点开能放回 */
const Shelf: React.FC<{ rows: MemoryEntry[]; ctx: Ctx }> = ({ rows, ctx }) => {
  const [open, setOpen] = useState<boolean>(false);
  if (!rows.length) return null;
  return (
    <div className="mc-shelf">
      <button type="button" className="mc-link" aria-expanded={open} onClick={() => setOpen(!open)}>已收起 {rows.length} 条<ChevronRight className={open ? 'rot' : ''} /></button>
      {open ? <ul className="mc-list">{rows.map((e: MemoryEntry) => <EntryRow key={e.key} e={e} ctx={ctx} shelf />)}</ul> : null}
    </div>
  );
};

/** 规矩页顶上：每个范围一条配额（只画有规矩的范围） */
const Rooms: React.FC<{ scopes: MemoryScopeSummary[]; scope: ScopeFilter }> = ({ scopes, scope }) => {
  const shown: MemoryScopeSummary[] = scopes.filter((s: MemoryScopeSummary) => (scope === 'all' ? s.rules.items > 0 : s.key === scope));
  if (!shown.length) return null;
  return (
    <div className="mc-rooms">
      {shown.map((s: MemoryScopeSummary) => {
        const room = roomOf(s);
        const pct: number = room.limit > 0 ? Math.min(100, Math.round((room.used / room.limit) * 100)) : 0;
        return (
          <div key={s.key} className={`mc-room ${room.tone}`}>
            <span className="mc-room-n">{s.key === 'global' ? '全局' : s.key === 'topics' ? '话题' : s.title}</span>
            <span className="mc-bar" aria-hidden="true"><i style={{ width: `${pct}%` }} /></span>
            <span className="mc-room-w">{room.words}</span>
          </div>
        );
      })}
    </div>
  );
};

/* ---------- 待审核 ---------- */
const ReviewCard: React.FC<{ r: MemoryReviewItem; ctx: Ctx }> = ({ r, ctx }) => {
  const [edit, setEdit] = useState<boolean>(false);
  const [open, setOpen] = useState<boolean>(false);
  const rc: Receipt | undefined = ctx.receipts[r.key];
  const busy: boolean = rc?.phase === 'sending';
  const left: MemoryEntry | undefined = r.conflict_with ? ctx.pool.entries.find((e: MemoryEntry) => e.key === r.conflict_with) : undefined;
  const meta: string[] = reviewMeta(r, ctx.pool);
  if (r.type === 'conflict') {
    return (
      <li className="mc-rv">
        <div className="mc-t1"><span className="mc-title">{r.title}</span></div>
        <div className="mc-meta">{meta.join(' · ')}</div>
        <div className="mc-pair">
          <div><span className="mc-sub">已有的</span><b>{left?.title ?? r.conflict_with}</b><p>{left?.text ?? ''}</p></div>
          <div><span className="mc-sub">新来的</span><b>{r.title}</b><p>{r.text}</p></div>
        </div>
        <div className="mc-rv-acts">
          <button type="button" className="mc-btn" disabled={busy} onClick={() => void ctx.run(r.key, keepOp('keep_left', r))}>留已有的</button>
          <button type="button" className="mc-btn" disabled={busy} onClick={() => void ctx.run(r.key, keepOp('keep_right', r))}>换成新的</button>
          <button type="button" className="mc-btn" disabled={busy} onClick={() => void ctx.run(r.key, keepOp('keep_both', r))}>都留</button>
        </div>
        <ReceiptLine r={rc} />
      </li>
    );
  }
  return (
    <li className="mc-rv">
      <div className="mc-t1"><span className="mc-title">{r.title}</span></div>
      <div className="mc-meta">{meta.join(' · ')}</div>
      {r.quote ? <button type="button" className={`mc-quote${open ? ' open' : ''}`} onClick={() => setOpen(!open)}>你说：“{r.quote}”</button> : null}
      {r.text && r.text !== r.title ? <p className="mc-text">{r.text}</p> : null}
      {r.items?.length ? (
        <ul className="mc-tidy">{r.items.map((e: MemoryEntry) => <li key={e.key}><span className="mono">{e.code}</span>{e.title}</li>)}</ul>
      ) : null}
      {edit ? (
        <Editor
          index={ctx.index}
          init={{ title: r.title, text: r.text, kind: r.suggest.kind }}
          places={placeOptions(ctx.pool, ctx.index)}
          place={r.suggest.scope === 'project' ? `p:${r.suggest.project_key ?? ''}` : 'global'}
          saveWord="采纳"
          busy={busy}
          onCancel={() => setEdit(false)}
          onSave={(d) => {
            void ctx.run(r.key, acceptOp(r, { title: d.title, text: d.text, kind: d.kind, ...placeFromValue(d.place) })).then((ok: boolean) => {
              if (ok) setEdit(false);
            });
          }}
        />
      ) : (
        <div className="mc-rv-acts">
          <button type="button" className="mc-btn pri" disabled={busy} onClick={() => void ctx.run(r.key, acceptOp(r))}>采纳</button>
          <button type="button" className="mc-btn" disabled={busy} onClick={() => setEdit(true)}>改</button>
          <button type="button" className="mc-link" disabled={busy} onClick={() => void ctx.run(r.key, rejectOp(r))}>不要</button>
        </div>
      )}
      <ReceiptLine r={rc} />
    </li>
  );
};

const ReviewTab: React.FC<{ rows: MemoryReviewItem[]; ctx: Ctx }> = ({ rows, ctx }) => {
  const [ask, setAsk] = useState<'' | 'accept_all' | 'reject_all'>('');
  const rc: Receipt | undefined = ctx.receipts['review:all'];
  if (!rows.length) return <p className="mc-empty">现在没有要你审核的。</p>;
  return (
    <>
      <div className="mc-bulk">
        {ask ? (
          <>
            <span className="mc-sub">{ask === 'accept_all' ? `确认把这 ${rows.length} 条都按建议记下？` : `确认这 ${rows.length} 条都不要？`}</span>
            <button type="button" className={`mc-btn${ask === 'accept_all' ? ' pri' : ''}`} disabled={rc?.phase === 'sending'} onClick={() => { const a = ask; setAsk(''); void ctx.run('review:all', allOp(a, rows)); }}>
              {ask === 'accept_all' ? '全部采纳' : '全部不要'}
            </button>
            <button type="button" className="mc-link" onClick={() => setAsk('')}>取消</button>
          </>
        ) : (
          <>
            <button type="button" className="mc-btn" onClick={() => setAsk('accept_all')} data-testid="memory-accept-all">全部采纳</button>
            <button type="button" className="mc-link" onClick={() => setAsk('reject_all')}>全部不要</button>
          </>
        )}
      </div>
      <ReceiptLine r={rc} />
      <ul className="mc-list">{rows.map((r: MemoryReviewItem) => <ReviewCard key={r.key} r={r} ctx={ctx} />)}</ul>
    </>
  );
};

/* ---------- 记录 ---------- */
const at = (sec: number): string =>
  new Date(sec * 1000).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }).replace(/\//gu, '-');
const LogTab: React.FC<{ rows: MemoryLogItem[]; ctx: Ctx }> = ({ rows, ctx }) => {
  if (!rows.length) return <p className="mc-empty">还没有变更记录。</p>;
  return (
    <ul className="mc-list">
      {[...rows].sort((a: MemoryLogItem, b: MemoryLogItem) => b.at - a.at).map((l: MemoryLogItem, i: number) => {
        const w = logLine(l);
        const id = `undo:${l.undo_token ?? i}`;
        const rc: Receipt | undefined = ctx.receipts[id];
        return (
          <li key={`${l.at}:${i}`} className="mc-row">
            <div className="mc-line">
              <div className="mc-main static">
                <span className="mc-t1"><span className="mc-title">{w.who}{w.action}「{w.title}」</span></span>
                <span className="mc-meta">{[at(l.at), w.because].filter(Boolean).join(' · ')}</span>
              </div>
              {l.undo_token ? (
                <span className="mc-acts">
                  <button type="button" className="mc-act" disabled={rc?.phase === 'sending'} onClick={() => void ctx.run(id, undoOp(l.undo_token ?? ''))}>撤销</button>
                </span>
              ) : null}
            </div>
            <ReceiptLine r={rc} />
          </li>
        );
      })}
    </ul>
  );
};

/* ---------- 抽屉：下一轮带什么、导入 ---------- */
const Drawer: React.FC<{ title: string; onClose: () => void; foot?: React.ReactNode; children: React.ReactNode }> = ({ title, onClose, foot, children }) => {
  useEffect(() => {
    const esc = (e: KeyboardEvent): void => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', esc);
    return () => document.removeEventListener('keydown', esc);
  }, [onClose]);
  return (
    <div className="mc-shade" onMouseDown={(e: React.MouseEvent) => { if (e.target === e.currentTarget) onClose(); }}>
      <aside className="mc-drawer" role="dialog" aria-label={title}>
        <header><b>{title}</b><button type="button" className="mc-ic" aria-label="关闭" onClick={onClose}><X /></button></header>
        <div className="mc-dbody">{children}</div>
        {foot ? <footer>{foot}</footer> : null}
      </aside>
    </div>
  );
};

const PreviewDrawer: React.FC<{ data: MemoryPreviewsData | undefined; titleOf: (c: string) => string; onClose: () => void }> = ({ data, titleOf, onClose }) => {
  const list: MemoryPreview[] = data?.previews ?? [];
  const [pick, setPick] = useState<string>('');
  const cur: MemoryPreview | undefined = list.find((p: MemoryPreview) => p.topic_key === pick) ?? list[0];
  return (
    <Drawer title="下一轮带什么" onClose={onClose} foot={cur ? <span className="mc-sub">共 {cur.chars.toLocaleString('en-US')} 字</span> : null}>
      {!data ? <p className="mc-empty">读取中…</p> : !list.length ? <p className="mc-empty">还没有预览。</p> : (
        <>
          <select className="mc-sel wide" value={cur?.topic_key ?? ''} aria-label="看哪个话题" onChange={(e: React.ChangeEvent<HTMLSelectElement>) => setPick(e.target.value)}>
            {list.map((p: MemoryPreview) => <option key={p.topic_key} value={p.topic_key}>{p.title}</option>)}
          </select>
          {cur ? previewSections(cur, titleOf).map((s) => (
            <section key={s.key} className="mc-pv">
              <h4>{s.word}<em>{s.rows.length}</em></h4>
              <ul>
                {s.rows.map((r) => (
                  <li key={r.code}>
                    <Link to={`/memory?code=${encodeURIComponent(r.code)}`} onClick={onClose} className="mono">{r.code}</Link>
                    <span className="mc-pv-t">{r.title}</span>
                    {r.why ? <span className="mc-sub">{r.why}</span> : null}
                  </li>
                ))}
              </ul>
            </section>
          )) : null}
        </>
      )}
    </Drawer>
  );
};

const ImportDrawer: React.FC<{ page: number; pages: number; data: MemoryImportPage | undefined; ctx: Ctx; onPage: (n: number) => void; onClose: () => void }> = ({ page, pages, data, ctx, onPage, onClose }) => {
  const items: MemoryImportItem[] = useMemo(() => data?.items ?? [], [data]);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [touched, setTouched] = useState<boolean>(false);
  useEffect(() => {
    // 换页或数据到了：没动过就按默认勾
    if (!touched) setPicked(new Set(items.filter(importChecked).map((it: MemoryImportItem) => it.fingerprint)));
  }, [items, touched]);
  const fresh: MemoryImportItem[] = items.filter((it: MemoryImportItem) => it.state === 'new');
  const chosen: string[] = fresh.map((it) => it.fingerprint).filter((f: string) => picked.has(f));
  const rest: string[] = fresh.map((it) => it.fingerprint).filter((f: string) => !picked.has(f));
  const rc: Receipt | undefined = ctx.receipts['import'];
  const busy: boolean = rc?.phase === 'sending';
  const flip = (f: string): void => {
    setTouched(true);
    setPicked((s: Set<string>) => {
      const n = new Set(s);
      if (n.has(f)) n.delete(f);
      else n.add(f);
      return n;
    });
  };
  const foot = (
    <>
      <ReceiptLine r={rc} />
      <span className="sp" />
      <button type="button" className="mc-link" disabled={busy || !rest.length} onClick={() => void ctx.run('import', ignoreOp(rest))}>其余 {rest.length} 条留在原工具</button>
      <button type="button" className="mc-btn pri" disabled={busy || !chosen.length} onClick={() => void ctx.run('import', importOp(chosen)).then((ok: boolean) => { if (ok) setTouched(false); })}>导入 {chosen.length} 条</button>
    </>
  );
  return (
    <Drawer title="从 Claude Code、Codex 导入" onClose={onClose} foot={foot}>
      {pages > 1 ? (
        <div className="mc-pager">
          <button type="button" className="mc-link" disabled={page <= 0} onClick={() => { setTouched(false); onPage(page - 1); }}>上一页</button>
          <span className="mc-sub">第 {page + 1}/{pages} 页</span>
          <button type="button" className="mc-link" disabled={page >= pages - 1} onClick={() => { setTouched(false); onPage(page + 1); }}>下一页</button>
        </div>
      ) : null}
      {!data ? <p className="mc-empty">读取中…</p> : !items.length ? <p className="mc-empty">这一页没有可导入的。</p> : importGroups(items).map((g) => (
        <section key={g.label} className="mc-pv">
          <h4>{g.label}<em>{g.items.length}</em></h4>
          <ul className="mc-imp">
            {g.items.map((it: MemoryImportItem) => (
              <li key={it.fingerprint} className={it.state === 'new' ? '' : 'dim'}>
                <label>
                  <input type="checkbox" disabled={it.state !== 'new' || busy} checked={picked.has(it.fingerprint)} onChange={() => flip(it.fingerprint)} />
                  <span className="mc-imp-b">
                    <span className="mc-title">{it.title}</span>
                    <span className="mc-meta">{importMeta(it, ctx.pool).join(' · ')}</span>
                  </span>
                </label>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </Drawer>
  );
};

/* ---------- 体检 ---------- */
const Health: React.FC<{ rows: HealthRow[]; pick: HealthRow | null; onPick: (r: HealthRow | null) => void }> = ({ rows, pick, onPick }) => (
  <div className="mc-health" aria-label="体检">
    <span className="mc-hl">体检</span>
    {rows.length ? rows.map((r: HealthRow) => (
      <button key={r.key} type="button" className={`mc-chip${pick?.key === r.key ? ' on' : ''}`} aria-pressed={pick?.key === r.key} onClick={() => onPick(pick?.key === r.key ? null : r)}>
        {r.word}<em>{r.n}</em>
      </button>
    )) : <span className="mc-sub">{HEALTH_OK}</span>}
  </div>
);

/* ---------- 整页 ---------- */
export const MemoryCenter: React.FC<{ index: MemoryIndex }> = ({ index }) => {
  const params = useParams<{ tab?: string }>();
  const [sp, setSp] = useSearchParams();
  const nav = useNavigate();
  const send = useMemoryOp();
  const [previewOpen, setPreviewOpen] = useState<boolean>(false);
  const [importPage, setImportPage] = useState<number | null>(null);
  const keys = useMemo(() => keysToLoad(index, { previews: previewOpen, importPage }), [index, previewOpen, importPage]);
  const got = useMemoryKeys(keys);
  const pool: Pool = useMemo(() => poolOf(
    got.data['memory:global'] as MemoryGlobalData | undefined,
    got.data['memory:topics'] as MemoryTopicsData | undefined,
    keys.filter((k) => projectKeyOf(k.key)).map((k) => got.data[k.key] as MemoryProjectData | undefined),
  ), [got.data, keys]);
  const scope: ScopeFilter = sp.get('scope') || 'all';
  const code: string = sp.get('code') ?? '';
  const [view, setView] = useState<DecisionView>('open');
  const [query, setQuery] = useState<string>('');
  const [editing, setEditing] = useState<string>('');
  const [adding, setAdding] = useState<boolean>(false);
  const [receipts, setReceipts] = useState<Record<string, Receipt>>({});
  const [notice, setNotice] = useState<{ id: number; text: string; undo?: string } | null>(null);
  const [healthPick, setHealthPick] = useState<HealthRow | null>(null);
  const timer = useRef<number>(0);
  useEffect(() => () => window.clearTimeout(timer.current), []);

  // 链接进来（⌘K、预览、话题页的“带了 N 条记忆”）：?code= 找到那一条，切到它的页签
  const hit = useMemo(() => (code ? locate(pool, code) : null), [pool, code]);
  const tab: MemoryTab = isTab(params.tab) ? params.tab : hit ? hit.tab : defaultTab(index);
  useEffect(() => {
    if (hit && hit.view !== 'open') setView(hit.view);
  }, [hit]);
  const goTab = (t: MemoryTab): void => {
    const q = new URLSearchParams(sp);
    q.delete('code');
    nav({ pathname: `/memory/${t}`, search: q.toString() ? `?${q.toString()}` : '' });
  };
  const setScope = (v: string): void => {
    const q = new URLSearchParams(sp);
    if (v === 'all') q.delete('scope');
    else q.set('scope', v);
    q.delete('code');
    setSp(q, { replace: true });
  };

  const run = useCallback(async (id: string, payload: MemoryEditPayloadV43, done?: string): Promise<boolean> => {
    setReceipts((r) => ({ ...r, [id]: { phase: 'sending', message: '' } }));
    const res: OpResult = await send(payload);
    const ok: boolean = res.phase === 'done';
    const message: string = ok ? res.message || done || '已办好' : failWords(res);
    setReceipts((r) => ({ ...r, [id]: { phase: ok ? 'done' : 'failed', message } }));
    if (ok) {
      window.setTimeout(() => setReceipts((r) => {
        if (r[id]?.phase !== 'done') return r;
        const next = { ...r };
        delete next[id];
        return next;
      }), 4000);
      if (done) {
        // 归档、作废这类：一行页面提示，5 秒内能撤销（撤销码从变更记录里找这一条的）
        window.clearTimeout(timer.current);
        setNotice((n) => ({ id: (n?.id ?? 0) + 1, text: message, undo: payload.keys[0] }));
        timer.current = window.setTimeout(() => setNotice(null), 5000);
      }
    }
    return ok;
  }, [send]);

  const ctx: Ctx = { pool, index, scope, view, receipts, run, focus: hit ? hit.entry.code : '', editing, setEditing };
  const health: HealthRow[] = healthRows(index.health);
  const focusRefs: Set<string> | null = healthPick ? new Set(healthPick.refs) : null;
  const review: MemoryReviewItem[] = reviewItems(pool, scope);
  const rows: MemoryEntry[] = tabEntries(pool, tab, scope, focusRefs ? 'all' : view, query).filter((e: MemoryEntry) => !focusRefs || focusRefs.has(e.key));
  const dc = decisionCounts(pool, scope);
  const titleMap = useMemo(() => titleIndex(pool.entries, index.titles), [pool.entries, index.titles]);
  const undoFor = (key: string | undefined): string => {
    if (!key) return '';
    const l: MemoryLogItem | undefined = [...pool.log].sort((a, b) => b.at - a.at).find((x: MemoryLogItem) => x.refs.includes(key) && !!x.undo_token);
    return l?.undo_token ?? '';
  };
  const noticeUndo: string = undoFor(notice?.undo);
  const options = scopeOptions(index);
  const total: number = index.counts.rule + index.counts.decision + index.counts.note;
  const loading: boolean = got.loading && !pool.entries.length && !pool.review.length;
  const empty: string = query ? `没有搜到“${query}”` : focusRefs ? '这一项涉及的条目不在这个页签' : tab === 'decisions' && view === 'open' ? '没有在办的决定' : '这里还没有。';
  const kindForAdd: MemoryKind = TAB_KIND[tab] ?? 'rule';
  const headc = headCounts(index, scope);

  return (
    <div className="mc-page">
      <Head title="记忆" sub={`规矩 ${headc.rule} · 决定 ${headc.decision} · 资料 ${headc.note}`} />
      <div className="scroll">
        <div className="mc" data-testid="memory-center">
          <div className="mc-top">
            <select className="mc-sel" value={scope} onChange={(e: React.ChangeEvent<HTMLSelectElement>) => setScope(e.target.value)} aria-label="范围">
              {options.map((o) => <option key={o.value} value={o.value}>{o.label}{o.pending ? `（待审核 ${o.pending}）` : ''}{o.over ? ' · 超额' : ''}</option>)}
            </select>
            <label className="mc-search">
              <Search aria-hidden="true" />
              <input type="search" value={query} placeholder="筛标题、正文、短码" aria-label="筛记忆" onChange={(e: React.ChangeEvent<HTMLInputElement>) => setQuery(e.target.value)} />
            </label>
            <span className="sp" />
            <button type="button" className="mc-btn ghost" onClick={() => setPreviewOpen(true)} title="下一轮带什么" data-testid="memory-preview"><Eye /><span className="mc-bw">下一轮带什么</span></button>
            <button type="button" className="mc-btn ghost" onClick={() => setImportPage(0)} title="从 Claude Code、Codex 导入" data-testid="memory-import">
              <Import /><span className="mc-bw">导入</span>{index.imports.new ? <em className="mc-n">{index.imports.new}</em> : null}
            </button>
            <button type="button" className="mc-btn pri" onClick={() => { setEditing(''); setAdding(true); }} title="记一条" data-testid="memory-new"><Plus /><span className="mc-bw">记一条</span></button>
          </div>
          <Health rows={health} pick={healthPick} onPick={(r) => {
            setHealthPick(r);
            if (r && tab !== 'log' && tab !== 'review') {
              const first: MemoryEntry | undefined = pool.entries.find((e: MemoryEntry) => r.refs.includes(e.key));
              if (first && TAB_KIND[tab] !== first.kind) goTab(({ rule: 'rules', decision: 'decisions', note: 'notes' } as const)[first.kind]);
            }
          }} />
          <nav className="mc-tabs" aria-label="记忆分页">
            {TABS.map((t: MemoryTab) => (
              <button key={t} type="button" className={t === tab ? 'on' : ''} aria-current={t === tab ? 'page' : undefined} onClick={() => goTab(t)}>
                {TAB_WORD[t]}{t === 'review' && index.counts.pending ? <em className="mc-n wait">{index.counts.pending}</em> : null}
              </button>
            ))}
          </nav>
          {notice ? (
            <div key={notice.id} className="mc-notice" role="status">
              <Check aria-hidden="true" /><span>{notice.text}</span>
              {noticeUndo ? <button type="button" className="mc-link" onClick={() => { setNotice(null); void run(`undo:${noticeUndo}`, undoOp(noticeUndo)); }}>撤销</button> : <span className="mc-sub">可在记录里找回</span>}
              <button type="button" className="mc-ic" aria-label="知道了" onClick={() => setNotice(null)}><X /></button>
            </div>
          ) : null}
          {healthPick ? (
            <div className="mc-focus"><span>只看体检“{healthPick.word}”涉及的 {healthPick.refs.length} 条</span><button type="button" className="mc-link" onClick={() => setHealthPick(null)}>看全部</button></div>
          ) : null}
          {adding ? (
            <Editor
              index={index}
              init={{ title: '', text: '', kind: kindForAdd }}
              places={placeOptions(pool, index)}
              place={scope.startsWith('p:') ? scope : 'global'}
              saveWord="记下"
              busy={receipts['new']?.phase === 'sending'}
              onCancel={() => setAdding(false)}
              onSave={(d) => {
                void run('new', addOp({ title: d.title, text: d.text, why: d.why, kind: d.kind, ...placeFromValue(d.place) })).then((ok: boolean) => {
                  if (ok) setAdding(false);
                });
              }}
            />
          ) : null}
          <ReceiptLine r={receipts['new']} />
          {TAB_NOTE[tab] ? <p className="mc-note">{TAB_NOTE[tab]}</p> : null}
          {tab === 'decisions' && !focusRefs ? (
            <div className="mc-seg" role="radiogroup" aria-label="看哪些决定">
              {(['open', 'all', 'done'] as DecisionView[]).map((v: DecisionView) => (
                <button key={v} type="button" role="radio" aria-checked={view === v} className={view === v ? 'on' : ''} onClick={() => setView(v)}>
                  {{ open: '在办', all: '全部', done: '已办' }[v]}<em>{dc[v]}</em>
                </button>
              ))}
            </div>
          ) : null}
          {tab === 'rules' ? <Rooms scopes={index.scopes} scope={scope} /> : null}
          {loading ? <p className="mc-empty">读取中…</p> : !total && !pool.review.length && tab !== 'log' ? (
            <p className="mc-empty">还没有记忆。在话题里说“以后都……”会记下来。</p>
          ) : tab === 'review' ? <ReviewTab rows={review} ctx={ctx} />
            : tab === 'log' ? <LogTab rows={pool.log} ctx={ctx} />
              : (
                <>
                  <EntryList rows={rows} ctx={ctx} empty={empty} />
                  {focusRefs || query ? null : <Shelf rows={shelved(pool, tab, scope)} ctx={ctx} />}
                </>
              )}
        </div>
      </div>
      {previewOpen ? <PreviewDrawer data={got.data['memory:previews'] as MemoryPreviewsData | undefined} titleOf={(c: string) => titleMap.get(c) ?? ''} onClose={() => setPreviewOpen(false)} /> : null}
      {importPage !== null ? (
        <ImportDrawer
          page={importPage}
          pages={Math.max(1, index.imports.pages)}
          data={got.data[`memory:import:${importPage}`] as MemoryImportPage | undefined}
          ctx={ctx}
          onPage={setImportPage}
          onClose={() => setImportPage(null)}
        />
      ) : null}
    </div>
  );
};

/** 路由 /memory：收到 memory:index 是记忆中心；旧 Covey（只推 v37 的 memory）退回原来的主记忆页 */
const MemoryCenterPage: React.FC = () => {
  const { mode, index } = useMemoryMode();
  const idx = useMemoryIndex();
  if (mode === 'v43' && index) return <MemoryCenter index={index} />;
  return (
    <div className="mc-page">
      <Head title="记忆" />
      <div className="scroll">
        <div className="mc">
          {mode === 'v37' ? <MainMemory /> : mode === 'loading' || idx.isLoading ? <p className="mc-empty">读取中…</p> : <p className="mc-empty">记忆没开，或者 Covey 还没推送记忆。</p>}
        </div>
      </div>
    </div>
  );
};
export default MemoryCenterPage;
