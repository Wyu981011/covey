import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { Check, Copy, Pencil, Pin, PinOff, Plus, Search, Trash2, X } from 'lucide-react';
import type { MainMemoryCandidate, MainMemoryData, MainMemoryEntry, MainMemoryGroup, MemoryEditPayload } from '@shared/api.interface';
import { MEMORY_KEY, newOpId, useMemory } from '@client/src/hooks/use-workbench';
import { sendOp, type OpResult } from './sendOp';
import {
  addPayload, byWords, checkDraft, editPayload, edited, filterGroups, hitRanges, kindLabel, placeOptions, previewOptions,
  roomOf, roomPercent, roomWords, scopeOptions, whenWords, type ScopeFilter,
} from './mainMemory';
import './mainmemory.css';

/* 设置页「记忆」（v37）：主人的主记忆，全局和各工作区的原则、知识条目和待确认的候选。和飞书设置卡「记忆」改的是同一份
   （Covey 的 app/web_memory.py）。读：按作用域分组、配额条、下一轮带不带、搜索和筛选、某个工作区下一轮带上的那一段；
   改：新建、原地改正文（数字数、⌘/Ctrl+S 保存、Esc 取消、未保存提醒）、常驻、删除先问一句、候选记下或不用。 */

type Phase = 'sending' | 'done' | 'failed';
interface Receipt {
  phase: Phase;
  message: string;
}

const SAVE_HINT = /Mac|iPhone|iPad/u.test(typeof navigator === 'undefined' ? '' : navigator.platform) ? '⌘S' : 'Ctrl+S';

/** 发一条 memory_edit，等 Covey 的回执；办好了重取主记忆（Covey 回执之前已推了新的） */
function useMemoryOp(): (payload: MemoryEditPayload) => Promise<OpResult> {
  const qc = useQueryClient();
  return useCallback(async (payload: MemoryEditPayload): Promise<OpResult> => {
    const r: OpResult = await sendOp({ op_id: newOpId(), kind: 'memory_edit', payload: payload as unknown as Record<string, unknown> });
    if (r.phase === 'done') await qc.invalidateQueries({ queryKey: MEMORY_KEY });
    return r;
  }, [qc]);
}

const failWords = (r: OpResult): string =>
  r.phase === 'unsent' ? `没发出去：${r.message || '网络不通'}` : r.phase === 'timeout' ? 'Covey 还没回音，稍后刷新看看' : r.message || '没办成';

/** 正文，搜索词标出来 */
const Hit: React.FC<{ text: string; query: string }> = ({ text, query }) => {
  const ranges: [number, number][] = hitRanges(text, query);
  if (!ranges.length) return <>{text}</>;
  const out: React.ReactNode[] = [];
  let at = 0;
  ranges.forEach(([a, b]: [number, number], i: number) => {
    if (a > at) out.push(text.slice(at, a));
    out.push(<mark key={i}>{text.slice(a, b)}</mark>);
    at = b;
  });
  out.push(text.slice(at));
  return <>{out}</>;
};

/** 自己长高的文本框（最高 320px，再长就滚） */
const Grow = React.forwardRef<HTMLTextAreaElement, React.TextareaHTMLAttributes<HTMLTextAreaElement> & { value: string }>((props, outer) => {
  const inner = useRef<HTMLTextAreaElement | null>(null);
  useEffect(() => {
    const el = inner.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight + 2, 320)}px`;
  }, [props.value]);
  const setRef = (el: HTMLTextAreaElement | null): void => {
    inner.current = el;
    if (typeof outer === 'function') outer(el);
    else if (outer) outer.current = el;
  };
  return <textarea ref={setRef} rows={2} {...props} />;
});
Grow.displayName = 'Grow';

const Counter: React.FC<{ count: number; limit: number }> = ({ count, limit }) => (
  <span className={`mm2-count${count > limit ? ' over' : count >= limit * 0.9 ? ' near' : ''}`} aria-live="polite">{count} / {limit}</span>
);

interface EditorProps {
  title?: string;
  initial: { text: string; kind?: string; why?: string };
  limit: number;
  kinds?: MainMemoryData['kinds'];
  /** 知识条目：能选种类、写原因 */
  knowledge: boolean;
  /** 新建：能选记成原则还是知识、记在哪 */
  place?: { options: { value: string; label: string }[]; value: string; onChange: (v: string) => void };
  what?: { value: 'principle' | 'knowledge'; onChange: (v: 'principle' | 'knowledge') => void; knowledgeOn: boolean };
  base?: MainMemoryEntry;
  saveLabel: string;
  onSave: (text: string, kind: string, why: string) => Promise<string | null>;
  onCancel: () => void;
  onDirty: (dirty: boolean) => void;
  /** 页面别处要换走（改另一条、新建）而这里有没保存的改动：在框里问一句 */
  guard?: { onDiscard: () => void; onKeep: () => void } | null;
}

/** 编辑框：新建和原地改共用。存的时候按钮变“保存中…”，没办成在框下面写原因、框留着 */
const Editor: React.FC<EditorProps> = ({ title, initial, limit, kinds, knowledge, place, what, base, saveLabel, onSave, onCancel, onDirty, guard }) => {
  const [text, setText] = useState<string>(initial.text);
  const [kind, setKind] = useState<string>(initial.kind ?? 'fact');
  const [why, setWhy] = useState<string>(initial.why ?? '');
  const [busy, setBusy] = useState<boolean>(false);
  const [error, setError] = useState<string>('');
  const [asking, setAsking] = useState<boolean>(false);
  const ref = useRef<HTMLTextAreaElement>(null);
  const check = checkDraft(text, limit);
  const dirty: boolean = base ? edited(base, text, knowledge ? kind : undefined, knowledge ? why : undefined) : !!text.trim();
  useEffect(() => onDirty(dirty), [dirty, onDirty]);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.focus();
    el.setSelectionRange(el.value.length, el.value.length);
  }, []);
  const save = async (): Promise<void> => {
    if (busy || !check.ok) return;
    if (base && !dirty) {
      onCancel();
      return;
    }
    setBusy(true);
    setError('');
    const why_: string | null = await onSave(text, kind, why);
    setBusy(false);
    if (why_) setError(why_);
  };
  const cancel = (): void => {
    if (dirty) setAsking(true);
    else onCancel();
  };
  const ask = guard ?? (asking ? { onDiscard: onCancel, onKeep: () => setAsking(false) } : null);
  const keys = (e: React.KeyboardEvent): void => {
    if ((e.metaKey || e.ctrlKey) && (e.key === 's' || e.key === 'S' || e.key === 'Enter')) {
      e.preventDefault();
      void save();
    } else if (e.key === 'Escape') {
      e.preventDefault();
      cancel();
    }
  };
  return (
    <div className="mm2-editor" onKeyDown={keys} data-testid="memory-editor">
      {title ? <div className="mm2-ed-title">{title}</div> : null}
      {what || place ? (
        <div className="mm2-ed-row">
          {what ? (
            <div className="mm2-seg" role="radiogroup" aria-label="记成">
              <button type="button" role="radio" aria-checked={what.value === 'principle'} className={what.value === 'principle' ? 'on' : ''} onClick={() => what.onChange('principle')}>原则</button>
              {what.knowledgeOn ? (
                <button type="button" role="radio" aria-checked={what.value === 'knowledge'} className={what.value === 'knowledge' ? 'on' : ''} onClick={() => what.onChange('knowledge')}>知识条目</button>
              ) : null}
            </div>
          ) : null}
          {place ? (
            <label className="mm2-field">
              <span>记在</span>
              <select value={place.value} onChange={(e: React.ChangeEvent<HTMLSelectElement>) => place.onChange(e.target.value)} aria-label="记在哪">
                {place.options.map((o: { value: string; label: string }) => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
            </label>
          ) : null}
        </div>
      ) : null}
      <Grow
        ref={ref}
        value={text}
        onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) => setText(e.target.value)}
        placeholder={knowledge ? `一句话写清这条知识（最多 ${limit} 字）` : `一句话写清这条原则：以后每一轮都会读到（最多 ${limit} 字）`}
        aria-label="正文"
        className="mm2-ta"
      />
      {knowledge ? (
        <div className="mm2-ed-row">
          <label className="mm2-field">
            <span>种类</span>
            <select value={kind} onChange={(e: React.ChangeEvent<HTMLSelectElement>) => setKind(e.target.value)} aria-label="种类">
              {(kinds ?? []).map((k: { value: string; text: string }) => <option key={k.value} value={k.value}>{k.text}</option>)}
            </select>
          </label>
          <label className="mm2-field grow">
            <span>原因</span>
            <input value={why} onChange={(e: React.ChangeEvent<HTMLInputElement>) => setWhy(e.target.value)} placeholder="可不填" aria-label="原因" />
          </label>
        </div>
      ) : null}
      {ask ? (
        <div className="mm2-guard" role="alertdialog" aria-label="改动还没保存">
          <span>改动还没保存。</span>
          <button type="button" className="mm2-btn danger sm" onClick={ask.onDiscard}>放弃改动</button>
          <button type="button" className="mm2-btn ghost sm" onClick={ask.onKeep}>继续改</button>
        </div>
      ) : null}
      <div className="mm2-ed-foot">
        <Counter count={check.count} limit={limit} />
        {dirty ? <span className="mm2-dirty">未保存</span> : null}
        {!check.ok && check.count > 0 ? <span className="mm2-err">{check.why}</span> : null}
        {error ? <span className="mm2-err" role="alert">{error}</span> : null}
        <span className="sp" />
        <button type="button" className="mm2-btn ghost" onClick={cancel} disabled={busy}>取消<kbd>Esc</kbd></button>
        <button type="button" className="mm2-btn pri" onClick={() => void save()} disabled={busy || !check.ok} data-testid="memory-save">
          {busy ? '保存中…' : saveLabel}<kbd>{SAVE_HINT}</kbd>
        </button>
      </div>
    </div>
  );
};

interface RowProps {
  e: MainMemoryEntry;
  data: MainMemoryData;
  query: string;
  editing: boolean;
  receipt?: Receipt;
  onEdit: () => void;
  onCloseEdit: () => void;
  onDirty: (dirty: boolean) => void;
  run: (key: string, payload: MemoryEditPayload) => Promise<string | null>;
  guard?: EditorProps['guard'];
}

const Row: React.FC<RowProps> = ({ e, data, query, editing, receipt, onEdit, onCloseEdit, onDirty, run, guard }) => {
  const [asking, setAsking] = useState<boolean>(false);
  const limit: number = data.limits?.text ?? 200;
  const sending: boolean = receipt?.phase === 'sending';
  if (editing) {
    return (
      <li className="mm2-row editing" data-key={e.key}>
        <Editor
          initial={{ text: e.text, kind: e.knowledge_kind, why: e.why }}
          limit={limit}
          kinds={data.kinds}
          knowledge={e.kind === 'knowledge'}
          base={e}
          saveLabel="保存"
          onSave={async (text: string, kind: string, why: string) => {
            const err: string | null = await run(e.key, editPayload(e, text, e.kind === 'knowledge' ? kind : undefined, e.kind === 'knowledge' ? why : undefined));
            if (!err) onCloseEdit();
            return err;
          }}
          onCancel={onCloseEdit}
          onDirty={onDirty}
          guard={guard}
        />
      </li>
    );
  }
  return (
    <li className={`mm2-row${e.carried ? '' : ' out'}${e.pinned ? ' pinned' : ''}`} data-key={e.key} data-testid="memory-row">
      <div className="mm2-main" onDoubleClick={e.editable ? onEdit : undefined}>
        <div className="mm2-tags">
          {e.pinned ? <span className="mm2-tag pin"><Pin />常驻</span> : null}
          <span className={`mm2-tag ${e.kind}`}>{kindLabel(e, data.kinds)}</span>
          {e.by === 'lead' ? <span className="mm2-tag lead">它总结的</span> : null}
          {e.carried ? null : <span className="mm2-tag out" title="这一组放不下，下一轮不带">下一轮不带</span>}
        </div>
        <p className="mm2-text"><Hit text={e.text} query={query} /></p>
        {e.why ? <p className="mm2-why">原因：<Hit text={e.why} query={query} /></p> : null}
        <div className="mm2-meta">
          <span>{byWords(e.by)}</span>
          {e.origin ? <span>{e.origin}</span> : null}
          {e.at ? <span>{whenWords(e.at)}</span> : null}
          {e.edited ? <span>改过</span> : null}
          <span>{e.chars} 字</span>
        </div>
        {receipt && receipt.phase !== 'sending' ? (
          <p className={`mm2-receipt ${receipt.phase}`} role={receipt.phase === 'failed' ? 'alert' : 'status'}>
            {receipt.phase === 'done' ? <Check /> : <X />}{receipt.message}
          </p>
        ) : null}
        {asking ? (
          <div className="mm2-confirm" role="alertdialog" aria-label="确认删除">
            <span>{e.kind === 'knowledge' ? '作废这条知识？作废后不再带进任何一轮。' : '删掉这条原则？删了就找不回来。'}</span>
            <button type="button" className="mm2-btn danger" onClick={() => { setAsking(false); void run(e.key, { action: 'delete', key: e.key }); }} data-testid="memory-delete-yes">
              {e.kind === 'knowledge' ? '作废' : '删除'}
            </button>
            <button type="button" className="mm2-btn ghost" onClick={() => setAsking(false)}>取消</button>
          </div>
        ) : null}
      </div>
      <div className="mm2-acts" aria-label="操作">
        {sending ? <span className="mm2-sending">处理中…</span> : null}
        {e.editable ? (
          <button type="button" className="mm2-ic" onClick={onEdit} title="改正文（双击正文也行）" aria-label="改正文" disabled={sending} data-testid="memory-edit">
            <Pencil />
          </button>
        ) : null}
        {e.pinnable ? (
          <button type="button" className={`mm2-ic${e.pinned ? ' on' : ''}`} disabled={sending} data-testid="memory-pin"
            onClick={() => void run(e.key, { action: e.pinned ? 'unpin' : 'pin', key: e.key })}
            title={e.pinned ? '取消常驻' : '标常驻：不管这一组满没满，每一轮都带上'} aria-label={e.pinned ? '取消常驻' : '标常驻'}>
            {e.pinned ? <PinOff /> : <Pin />}
          </button>
        ) : null}
        {e.editable ? (
          <button type="button" className="mm2-ic del" onClick={() => setAsking(true)} disabled={sending}
            title={e.kind === 'knowledge' ? '作废' : '删除'} aria-label={e.kind === 'knowledge' ? '作废' : '删除'} data-testid="memory-delete">
            <Trash2 />
          </button>
        ) : null}
      </div>
    </li>
  );
};

const Group: React.FC<{
  g: MainMemoryGroup;
  data: MainMemoryData;
  query: string;
  editing: string;
  receipts: Record<string, Receipt>;
  setEditing: (key: string) => void;
  onDirty: (dirty: boolean) => void;
  run: (key: string, payload: MemoryEditPayload) => Promise<string | null>;
  onAdd: () => void;
  guard?: EditorProps['guard'];
}> = ({ g, data, query, editing, receipts, setEditing, onDirty, run, onAdd, guard }) => {
  const room = roomOf(g);
  return (
    <section className={`mm2-group room-${room}`} data-testid="memory-group" data-scope={g.scope} data-workspace={g.workspace}>
      <header className="mm2-gh">
        <h3>{g.title}</h3>
        <span className="mm2-gn">{g.entries.length} 条</span>
        <span className="sp" />
        <div className="mm2-room" title={roomWords(g)}>
          <span className="mm2-bar" aria-hidden="true"><i style={{ width: `${roomPercent(g)}%` }} /></span>
          <span className="mm2-rn">{g.used.toLocaleString()} / {g.limit.toLocaleString()} 字</span>
        </div>
        <button type="button" className="mm2-ic" onClick={onAdd} title={`在${g.title}新建一条`} aria-label={`在${g.title}新建一条`}><Plus /></button>
      </header>
      {room !== 'ok' ? <p className={`mm2-roomline ${room}`}>{roomWords(g)}</p> : null}
      {g.entries.length ? (
        <ul className="mm2-list">
          {g.entries.map((e: MainMemoryEntry) => (
            <Row
              key={e.key}
              e={e}
              data={data}
              query={query}
              editing={editing === e.key}
              receipt={receipts[e.key]}
              onEdit={() => setEditing(e.key)}
              onCloseEdit={() => setEditing('')}
              onDirty={onDirty}
              run={run}
              guard={editing === e.key ? guard : null}
            />
          ))}
        </ul>
      ) : (
        <p className="mm2-empty">{query ? '没有搜到' : '还没有：点右上角的 + 记一条'}</p>
      )}
    </section>
  );
};

const Candidates: React.FC<{ rows: MainMemoryCandidate[]; receipts: Record<string, Receipt>; run: (key: string, p: MemoryEditPayload) => Promise<string | null> }> = ({ rows, receipts, run }) => (
  <section className="mm2-group mm2-cands" data-testid="memory-candidates">
    <header className="mm2-gh">
      <h3><i className="mm2-dot" aria-hidden="true" />待你确认</h3>
      <span className="mm2-gn">{rows.length} 条</span>
      <span className="sp" />
      <span className="mm2-hint">Covey 从你反复说的话里总结的；记下就成原则，一直带上</span>
    </header>
    <ul className="mm2-list">
      {rows.map((c: MainMemoryCandidate) => {
        const r: Receipt | undefined = receipts[c.key];
        return (
          <li key={c.key} className="mm2-row cand" data-key={c.key}>
            <div className="mm2-main">
              <div className="mm2-tags">
                <span className="mm2-tag lead">它总结的</span>
                <span className="mm2-tag">{c.workspace ? `工作区 ${c.workspace}` : '全局'}</span>
                {c.carried ? <span className="mm2-tag" title="还没确认，先作为“它总结的”带进下一轮">已在带上</span> : null}
              </div>
              <p className="mm2-text">{c.text}</p>
              <div className="mm2-meta">
                {c.from ? <span>{c.from}</span> : null}
                {c.at ? <span>{whenWords(c.at)}</span> : null}
              </div>
              {c.error ? <p className="mm2-receipt failed"><X />{c.error}</p> : null}
              {r && r.phase !== 'sending' ? <p className={`mm2-receipt ${r.phase}`}>{r.phase === 'done' ? <Check /> : <X />}{r.message}</p> : null}
            </div>
            <div className="mm2-acts show">
              <button type="button" className="mm2-btn pri" disabled={r?.phase === 'sending'} onClick={() => void run(c.key, { action: 'keep', key: c.key })}>记下</button>
              <button type="button" className="mm2-btn ghost" disabled={r?.phase === 'sending'} onClick={() => void run(c.key, { action: 'drop', key: c.key })}>不用</button>
            </div>
          </li>
        );
      })}
    </ul>
  </section>
);

const Preview: React.FC<{ data: MainMemoryData }> = ({ data }) => {
  const names: string[] = previewOptions(data);
  const [ws, setWs] = useState<string>(names[0] ?? '');
  const [copied, setCopied] = useState<boolean>(false);
  const p = data.previews?.[ws] ?? (names[0] ? data.previews?.[names[0]] : undefined);
  if (!names.length || !p) return null;
  return (
    <section className="mm2-group mm2-preview" data-testid="memory-preview">
      <header className="mm2-gh">
        <h3>下一轮实际带上的</h3>
        <span className="sp" />
        <label className="mm2-field">
          <span>新话题在</span>
          <select value={ws} onChange={(e: React.ChangeEvent<HTMLSelectElement>) => setWs(e.target.value)} aria-label="预览哪个工作区">
            {names.map((n: string) => <option key={n} value={n}>工作区 {n}</option>)}
          </select>
        </label>
      </header>
      <p className="mm2-pv-sum">
        {p.count} 条 · {p.chars.toLocaleString()} 字{p.left ? <> · <b className="warn">放不下 {p.left} 条</b></> : ' · 都带上了'}
        <button type="button" className="mm2-btn ghost sm" onClick={() => { void navigator.clipboard?.writeText(p.text); setCopied(true); window.setTimeout(() => setCopied(false), 1500); }}>
          {copied ? <Check /> : <Copy />}{copied ? '已复制' : '复制'}
        </button>
      </p>
      <pre className="mm2-pv">{p.text || '（这个工作区没有要带的记忆）'}</pre>
    </section>
  );
};

/** 设置页「记忆」 */
export const MainMemory: React.FC = () => {
  const q = useMemory();
  const data: MainMemoryData | undefined = q.data?.data;
  const send = useMemoryOp();
  const [query, setQuery] = useState<string>('');
  const [scope, setScope] = useState<ScopeFilter>('all');
  const [editing, setEditingKey] = useState<string>('');
  const [adding, setAdding] = useState<string>('');
  const [what, setWhat] = useState<'principle' | 'knowledge'>('principle');
  const [receipts, setReceipts] = useState<Record<string, Receipt>>({});
  const dirty = useRef<boolean>(false);
  const onDirty = useCallback((d: boolean) => { dirty.current = d; }, []);

  // 有没保存的改动时关页面、刷新先问一句
  useEffect(() => {
    const warn = (e: BeforeUnloadEvent): void => {
      if (!dirty.current) return;
      e.preventDefault();
      e.returnValue = '';
    };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, []);

  // 有没保存的改动又要换走（改另一条、新建）：不直接丢，先在打开的编辑框里问一句
  const [pending, setPending] = useState<(() => void) | null>(null);
  const leave = (next: () => void): void => {
    if (!dirty.current) {
      next();
      return;
    }
    setPending(() => next);
  };
  const guard: EditorProps['guard'] = pending ? {
    onDiscard: () => { dirty.current = false; const next = pending; setPending(null); next(); },
    onKeep: () => setPending(null),
  } : null;
  const setEditing = (key: string): void => {
    if (key && key === editing) return;
    const open = (): void => {
      dirty.current = false;
      setAdding('');
      setEditingKey(key);
    };
    if (key) leave(open);
    else open();
  };
  const startAdd = (place: string): void => {
    leave(() => {
      dirty.current = false;
      setEditingKey('');
      setWhat('principle');
      setAdding(place);
    });
  };

  /** 发一条，回执写在那一条上；没办成返回原因（编辑框里写），办成返回 null */
  const run = useCallback(async (key: string, payload: MemoryEditPayload): Promise<string | null> => {
    setReceipts((r: Record<string, Receipt>) => ({ ...r, [key]: { phase: 'sending', message: '' } }));
    const res: OpResult = await send(payload);
    const ok: boolean = res.phase === 'done';
    const message: string = ok ? res.message || '已办好' : failWords(res);
    setReceipts((r: Record<string, Receipt>) => ({ ...r, [key]: { phase: ok ? 'done' : 'failed', message } }));
    if (ok) {
      window.setTimeout(() => setReceipts((r: Record<string, Receipt>) => {
        const next = { ...r };
        if (next[key]?.phase === 'done') delete next[key];
        return next;
      }), 4000);
    }
    return ok ? null : message;
  }, [send]);

  const groups: MainMemoryGroup[] = useMemo(() => filterGroups(data?.groups ?? [], scope, query), [data, scope, query]);
  if (q.isLoading) return <p className="st-faint">读取中…</p>;
  if (!data?.on) return <div className="st-empty"><p>记忆没开（Covey 的 COVEY_MEMORY），或者 Covey 还没推送记忆</p></div>;
  const options = scopeOptions(data.groups ?? []);
  const places = placeOptions(data);
  const knowledgeOn: boolean = !!data.knowledge;
  const candidates: MainMemoryCandidate[] = (data.candidates ?? []).filter((c: MainMemoryCandidate) =>
    !query.trim() || c.text.toLowerCase().includes(query.trim().toLowerCase()));
  const limit: number = data.limits?.text ?? 200;

  return (
    <div className="mm2" data-testid="main-memory">
      <div className="mm2-top">
        <label className="mm2-search">
          <Search aria-hidden="true" />
          <input type="search" value={query} onChange={(e: React.ChangeEvent<HTMLInputElement>) => setQuery(e.target.value)} placeholder="搜记忆的正文、原因、来源" aria-label="搜记忆" />
          {query ? <button type="button" className="mm2-x" onClick={() => setQuery('')} aria-label="清空搜索"><X /></button> : null}
        </label>
        <div className="mm2-chips" role="tablist" aria-label="按作用域看">
          {options.map((o) => (
            <button key={o.value} type="button" role="tab" aria-selected={scope === o.value} className={scope === o.value ? 'on' : ''} onClick={() => setScope(o.value)}>
              {o.label}<em>{o.count}</em>
            </button>
          ))}
        </div>
        <button type="button" className="mm2-btn pri" onClick={() => startAdd(scope === 'all' ? 'global' : scope)} data-testid="memory-new"><Plus />新建</button>
      </div>
      <p className="mm2-intro">
        这里是每个话题和管家都会读的长期记忆：<b>全局</b>的每一轮都带，<b>工作区</b>的只在那个工作区里带。每组有字数上限，放不下的最早的先不带；
        要一直带上就标<b>常驻</b>。专项和话题的记忆在专项页、话题页的右栏。
      </p>
      {adding ? (
        <Editor
          title="新建一条"
          initial={{ text: '' }}
          limit={limit}
          kinds={data.kinds}
          knowledge={what === 'knowledge'}
          what={{ value: what, onChange: setWhat, knowledgeOn }}
          place={{ options: places, value: adding, onChange: setAdding }}
          saveLabel="记下"
          onSave={async (text: string, kind: string, why: string) => {
            const err: string | null = await run(`new:${adding}`, addPayload(what, adding, text, kind, why));
            if (!err) {
              dirty.current = false;
              setAdding('');
            }
            return err;
          }}
          onCancel={() => { dirty.current = false; setAdding(''); }}
          onDirty={onDirty}
          guard={guard}
        />
      ) : null}
      {Object.entries(receipts).filter(([k, r]) => k.startsWith('new:') && r.phase === 'done').map(([k, r]) => (
        <p key={k} className="mm2-receipt done" role="status"><Check />{r.message}</p>
      ))}
      {candidates.length && (scope === 'all') ? <Candidates rows={candidates} receipts={receipts} run={run} /> : null}
      {groups.map((g: MainMemoryGroup) => (
        <Group
          key={`${g.scope}:${g.workspace}`}
          g={g}
          data={data}
          query={query}
          editing={editing}
          receipts={receipts}
          setEditing={setEditing}
          onDirty={onDirty}
          run={run}
          onAdd={() => startAdd(g.scope === 'global' ? 'global' : `w:${g.workspace}`)}
          guard={adding ? null : guard}
        />
      ))}
      {!groups.length && query ? <p className="mm2-empty">没有搜到“{query}”</p> : null}
      <Preview data={data} />
    </div>
  );
};

export default MainMemory;
