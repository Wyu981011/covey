import React, { useMemo, useRef, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { MessageSquareQuote, X } from 'lucide-react';
import type { ChecklistItem, PlanItem, SnapshotProject, SnapshotResponse, SnapshotTopic, TurnView } from '@shared/api.interface';
import { useIsDesktop } from '@client/src/hooks/use-breakpoint';
import { useTurns } from '@client/src/hooks/use-workbench';
import { getDraft, setDraft } from '@client/src/lib/conv-store';
import { TopicBadge } from './RoleAvatar';
import { useTick } from './ui';
import { engineText, shortWhen, toneOf, topicHref } from './lib';
import { topicColor } from './look.gen';
import { firstParagraph, lastDoneAgent, shownText } from './topicText';
import { board, projectDecisions, quoteOf, withQuote, type Board, type Decision, type Placed } from './progressData';
import { useV43ProjectEntries } from './MemoryList';
import {
  ACT_CLS, ACT_ICON, ACT_ORDER, ACT_WORD, briefOf, edgeOn, fitText, GBOX, itemKind, itemName, ITEM_ICON, ITEM_WORD, lastWord, nextStepOf, phaseOf, positionOf, quoteAction,
  quoteTopic, restWords, sessionsOf, stepLine, topicRefs, TONE_CLS, TONE_ICON, toneWordOf, traceOf, waitsOwner,
  type ActionView, type ActState, type Brief, type FeedRow, type ItemKind, type OwnerRow, type Position, type Trace,
} from './briefData';
import ProjectProgress from './ProjectProgress';
import './brief.css';

/* 专项的「简报」标签（v41）：头部 # 名、背景、目标、统计；动作卡（负责人一句、自动一行、对应的话题、检查表展开）；任务图；近 10 条决定；
 * 右栏等你、和负责人说、简报动态；点话题打开详情抽屉（位置和影响在最上面）。算法在 briefData.ts，全在网页上现算。
 * 负责人还没写背景和动作时退回第一期的三栏（ProjectProgress）。状态不只靠颜色：每处都带图标和字。 */

/** 状态胶囊：图标加字。短标签不折行（tags.css 的 .short） */
const Pl: React.FC<{ cls: string; icon: string; word: string; extra?: string }> = ({ cls, icon, word, extra }) => (
  <span className={`pb-pl short pb-s-${cls}`}><b aria-hidden="true">{icon}</b>{word}{extra}</span>
);
export const ActPill: React.FC<{ state: ActState }> = ({ state }) => <Pl cls={ACT_CLS[state]} icon={ACT_ICON[state]} word={ACT_WORD[state]} />;
const TonePill: React.FC<{ t: SnapshotTopic }> = ({ t }) => <Pl cls={TONE_CLS[toneOf(t)]} icon={TONE_ICON[toneOf(t)]} word={toneWordOf(t)} />;

/** 一排 T 号小块：点了打开那个话题的详情 */
const TopicChip: React.FC<{ t: SnapshotTopic; pick: (key: string) => void }> = ({ t, pick }) => (
  <button type="button" className={`pb-sc short pb-s-${TONE_CLS[toneOf(t)]}`} aria-label={`T${t.number} ${toneWordOf(t)}`} title={`T${t.number} ${t.title} · ${toneWordOf(t)}`} onClick={(e) => { e.stopPropagation(); pick(t.key); }}>
    <TopicBadge number={t.number} /><b aria-hidden="true">{TONE_ICON[toneOf(t)]}</b>
  </button>
);

/** 话题一行：状态、阶段和第几步、在等你什么、下一步、最后结论、位置（交付哪条、前置、解锁）和「在任务图里看」 */
const SessionRow: React.FC<{ b: Brief; v: ActionView; t: SnapshotTopic; now: number; pick: (key: string) => void; graph: (key: string) => void }> = ({ b, v, t, now, pick, graph }) => {
  const pos: Position = positionOf(b, t.key);
  const phase: string = phaseOf(t);
  const step: string = stepLine(t);
  const ask: string = t.progress?.waiting ?? '';
  const next: string = nextStepOf(t);
  const last: string = lastWord(t);
  const also: string = (b.byTopic.get(t.key) ?? []).filter((x: ActionView) => x !== v).map((x: ActionView) => x.n).join('、');
  const meta: string = [phase ? `阶段：${phase}` : '', step, shortWhen(t.updated_at, now), also ? `也在动作 ${also}` : ''].filter(Boolean).join(' · ');
  return (
    <div role="button" tabIndex={0} className={`pb-ss pb-s-${TONE_CLS[toneOf(t)]}`} onClick={() => pick(t.key)} onKeyDown={(e) => { if (e.key === 'Enter') pick(t.key); }}>
      <div className="pb-sh"><TopicBadge number={t.number} /><span className="pb-st" title={t.title}>{t.title}</span><TonePill t={t} /></div>
      {meta ? <div className="pb-sm" title={meta}>{meta}</div> : null}
      {ask || (waitsOwner(t, b.ctx.asked) && toneOf(t) === 'waiting') ? (
        <div className="pb-sq" title={ask}><b>在等你：</b>{ask || '有事等你定'}</div>
      ) : next ? (
        <div className="pb-sx" title={next}><b>下一步：</b>{next}</div>
      ) : null}
      {last ? <div className={`pb-sa${toneOf(t) === 'stopped' ? ' bad' : ''}`} title={last}><b>结论：</b>{last}</div> : null}
      <div className={`pb-sp${pos.mine.length ? '' : ' none'}`}>
        <b>位置：</b><span className="pb-spt" title={pos.line}>{pos.line}</span>
        <button type="button" className="pb-hlk short" onClick={(e) => { e.stopPropagation(); graph(t.key); }}>在任务图里看 ›</button>
      </div>
    </div>
  );
};

/** 展开的检查表条目：状态、证据、缺口或尾巴、在等谁、交付它的话题 */
const ItemRow: React.FC<{ it: ChecklistItem; b: Brief; pick: (key: string) => void; discuss: (id: string) => void }> = ({ it, b, pick, discuss }) => {
  const k: ItemKind = itemKind(it);
  const waits: string[] = it.needs.filter((n: string) => b.ctx.items.has(n) && !['done', 'dropped'].includes(b.ctx.items.get(n)?.state ?? ''));
  const ts: SnapshotTopic[] = topicRefs(it).map((r: string) => b.ctx.topics.get(b.ctx.keyOf(r))).filter((t): t is SnapshotTopic => !!t);
  return (
    <div className="pb-ir">
      <Pl cls={k === 'wait' ? 'wait' : k === 'done' ? 'done' : k === 'stop' ? 'stop' : 'next'} icon={ITEM_ICON[k]} word={ITEM_WORD[k]} />
      <b className="pb-iid">{it.id}</b>
      <div className="pb-ib">
        <div className="pb-ic" title={it.criterion}>{it.title ? <b>{it.title}</b> : null}{it.criterion}</div>
        {waits.length ? <div className="pb-ig">在等 {waits.join('、')}</div> : null}
        {it.evidence ? <div className="pb-ie" title={it.evidence}><b>证据：</b>{it.evidence}</div> : null}
        {it.gap ? <div className="pb-ig" title={it.gap}><b>{it.state === 'done' ? '尾巴：' : '缺口：'}</b>{it.gap}</div> : null}
      </div>
      <div className="pb-it">
        {ts.map((t: SnapshotTopic) => <button key={t.key} type="button" className="pb-tl" aria-label={`T${t.number}`} onClick={() => pick(t.key)}><TopicBadge number={t.number} /></button>)}
        <button type="button" className="pb-go short" onClick={() => discuss(it.id)}>讨论 ›</button>
      </div>
    </div>
  );
};

const ActionCard: React.FC<{
  b: Brief; v: ActionView; now: number; open: boolean; toggle: () => void; pick: (key: string) => void; graph: (key: string) => void; say: (quote: string) => void; canSay: boolean; discuss: (id: string) => void;
}> = ({ b, v, now, open, toggle, pick, graph, say, canSay, discuss }) => {
  const { shown, rest } = sessionsOf(v, b.ctx.asked);
  return (
    <section className={`pb-act pb-s-${ACT_CLS[v.state]}`} id={`pb-${v.action.id}`}>
      <div className="pb-ah">
        <span className="pb-an">{v.n}.</span>
        <span className="pb-at" title={v.action.title}>{v.action.title}</span>
        <ActPill state={v.state} />
        <button type="button" className="pb-ax short" aria-expanded={open} onClick={toggle}>检查表 {v.met}/{v.items.length} · {open ? '收起' : '展开'} ›</button>
        <button type="button" className="pb-aq" disabled={!canSay} aria-label="和负责人说这个动作" title="和负责人说这个动作" onClick={() => say(quoteAction(v))}><MessageSquareQuote /></button>
      </div>
      {v.action.note ? <div className="pb-al"><span className="pb-lead short">负责人</span><span>{v.action.note}</span></div> : null}
      <div className="pb-au"><span className="pb-auto short">自动</span><span>{v.auto || '还没有检查表条目和话题'}</span></div>
      {v.gaps.slice(0, 2).map((g) => (
        <div key={g.id} className="pb-gp" title={g.text}><b>⚠ 缺口</b>{b.ctx.topics.get(b.ctx.keyOf(g.thread)) ? <span className="pb-gt">T{b.ctx.topics.get(b.ctx.keyOf(g.thread))?.number}</span> : null}<span>{g.text}</span></div>
      ))}
      {v.gaps.length > 2 ? <div className="pb-gp"><b>⚠ 缺口</b><span>还有 {v.gaps.length - 2} 条</span></div> : null}
      {open ? <div className="pb-ai">{v.items.length ? v.items.map((it: ChecklistItem) => <ItemRow key={it.id} it={it} b={b} pick={pick} discuss={discuss} />) : <p className="pb-muted">这个动作还没有检查表条目</p>}</div> : null}
      <div className="pb-ab">
        {v.state === 'done' ? (
          <div className="pb-ac">{rest.map((t: SnapshotTopic) => <TopicChip key={t.key} t={t} pick={pick} />)}<span className="pb-muted">{rest.length ? `${rest.length} 个话题，点开看结论` : '没有挂话题'}</span></div>
        ) : (
          <>
            {shown.map((t: SnapshotTopic) => <SessionRow key={t.key} b={b} v={v} t={t} now={now} pick={pick} graph={graph} />)}
            {!v.topics.length ? <p className="pb-muted">还没有话题挂在这个动作上</p> : null}
            {rest.length ? (
              <div className="pb-ac pb-more">
                <span>更早的 {rest.length} 个话题（{restWords(rest)}）：</span>
                {rest.map((t: SnapshotTopic) => <TopicChip key={t.key} t={t} pick={pick} />)}
              </div>
            ) : null}
          </>
        )}
      </div>
    </section>
  );
};

/** 等你一块：条目的下一步在你手上、话题在等你；点条目带着它和负责人讨论，点话题去话题页 */
const OwnerList: React.FC<{ rows: OwnerRow[]; discuss: (id: string) => void }> = ({ rows, discuss }) => (
  <>
    {rows.map((r: OwnerRow) =>
      r.kind === 'item' && r.item ? (
        <button key={r.item.id} type="button" className="pb-ow" onClick={() => discuss((r.item as ChecklistItem).id)}>
          <span className="pb-oi" aria-hidden="true">!</span>
          <span className="pb-ob">
            <span className="pb-ot">{r.n ? `动作 ${r.n} · ` : ''}{r.item.id}<span className="pb-ou">{itemName(r.item)}</span></span>
            <span className="pb-od" title={r.text}>要你做：{r.text || '负责人标了在你手上'}</span>
          </span>
          <span className="pb-go short">讨论 ›</span>
        </button>
      ) : r.topic ? (
        <Link key={r.topic.key} to={topicHref(r.topic)} className="pb-ow">
          <span className="pb-oi" aria-hidden="true">?</span>
          <span className="pb-ob">
            <span className="pb-ot">{r.n ? `动作 ${r.n} · ` : ''}<TopicBadge number={r.topic.number} /><span className="pb-ou">{r.topic.title}</span></span>
            <span className="pb-od" title={r.text}>在等你：{r.text || '有事等你定'}</span>
          </span>
          <span className="pb-go short">去看 ›</span>
        </Link>
      ) : null,
    )}
    {!rows.length ? <span className="pb-muted">没有卡在你手上的</span> : null}
  </>
);

/** 头部：# 名、背景、目标、统计（几个动作、各状态几个、话题数、检查表）；手机上等你收成一块放在这里 */
const Doc: React.FC<{ p: SnapshotProject; b: Brief; now: number; mobile: boolean; discuss: (id: string) => void }> = ({ p, b, now, mobile, discuss }) => (
  <section className="pb-card pb-doc">
    <h1># {p.title}</h1>
    <div className="pb-kv">
      {b.background ? <><b>背景：</b><span>{b.background}</span></> : null}
      {b.goal ? <><b>目标：</b><span>{b.goal}</span></> : null}
    </div>
    <div className="pb-sum">
      <b>{b.actions.length} 个动作</b>
      <div className="pb-bar" role="img" aria-label={ACT_ORDER.map((k: ActState) => `${ACT_WORD[k]} ${b.counts[k]}`).join('，')}>
        {ACT_ORDER.map((k: ActState) => (b.counts[k] ? <i key={k} className={`pb-s-${ACT_CLS[k]}`} style={{ flex: b.counts[k] }} title={`${ACT_WORD[k]} ${b.counts[k]}`} /> : null))}
      </div>
      {ACT_ORDER.filter((k: ActState) => b.counts[k]).map((k: ActState) => <span key={k} className={`pb-lg pb-s-${ACT_CLS[k]}`}><b aria-hidden="true">{ACT_ICON[k]}</b> {ACT_WORD[k]} {b.counts[k]}</span>)}
      <span>· {b.members.length} 个话题（{b.liveN} 在跑）· 检查表 {b.met}/{b.total} 满足</span>
      {b.unmapped.length ? <span className="pb-muted" title={b.unmapped.map((t: SnapshotTopic) => `T${t.number}`).join('、')}>· {b.unmapped.length} 个话题还没挂到条目上</span> : null}
      {b.changedAt ? <span className="pb-muted pb-fresh">负责人 {shortWhen(b.changedAt, now)} 改过简报</span> : null}
    </div>
    {mobile && b.owner.length ? (
      <div className="pb-mwait">
        <b><span className="pb-oi" aria-hidden="true">!</span> 等你 {b.owner.length}</b>
        <OwnerList rows={b.owner} discuss={discuss} />
      </div>
    ) : null}
  </section>
);

/** 任务图：一个动作一行，条目上标交付它的话题；选中一个话题时它交付的条目粗框，前置和被它解锁的连线变蓝，其余变淡 */
const TaskGraph: React.FC<{ b: Brief; hl: string | null; pick: (key: string) => void; graph: (key: string | null) => void; wrap: React.RefObject<HTMLElement> }> = ({ b, hl, pick, graph, wrap }) => {
  const g = b.graph;
  const tr: Trace | null = hl ? traceOf(b, hl) : null;
  const pos: Position | null = hl ? positionOf(b, hl) : null;
  const sel: SnapshotTopic | undefined = hl ? b.ctx.topics.get(hl) : undefined;
  const at = new Map<string, { x: number; y: number }>(g.nodes.map((n) => [n.id, { x: n.x, y: n.y }]));
  const { NW, NH, LW } = GBOX;
  const act = (id: string): ActionView | undefined => b.actions.find((v: ActionView) => v.action.id === id);
  const ids = (s: ReadonlySet<string>): string => [...s].sort((x: string, y: string) => Number(x.slice(1)) - Number(y.slice(1))).join('、') || '没有';
  return (
    <section className="pb-card pb-dep" ref={wrap}>
      <h3 className="pb-h">任务图：每条做完的事在哪、解锁谁<span className="pb-hint">一个动作一行；有依赖的条目从左往右按先后；条目右边是交付它的话题</span></h3>
      {tr && pos ? (
        <div className="pb-tgc">
          {sel ? <><TopicBadge number={sel.number} /><span>{sel.title}：{pos.line}</span></> : <span>{pos.line}</span>}
          <span className="pb-tgl"><i className="pb-k1" />它交付 <i className="pb-k2" />前置（一路往前）{ids(tr.up)} <i className="pb-k3" />被它解锁（一路往后）{ids(tr.down)}</span>
          <button type="button" className="pb-go short" onClick={() => graph(null)}>清除 ✕</button>
        </div>
      ) : (
        <div className="pb-tgc">点任一话题的「在任务图里看 ›」：它交付的条目加粗框，一路往前的前置、一路往后被它解锁的连线变蓝，其余变淡。</div>
      )}
      {!g.nodes.length ? (
        <p className="pb-muted">检查表里还没有条目</p>
      ) : (
        <div className={`pb-tg${tr ? ' hl' : ''}`}>
          {/* 全局 svg 规则把图标定成 16px、描边：这里写死尺寸 */}
          <svg width={g.width} height={g.height} style={{ width: g.width, height: g.height }} viewBox={`0 0 ${g.width} ${g.height}`} role="img" aria-label="任务图">
            <defs>
              <marker id="pb-ar" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L8,4 L0,8 z" className="pb-arh" /></marker>
              <marker id="pb-ar2" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L8,4 L0,8 z" className="pb-arh on" /></marker>
            </defs>
            {g.lanes.map((l, i) => {
              const v: ActionView | undefined = act(l.id);
              return (
                <g key={l.id || 'loose'} className={`pb-lane${tr?.acts.includes(l.id) && l.id ? ' mine' : ''}`}>
                  <rect x={0} y={l.y - GBOX.LP / 2} width={g.width} height={l.h + GBOX.LP} rx={6} className={`pb-lb${i % 2}`} />
                  <text x={10} y={l.y + 19} className="pb-ll">{v ? `${v.n}. ${fitText(v.action.title, 20)}` : '没挂动作'}</text>
                  {v ? <text x={LW - 14} y={l.y + 19} className={`pb-lsi pb-s-${ACT_CLS[v.state]}`} textAnchor="end">{ACT_ICON[v.state]}</text> : null}
                </g>
              );
            })}
            {g.edges.map((e) => {
              const a = at.get(e.from);
              const z = at.get(e.to);
              if (!a || !z) return null;
              const on: boolean = !!tr && edgeOn(tr, e);
              return <path key={`${e.from}>${e.to}`} className={`pb-ge${on ? ' on' : ''}`} d={`M${a.x + NW},${a.y + NH / 2} C${a.x + NW + 18},${a.y + NH / 2} ${z.x - 18},${z.y + NH / 2} ${z.x - 2},${z.y + NH / 2}`} markerEnd={on ? 'url(#pb-ar2)' : 'url(#pb-ar)'} />;
            })}
            {g.nodes.map((n) => {
              const it: ChecklistItem | undefined = b.ctx.items.get(n.id);
              if (!it) return null;
              const k: ItemKind = itemKind(it);
              const tk: string = b.ctx.keyOf(it.topic);
              const t: SnapshotTopic | undefined = b.ctx.topics.get(tk);
              const role: string = !tr ? '' : tr.self.has(n.id) ? ' self' : tr.up.has(n.id) ? ' up' : tr.down.has(n.id) ? ' down' : '';
              return (
                <g
                  key={n.id}
                  className={`pb-gn pb-k-${k}${role}${t ? ' tap' : ''}`}
                  transform={`translate(${n.x},${n.y})`}
                  role={t ? 'button' : undefined}
                  tabIndex={t ? 0 : undefined}
                  onClick={t ? () => graph(hl === tk ? null : tk) : undefined}
                  onKeyDown={t ? (e) => { if (e.key === 'Enter') graph(hl === tk ? null : tk); } : undefined}
                >
                  <title>{`${it.id} ${it.criterion} · ${ITEM_WORD[k]}${t ? ` · T${t.number} 交付` : ''}`}</title>
                  <rect width={NW} height={NH} rx={6} className="pb-gr" />
                  <text x={8} y={19}><tspan className="pb-ni">{ITEM_ICON[k]}</tspan> <tspan className="pb-nid">{it.id}</tspan> {fitText(itemName(it), t ? 12 : 17)}</text>
                  {t ? (
                    <g onClick={(e) => { e.stopPropagation(); pick(t.key); }}>
                      <rect x={NW - 36} y={6} width={31} height={18} rx={4} className="pb-gtb" style={{ fill: topicColor(t.number) ?? 'var(--t3)' }} />
                      <text x={NW - 20.5} y={19} className="pb-gtn" textAnchor="middle">T{t.number}</text>
                    </g>
                  ) : null}
                </g>
              );
            })}
          </svg>
        </div>
      )}
    </section>
  );
};

const Decisions: React.FC<{ rows: Decision[]; now: number; v43?: boolean }> = ({ rows, now, v43 }) => (
  <section className="pb-card pb-dec">
    <h3 className="pb-h">近 10 条决定<span className="pb-hint">{v43 ? '决定记录，新的在前' : '主人答过的，自动记'}</span></h3>
    {rows.length ? (
      rows.map((d: Decision) => (
        <div key={d.id || d.text} className="pb-dc" title={d.text}>
          <span className="pb-tm">{shortWhen(d.at, now)}</span>
          {d.number ? <TopicBadge number={d.number} /> : null}
          <span className="pb-dq">{d.question}</span>
          {d.answer ? <span className="pb-da">→ {d.answer}</span> : null}
        </div>
      ))
    ) : (
      <p className="pb-muted">还没有决定</p>
    )}
  </section>
);

/** 右栏：等你、和负责人说（放进负责人对话的输入框再切过去）、简报动态 */
const Rail: React.FC<{ b: Brief; now: number; canSay: boolean; say: (text: string) => void; discuss: (id: string) => void }> = ({ b, now, canSay, say, discuss }) => {
  const [text, setText] = useState<string>('');
  const put = (): void => {
    if (!text.trim() || !canSay) return;
    say(text.trim());
    setText('');
  };
  return (
    <aside className="pb-rail">
      <section className="pb-card pb-owner" aria-label="等你">
        <h3 className="pb-h"><span className="pb-oi sm" aria-hidden="true">!</span>等你 {b.owner.length}<span className="pb-hint">条目和话题里要你做的</span></h3>
        <OwnerList rows={b.owner} discuss={discuss} />
      </section>
      <section className="pb-card pb-talk">
        <h3 className="pb-h">和负责人说<span className="pb-hint">改背景、目标、动作</span></h3>
        <textarea
          className="pb-say"
          rows={3}
          value={text}
          disabled={!canSay}
          placeholder={canSay ? '对负责人说一句，比如“把 T91 也挂到动作 3”“动作 4 拆成两条”…' : '这个专项还没有负责人对话'}
          onChange={(e) => setText(e.target.value)}
        />
        <div className="pb-sayn">
          <span>放进「对话」的输入框，发出去和在那里说一样；它用工具改简报，这一页跟着变</span>
          <button type="button" className="btn sm pri short" disabled={!canSay || !text.trim()} onClick={put}>放进对话 ›</button>
        </div>
      </section>
      <section className="pb-card pb-feed">
        <h3 className="pb-h">简报动态<span className="pb-hint">话题的检查点和结束回执自动改动作</span></h3>
        {b.feed.map((f: FeedRow) => (
          <div key={`${f.who}-${f.at}-${f.topic?.key ?? f.text}`} className="pb-fd">
            <span className="pb-tm">{shortWhen(f.at, now)}</span>
            {f.topic ? <TopicBadge number={f.topic.number} /> : <span className="pb-who short">负责人</span>}
            <span className="pb-ft" title={f.text}>{f.text}</span>
            <span className={`pb-${f.who === 'lead' ? 'lead' : 'auto'} short`}>{f.who === 'lead' ? '负责人' : '自动'}</span>
          </div>
        ))}
        {!b.feed.length ? <p className="pb-muted">还没有动态</p> : null}
      </section>
    </aside>
  );
};

const Row: React.FC<{ k: string; children: React.ReactNode }> = ({ k, children }) => (
  <>
    <div className="pb-dl">{k}</div>
    <div className="pb-dv">{children}</div>
  </>
);

/** 位置那一格里的一个条目：状态、编号、短标题、交付它的话题 */
const FlowChip: React.FC<{ id: string; b: Brief; me?: boolean }> = ({ id, b, me }) => {
  const it: ChecklistItem | undefined = b.ctx.items.get(id);
  if (!it) return null;
  const k: ItemKind = itemKind(it);
  const t: SnapshotTopic | undefined = b.ctx.topics.get(b.ctx.keyOf(it.topic));
  return (
    <div className={`pb-pq pb-k-${k}${me ? ' me' : ''}`} title={`${it.id} ${it.criterion} · ${ITEM_WORD[k]}`}>
      <b aria-hidden="true">{ITEM_ICON[k]}</b><span className="pb-pqi">{it.id}</span><span className="pb-pqt">{itemName(it)}</span>{t && !me ? <TopicBadge number={t.number} /> : null}
    </div>
  );
};

/** 话题详情抽屉：位置和影响在最上面；步骤清单用最新一轮的 plan（同全图抽屉取步骤的写法）；「打开话题」 */
const SessionDrawer: React.FC<{ b: Brief; t: SnapshotTopic; now: number; graph: (key: string) => void; canSay: boolean; say: (quote: string) => void; onClose: () => void }> = ({ b, t, now, graph, canSay, say, onClose }) => {
  const nav = useNavigate();
  const { data } = useTurns(t.key);
  const turns: TurnView[] = data?.turns ?? [];
  const agent: TurnView[] = turns.filter((x: TurnView) => x.role !== 'owner' && x.role !== 'event');
  const cur: TurnView | undefined = agent.find((x: TurnView) => x.status === 'running') ?? agent[agent.length - 1];
  const plan: PlanItem[] = cur?.plan ?? [];
  const planDone: number = plan.filter((x: PlanItem) => x.state === 'done').length;
  const done: TurnView | undefined = lastDoneAgent(turns);
  const answer: string = (done ? firstParagraph(shownText(done), 260) : '') || lastWord(t);
  const pos: Position = positionOf(b, t.key);
  const acts: ActionView[] = b.byTopic.get(t.key) ?? [];
  const ask: string = t.progress?.waiting ?? '';
  const phase: string = phaseOf(t);
  const next: string = nextStepOf(t);
  const goal: string = t.gist?.goal || t.gist?.essence || '';
  return (
    <div className="drawer pb-drw" role="dialog" aria-label={`T${t.number} 详情`}>
      <div className="dh">
        <div className="pb-dh">
          <TopicBadge number={t.number} />
          <b className="pb-dt" title={t.title}>{t.title}</b>
          <a role="button" aria-label="关闭" onClick={onClose} className="pb-x"><X /></a>
        </div>
        <div className="pb-dsub">
          <TonePill t={t} />
          <span>{[t.round ? `第 ${t.round} 轮` : '', t.started_at ? `${shortWhen(t.started_at, now)} 开始` : '', `${shortWhen(t.updated_at, now)} 最后动静`, engineText(t)].filter(Boolean).join(' · ')}</span>
        </div>
      </div>
      <div className="pb-dbody">
        {acts.length ? (
          <Row k="在哪个动作">
            {acts.map((v: ActionView) => <div key={v.action.id} className="pb-da2">动作 {v.n}「{v.action.title}」<ActPill state={v.state} /></div>)}
          </Row>
        ) : null}
        <div className="pb-dl">在项目里的位置和影响 <button type="button" className="pb-hlk short" onClick={() => graph(t.key)}>在任务图里看 ›</button></div>
        <div className="pb-dv">
          {pos.mine.length ? (
            <div className="pb-pf3">
              <div className="pb-pcol"><div className="pb-phd">前置</div>{pos.up.map((c: string) => <FlowChip key={c} id={c} b={b} />)}{!pos.up.length ? <div className="pb-muted">没有</div> : null}{pos.upMore.length ? <div className="pb-muted">再往前 {pos.upMore.join('、')}</div> : null}</div>
              <div className="pb-parr" aria-hidden="true">→</div>
              <div className="pb-pcol"><div className="pb-phd"><TopicBadge number={t.number} /> 交付</div>{pos.mine.map((c: string) => <FlowChip key={c} id={c} b={b} me />)}</div>
              <div className="pb-parr" aria-hidden="true">→</div>
              <div className="pb-pcol"><div className="pb-phd">解锁</div>{pos.down.map((c: string) => <FlowChip key={c} id={c} b={b} />)}{!pos.down.length ? <div className="pb-muted">没有</div> : null}{pos.downMore.length ? <div className="pb-muted">再往后 {pos.downMore.join('、')}</div> : null}</div>
            </div>
          ) : (
            <div className="pb-pnone">这个话题还没挂到检查表条目上（{pos.acts.length ? `只在${pos.acts.map((v: ActionView) => `动作 ${v.n}`).join('、')}` : '也没挂到动作'}），看不出它做完的事算进哪一条、解锁什么。负责人开话题或核对时写它交付哪条，这里就有了。</div>
          )}
          <ul className="pb-pfx">{pos.effects.map((x: string) => <li key={x}>{x}</li>)}</ul>
        </div>
        {goal ? <Row k="这个话题要做成什么">{goal}</Row> : null}
        {phase ? <Row k="此刻阶段">{phase}</Row> : null}
        {plan.length ? (
          <Row k={`步骤 ${planDone}/${plan.length}${pos.mine.length ? `（算进 ${pos.mine.join('、')}）` : ''}`}>
            {plan.map((s: PlanItem, i: number) => (
              <div key={`${i}-${s.title}`} className={`pb-stp ${s.state === 'done' ? 'done' : s.state === 'doing' ? 'doing' : ''}`}>
                <b aria-hidden="true">{s.state === 'done' ? '✓' : s.state === 'doing' ? '▶' : '○'}</b>{s.title}
              </div>
            ))}
          </Row>
        ) : null}
        {next ? <Row k="下一步">{next}</Row> : null}
        {ask || (waitsOwner(t, b.ctx.asked) && toneOf(t) === 'waiting') ? <Row k="在等你"><span className="pb-wait">{ask || '有事等你定'}</span></Row> : null}
        {answer ? <Row k="最后结论">{answer}</Row> : null}
        <div className="pb-btns">
          <button type="button" className="btn pri short" onClick={() => nav(topicHref(t))}>打开话题 ›</button>
          <button type="button" className="btn short" disabled={!canSay} onClick={() => say(quoteTopic(t))}>和负责人说</button>
        </div>
        <p className="pb-hint2">这个话题更新检查点或结束时，Bridge 自动改它所在动作的状态和“自动”那一行；它报的协作缺口挂在这个动作上。负责人核对后改检查表条目，动作才算做完。</p>
      </div>
    </div>
  );
};

const ProjectBrief: React.FC<{ p: SnapshotProject; snap: SnapshotResponse; lead: SnapshotTopic | undefined; base: string }> = ({ p, snap, lead, base }) => {
  const desktop: boolean = useIsDesktop();
  const nav = useNavigate();
  const now: number = useTick(30000);
  const [params, setParams] = useSearchParams();
  const sel: string | null = params.get('s');
  const hl: string | null = params.get('hl');
  const [open, setOpen] = useState<ReadonlySet<string>>(new Set<string>());
  const tg = useRef<HTMLElement>(null);
  const b: Brief = useMemo(() => briefOf(p, snap, now), [p, snap, now]);
  const topicsByKey = useMemo(() => new Map<string, SnapshotTopic>(snap.topics.map((t: SnapshotTopic) => [t.key, t])), [snap.topics]);
  const placed: Board = useMemo(() => board(p.checklist, topicsByKey), [p.checklist, topicsByKey]);
  // v43：读记忆中心里这个专项的决定记录（memory:p:<专项>）；旧 Covey 照旧读专项记忆里主人答过的
  const v43 = useV43ProjectEntries(p.key);
  const decisions: Decision[] = useMemo(() => projectDecisions(p.memory, v43, snap.topics, 10), [p.memory, v43, snap.topics]);
  const keep = (k: string, v: string | null, also?: [string, string | null]): void => {
    const n = new URLSearchParams(params);
    for (const [key, val] of [[k, v], ...(also ? [also] : [])] as [string, string | null][]) {
      if (val === null) n.delete(key);
      else n.set(key, val);
    }
    setParams(n, { replace: true });
  };
  const pick = (key: string): void => keep('s', sel === key ? null : key);
  const graph = (key: string | null): void => {
    keep('hl', key, ['s', null]);
    if (key) window.requestAnimationFrame(() => tg.current?.scrollIntoView({ block: 'start', behavior: 'smooth' }));
  };
  // 和负责人说：引用放进负责人对话的输入框（原来的草稿接在后面）再切到对话，发送走现有的 say（同第一期「带着这条和负责人讨论」）
  const say = (quote: string): void => {
    if (!lead) return;
    setDraft(lead.key, withQuote(quote, getDraft(lead.key)));
    nav(base);
  };
  const sayText = (text: string): void => {
    if (!lead) return;
    const cur: string = getDraft(lead.key).trim();
    setDraft(lead.key, cur ? `${text}\n${cur}` : text);
    nav(base);
  };
  const discuss = (id: string): void => {
    const x: Placed | undefined = placed.byId.get(id);
    if (x) say(quoteOf(x));
  };
  if (!b.has) return <ProjectProgress p={p} snap={snap} lead={lead} base={base} hint="负责人还没写背景和动作" />;
  const cur: SnapshotTopic | undefined = sel ? topicsByKey.get(sel) : undefined;
  const toggle = (id: string): void => setOpen((s: ReadonlySet<string>) => {
    const n = new Set<string>(s);
    if (n.has(id)) n.delete(id);
    else n.add(id);
    return n;
  });
  return (
    <div className="pb-wrap">
      <div className={`pb${desktop ? '' : ' pb-m'}`}>
        <div className="pb-main">
          <div className="pb-left">
            <Doc p={p} b={b} now={now} mobile={!desktop} discuss={discuss} />
            <h2 className="pb-h2">动作<span className="pb-hint">每个动作下面是它对应的话题（session）；状态按检查表和话题自动算，负责人那句话单独写</span></h2>
            {b.actions.map((v: ActionView) => (
              <ActionCard
                key={v.action.id}
                b={b}
                v={v}
                now={now}
                open={open.has(v.action.id)}
                toggle={() => toggle(v.action.id)}
                pick={pick}
                graph={graph}
                say={say}
                canSay={!!lead}
                discuss={discuss}
              />
            ))}
            {b.strayGaps.length ? (
              <section className="pb-card pb-stray">
                <h3 className="pb-h">没挂到动作的缺口 {b.strayGaps.length}<span className="pb-hint">报缺口的话题不在任何动作里，请负责人挂上</span></h3>
                {b.strayGaps.map((g) => <div key={g.id} className="pb-gp" title={g.text}><b>⚠ 缺口</b><span>{g.text}</span></div>)}
              </section>
            ) : null}
            <TaskGraph b={b} hl={hl} pick={pick} graph={graph} wrap={tg} />
            <Decisions rows={decisions} now={now} v43={Array.isArray(v43)} />
          </div>
          <Rail b={b} now={now} canSay={!!lead} say={sayText} discuss={discuss} />
        </div>
      </div>
      {cur ? <SessionDrawer key={cur.key} b={b} t={cur} now={now} graph={graph} canSay={!!lead} say={say} onClose={() => keep('s', null)} /> : null}
    </div>
  );
};
export default ProjectBrief;
