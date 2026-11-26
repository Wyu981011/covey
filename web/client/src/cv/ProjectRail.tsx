import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { Check, ChevronDown, ChevronRight, Copy, FileText, Image as ImageIcon, Loader2, PackageCheck } from 'lucide-react';
import { toast } from 'sonner';
import type { LibraryItem, MemoryItem, SnapshotProject, SnapshotTopic } from '@shared/api.interface';
import { newOpId, useTopicByNumber } from '@client/src/hooks/use-workbench';
import { toDate } from '@client/src/lib/workbench-format';
import { useSendAndWait } from './sendOp';
import { useTick } from './ui';
import { fmtDur, fmtTok, isRunning, topicHref } from './lib';
import { isLayered } from './memoryLayers';
import { MemoryPanel } from './MemoryPanel';
import { MemoryList, useV43ProjectEntries } from './MemoryList';
import './rail.css';

/** 专项右栏（T550 评审第 11 条）：此刻、记忆、文件三块，整栏一起滚，哪块都不裁。
 * - 此刻：前 NOW_FIRST 个在做的话题整张露出，其余折成“还有 N 个在做 · T…”，点开看全部。
 * - 记忆：最近的 MEM_FIRST 条，每条一行摘要，点开看全文、来源和“不对”；“全部 N 条 ›”在栏里展开，可按谁说的筛。
 * - 文件：最近的 FILE_FIRST 个，“全部 N 个 ›”展开；不是网址的（本机路径、交付说明）点开看全文、能复制。
 * 手机和窄屏没有右栏，同一个组件放进专项的“记忆与文件”标签里（mobile）。 */
const NOW_FIRST = 3;
const MEM_FIRST = 5;
const FILE_FIRST = 5;

type Who = 'all' | 'you' | 'ai';
const KIND_WORD: Record<string, string> = {
  decision: '决定', constraint: '约定', style: '写法', practice: '做法', pitfall: '踩过的坑', fact: '事实', question: '待定', preference: '偏好',
};
const SOURCE_WORD: Record<string, string> = { lead: '负责人记下', owner: '你说的', owner_answer: '你回答问题时说的', owner_fix: '你纠正时说的' };

const secOf = (v: number | string | null | undefined): number => (toDate(v)?.getTime() ?? 0) / 1000;
const isYou = (m: MemoryItem): boolean => m.said_by === '你说的';
/** 一行摘要：去掉每条都有的“主人答：”“主人定：”开头，前面的小标已经说了是谁的话；全文不动 */
const summary = (text: string): string => text.replace(/^\s*主人(?:回答|答|定|说)\s*[:：]\s*/u, '');

/** docs/ui.md 第 7 节：今天写 23:10，别的日子写 11-17 23:10 */
function when(v: number | string | null | undefined): string {
  const d: Date | null = toDate(v);
  if (!d) return '';
  const part = (o: Intl.DateTimeFormatOptions): string => d.toLocaleString('zh-CN', { ...o, timeZone: 'Asia/Shanghai' });
  const day = (x: Date): string => x.toLocaleDateString('zh-CN', { timeZone: 'Asia/Shanghai' });
  const hm: string = part({ hour12: false, hour: '2-digit', minute: '2-digit' });
  if (day(d) === day(new Date())) return hm;
  const [mo, da] = [part({ month: 'numeric' }), part({ day: 'numeric' })].map((s: string) => s.replace(/\D/gu, '').padStart(2, '0'));
  return `${mo}-${da} ${hm}`;
}

const isUrl = (s: string | undefined): boolean => !!s && /^https?:\/\//iu.test(s);

/** 块尾的“全部 N 条 ›”/“收起” */
const Fold: React.FC<{ open: boolean; total: number; unit: string; onToggle: () => void }> = ({ open, total, unit, onToggle }) => (
  <button type="button" className="a-rfold" onClick={onToggle}>
    {open ? '收起' : <>全部 {total} {unit}<ChevronRight /></>}
  </button>
);

const NowBlock: React.FC<{ live: SnapshotTopic[] }> = ({ live }) => {
  const now: number = useTick(1000);
  const [all, setAll] = useState<boolean>(false);
  const shown: SnapshotTopic[] = all ? live : live.slice(0, NOW_FIRST);
  const rest: SnapshotTopic[] = live.slice(NOW_FIRST);
  return (
    <div className="rps a-rnow">
      {live.length ? (
        shown.map((t: SnapshotTopic) => (
          <Link key={t.key} to={topicHref(t)} className="nowrow">
            <Loader2 className="sp" />
            <span className="tx"><b>T{t.number} {t.title}</b><small>{t.running?.step_label || '在做…'}</small></span>
            <span className="tm">{t.running?.started_at ? fmtDur(now - t.running.started_at) : ''}</span>
          </Link>
        ))
      ) : (
        <p className="t3 a-rempty">现在没有话题在跑。</p>
      )}
      {rest.length ? (
        all ? (
          <button type="button" className="a-rfold" onClick={() => setAll(false)}>收起</button>
        ) : (
          <button type="button" className="a-rnowmore" onClick={() => setAll(true)}>
            <span className="a-rn">还有 {rest.length} 个在做</span>
            <span className="a-rids">{rest.map((t: SnapshotTopic) => `T${t.number}`).join('、')}</span>
            <ChevronRight />
          </button>
        )
      ) : null}
    </div>
  );
};

const MemRow: React.FC<{ m: MemoryItem; open: boolean; onToggle: () => void; onForget: (m: MemoryItem) => void }> = ({ m, open, onToggle, onForget }) => {
  const byNum = useTopicByNumber();
  const n: number | undefined = m.origin?.topic_number;
  const from: SnapshotTopic | undefined = n ? byNum.get(n) : undefined;
  const kind: string | undefined = m.kind ? KIND_WORD[m.kind] : undefined;
  const src: string | undefined = m.source ? SOURCE_WORD[m.source] : undefined;
  return (
    <div className={`a-mem${open ? ' open' : ''}`}>
      <button type="button" className="a-mrow" onClick={onToggle} aria-expanded={open}>
        <span className={`tag ${isYou(m) ? 'you' : 'ai'}`}>{m.said_by || '记下的'}</span>
        <span className="a-msum">{summary(m.text)}</span>
        <span className="a-mat">{when(m.at)}</span>
      </button>
      {open ? (
        <div className="a-mdet">
          <div className="a-mfull">{m.text}</div>
          <div className="a-mmeta">
            {kind ? <span>{kind}</span> : null}
            {n ? (from ? <Link to={topicHref(from)} className="mono short">来自 T{n}</Link> : <span className="mono short">来自 T{n}</span>) : null}
            {src && src !== m.said_by ? <span>{src}</span> : null}
            {m.at ? <span>{when(m.at)} 记下</span> : null}
            <span className="sp" />
            {m.id ? <button type="button" className="a-mwrong" onClick={() => onForget(m)} title="这条记错了：作废它，以后不再照着做">不对</button> : null}
          </div>
        </div>
      ) : null}
    </div>
  );
};

const MemBlock: React.FC<{ p: SnapshotProject }> = ({ p }) => {
  const sendWait = useSendAndWait();
  const [all, setAll] = useState<boolean>(false);
  const [who, setWho] = useState<Who>('all');
  const [open, setOpen] = useState<string | null>(null);
  const list: MemoryItem[] = [...p.memory].sort((a: MemoryItem, b: MemoryItem) => secOf(b.at) - secOf(a.at));
  const you: number = list.filter(isYou).length;
  const pick: MemoryItem[] = who === 'all' ? list : list.filter((m: MemoryItem) => isYou(m) === (who === 'you'));
  const shown: MemoryItem[] = all ? pick : pick.slice(0, MEM_FIRST);
  // 「不对」：作废这条专项记忆（同飞书专项卡上的删、三层记忆面板的不对），等 Covey 的回执（“已作废：…”）再说结果
  const forget = (m: MemoryItem): void => {
    void sendWait({ op_id: newOpId(), kind: 'forget', project_key: p.key, payload: { project_key: p.key, entry_id: m.id } }, '已发出：作废这条记忆');
  };
  const keyOf = (m: MemoryItem, i: number): string => m.id ?? `i${i}`;
  return (
    <div className="rps a-rblk">
      <div className="sh"><b>记忆</b><span className="n">{list.length}</span><span className="sp" />{list.length ? <span className="a-rhint">最近在上，点一条看全文</span> : null}</div>
      {all && you && you < list.length ? (
        <div className="a-mwho">
          {([['all', `全部 ${list.length}`], ['you', `你说的 ${you}`], ['ai', `它总结的 ${list.length - you}`]] as [Who, string][]).map(([k, label]) => (
            <button key={k} type="button" className={who === k ? 'on' : ''} onClick={() => setWho(k)}>{label}</button>
          ))}
        </div>
      ) : null}
      {list.length ? (
        shown.map((m: MemoryItem, i: number) => (
          <MemRow key={keyOf(m, i)} m={m} open={open === keyOf(m, i)} onToggle={() => setOpen(open === keyOf(m, i) ? null : keyOf(m, i))} onForget={forget} />
        ))
      ) : (
        <p className="t3 a-rempty">还没有记忆。你定下的事、负责人总结的约定会记在这里。</p>
      )}
      {pick.length > MEM_FIRST ? <Fold open={all} total={pick.length} unit="条" onToggle={() => { setAll(!all); if (all) setWho('all'); }} /> : null}
    </div>
  );
};

/** 文件条目的名字：同名的“交付”带上话题号，好分清 */
const fileName = (f: LibraryItem): string => (f.name === '交付' && f.topic_number ? `交付 · T${f.topic_number}` : f.name);
const FileIcon: React.FC<{ f: LibraryItem }> = ({ f }) =>
  f.name === '交付' ? <PackageCheck /> : f.kind === 'image' || /\.(png|jpe?g|gif|webp|svg)$/iu.test(f.name) ? <ImageIcon /> : <FileText />;

const FileRow: React.FC<{ f: LibraryItem; open: boolean; onToggle: () => void }> = ({ f, open, onToggle }) => {
  const [copied, setCopied] = useState<boolean>(false);
  const sub = (
    <div className="sb">
      {f.topic_number && fileName(f) === f.name ? <span className="mono short">T{f.topic_number}</span> : null}
      {f.size ? <span>{fmtTok(f.size).replace('K', ' KB').replace('M', ' MB')}</span> : null}
      {f.at ? <span>{when(f.at)}</span> : null}
    </div>
  );
  const body = (
    <>
      <span className="fic"><FileIcon f={f} /></span>
      <div className="tx"><div className="nm">{fileName(f)}</div>{sub}</div>
    </>
  );
  if (isUrl(f.link)) {
    return <a className="fi" href={f.link} target="_blank" rel="noreferrer">{body}</a>;
  }
  const copy = (): void => {
    void navigator.clipboard?.writeText(f.link || f.name).then(
      () => { setCopied(true); window.setTimeout(() => setCopied(false), 1500); },
      () => toast.error('复制没成功，可以手动选中文字'),
    );
  };
  return (
    <div className={`a-file${open ? ' open' : ''}`}>
      <button type="button" className="fi" onClick={onToggle} aria-expanded={open}>
        {body}
        <ChevronDown className="a-fchev" />
      </button>
      {open && f.link ? (
        <div className="a-fdet">
          <div className="a-ftext">{f.link}</div>
          <button type="button" className="a-fcopy" onClick={copy}>{copied ? <><Check />已复制</> : <><Copy />复制</>}</button>
        </div>
      ) : null}
    </div>
  );
};

const FileBlock: React.FC<{ p: SnapshotProject }> = ({ p }) => {
  const [all, setAll] = useState<boolean>(false);
  const [open, setOpen] = useState<number | null>(null);
  const list: LibraryItem[] = p.library.map((f: LibraryItem, i: number) => ({ f, i })).sort((a, b) => secOf(b.f.at) - secOf(a.f.at) || b.i - a.i).map((x) => x.f);
  const shown: LibraryItem[] = all ? list : list.slice(0, FILE_FIRST);
  return (
    <div className="rps a-rblk">
      <div className="sh"><b>文件</b><span className="n">{list.length}</span></div>
      {list.length ? (
        shown.map((f: LibraryItem, i: number) => <FileRow key={`${i}:${f.name}:${String(f.at ?? '')}`} f={f} open={open === i} onToggle={() => setOpen(open === i ? null : i)} />)
      ) : (
        <p className="t3 a-rempty">还没有文件。话题交付的产物会放在这里。</p>
      )}
      {list.length > FILE_FIRST ? <Fold open={all} total={list.length} unit="个" onToggle={() => { setAll(!all); setOpen(null); }} /> : null}
    </div>
  );
};

/** 专项的右栏；mobile 时铺满“记忆与文件”标签 */
const ProjectRail: React.FC<{ p: SnapshotProject; topics: SnapshotTopic[]; mobile?: boolean }> = ({ p, topics, mobile }) => {
  const live: SnapshotTopic[] = topics.filter(isRunning);
  // v43：记忆中心推了这个专项的键就画精简清单（规矩、在办决定，点了去记忆中心）；旧 Covey 照旧
  const v43 = useV43ProjectEntries(p.key);
  return (
    <aside className={mobile ? 'a-prail a-prmob' : 'rp a-prail'}>
      {mobile && p.goal ? <div className="a-pgoal"><b>目标</b>{p.goal.replace(/^\s*目标\s*[:：]\s*/u, '')}</div> : null}
      <div className="rph"><h2>此刻</h2>{live.length ? <><span className="a-rcnt">{live.length} 在做</span><span className="live"><i />实时</span></> : mobile ? <span className="a-rnone">没有话题在跑</span> : null}</div>
      {/* 手机上没有在做的就只占标题这一行，不再单独一块“现在没有话题在跑。” */}
      {mobile && !live.length ? null : <NowBlock live={live} />}
      {/* v31：记忆分了层就按长期约定｜当前决定｜历史记录画；旧数据照旧（MemBlock） */}
      {Array.isArray(v43) ? <div className="rps a-rblk"><MemoryList entries={v43} scope={`p:${p.key}`} /></div>
        : isLayered(p.memory) ? <MemoryPanel items={p.memory} scope={{ project_key: p.key }} version={p.memory_version} /> : <MemBlock p={p} />}
      <FileBlock p={p} />
    </aside>
  );
};
export default ProjectRail;
