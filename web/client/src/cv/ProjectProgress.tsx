import React, { useLayoutEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { MessageSquareQuote, X } from 'lucide-react';
import type { SnapshotProject, SnapshotResponse, SnapshotTopic } from '@shared/api.interface';
import { useIsDesktop } from '@client/src/hooks/use-breakpoint';
import { getDraft, setDraft } from '@client/src/lib/conv-store';
import { TopicBadge } from './RoleAvatar';
import { useTick } from './ui';
import { shortWhen, topicHref } from './lib';
import {
  board, COL_ICON, COL_WORD, cut, depGraph, endedWords, milestoneDays, ownerDecisions, quoteOf, stateWord, topicNow, waitingTopics, withQuote,
  type Board, type Col, type Decision, type DepGraph, type Placed, type WaitTopic,
} from './progressData';
import './progress.css';

/* 专项的「进度」标签（v39，第一期只读；v40 起只在负责人还没写背景和动作时显示，由 ProjectBrief 退回到这里）：顶上等你带，中间 做完 / 正在做 / 将要做 三栏，下面依赖图，右栏近 10 条决定和最近里程碑；
 * 点任一条右侧打开详情，「带着这条和负责人讨论」把引用放进负责人对话的输入框。分栏规则在 progressData.ts。
 * 状态不只靠颜色：每处都带图标和字（琥珀对白底不到 3:1）。 */

/** 一条的颜色类：不做了的灰掉 */
const kOf = (x: Pick<Placed, 'col' | 'why'>): string => (x.why === 'dropped' ? 'k-dropped' : `k-${x.col}`);
const iconOf = (x: Pick<Placed, 'col' | 'why'>): string => (x.why === 'dropped' ? '–' : COL_ICON[x.col]);

/** 标题：第一期没有短标题，一行显示完整的标准，CSS 省略号截断，悬停看全文（按标点截会截成“wangyu/main”这种） */
const Title: React.FC<{ x: Placed }> = ({ x }) => <span className="pg-t" title={x.item.criterion}>{x.item.criterion}</span>;

/** 一个条目的小块：图标、编号、标准开头；点了打开它的详情 */
const Chip: React.FC<{ x: Placed | undefined; id: string; pick: (id: string) => void; prefix?: string }> = ({ x, id, pick, prefix }) => (
  <button type="button" className={`pg-chip ${x ? kOf(x) : 'k-next'}`} title={x ? `${id} ${x.item.criterion} · ${stateWord(x)}` : id} onClick={(e) => { e.stopPropagation(); pick(id); }}>
    <b aria-hidden="true">{x ? iconOf(x) : '○'}</b>{prefix}{id}
    {x ? <span className="pg-ct">{x.item.criterion}</span> : null}
  </button>
);

const Head: React.FC<{ col: Col; n: number; hint: string }> = ({ col, n, hint }) => (
  <h3 className="pg-h">
    <i className={`pg-dot k-${col}`} aria-hidden="true" />{COL_WORD[col]} <em>{n}</em><span className="pg-hint">{hint}</span>
  </h3>
);

/** 顶上一行：多少条目标、按栏的分段条（每段之间留缝，带图标和数字），检查表最后一次改动 */
const SumLine: React.FC<{ b: Board; now: number }> = ({ b, now }) => {
  const order: Col[] = ['done', 'doing', 'next', 'owner'];
  return (
    <div className="pg-sum">
      <b>{b.placed.length} 条目标</b>
      <div className="pg-bar" role="img" aria-label={order.map((c: Col) => `${COL_WORD[c]} ${b.counts[c]}`).join('，')}>
        {order.map((c: Col) => (b.counts[c] ? <i key={c} className={`k-${c}`} style={{ flex: b.counts[c] }} title={`${COL_WORD[c]} ${b.counts[c]}`} /> : null))}
      </div>
      {order.map((c: Col) => (
        <span key={c} className={`pg-lg k-${c}`}>
          <b aria-hidden="true">{COL_ICON[c]}</b> {COL_WORD[c]} <em>{b.counts[c]}</em>
        </span>
      ))}
      {b.changedAt ? <span className="pg-fresh">检查表 {shortWhen(b.changedAt, now)} 改过</span> : null}
    </div>
  );
};

/** 等你带：缺口里说要主人的条目（按缺口推断）、本专项等你的话题；右边是做完了、缺口还没清的尾巴 */
const OwnerBand: React.FC<{ b: Board; waits: WaitTopic[]; pick: (id: string) => void }> = ({ b, waits, pick }) => {
  const n: number = b.owner.length + waits.length;
  return (
    <section className={`pg-band${n ? '' : ' calm'}`} aria-label="等你">
      <div className="pg-bh"><i className="pg-dot k-owner" aria-hidden="true" />等你 <em>{n}</em></div>
      <div className="pg-ocs">
        {b.owner.map((x: Placed) => (
          <button key={x.item.id} type="button" className="pg-oc" onClick={() => pick(x.item.id)}>
            <span className="pg-oi" aria-hidden="true">!</span>
            <span className="pg-ob">
              <span className="pg-ot"><b>{x.item.id}</b><Title x={x} />{x.topic ? <TopicBadge number={x.topic.number} /> : null}</span>
              <span className="pg-od" title={x.item.gap}>要你做：{x.item.gap}</span>
              <span className="pg-ou">按缺口推断</span>
            </span>
            <span className="pg-go">讨论 ›</span>
          </button>
        ))}
        {waits.map((w: WaitTopic) => (
          <Link key={w.topic.key} to={topicHref(w.topic)} className="pg-oc pg-ot-topic">
            <span className="pg-oi" aria-hidden="true">?</span>
            <span className="pg-ob">
              <span className="pg-ot">{w.topic.kind === 'lead' ? <b>负责人</b> : <TopicBadge number={w.topic.number} />}<span className="pg-t">{w.topic.kind === 'lead' ? '' : w.topic.title}</span></span>
              <span className="pg-od">{w.questions ? `有 ${w.questions} 道题等你` : '在等你'}</span>
            </span>
            <span className="pg-go">去看 ›</span>
          </Link>
        ))}
        {!n ? <span className="pg-muted">没有卡在你手上的</span> : null}
      </div>
      {b.tails.length ? (
        <div className="pg-tails">
          <div className="pg-tlh">做完了、缺口还没清的尾巴</div>
          {b.tails.map((x: Placed) => (
            <button key={x.item.id} type="button" className="pg-tl" title={x.item.gap} onClick={() => pick(x.item.id)}>
              <b>{x.item.id}</b>{x.item.gap}
            </button>
          ))}
        </div>
      ) : null}
    </section>
  );
};

const DoneCol: React.FC<{ b: Board; pick: (id: string) => void; now: number }> = ({ b, pick, now }) => (
  <section className="pg-col">
    <Head col="done" n={b.counts.done} hint="→ 是它解锁的 · 时间是条目最后改动" />
    <div className="pg-cb">
      {b.done.map((x: Placed) => (
        <button key={x.item.id} type="button" className={`pg-dr${x.why === 'dropped' ? ' gone' : ''}`} onClick={() => pick(x.item.id)}>
          <span className={`pg-ic ${kOf(x)}`} aria-label={stateWord(x)}>{iconOf(x)}</span>
          <b className="pg-id">{x.item.id}</b>
          <Title x={x} />
          {x.tail ? <span className="pg-tail" title={x.item.gap}>尾巴</span> : null}
          {x.unlocks.map((u: string) => <span key={u} className={`pg-ul ${b.byId.get(u) ? kOf(b.byId.get(u) as Placed) : ''}`}>→ {u}</span>)}
          {x.topic ? <TopicBadge number={x.topic.number} /> : null}
          <span className="pg-tm">{shortWhen(x.item.at, now)}</span>
        </button>
      ))}
      {!b.done.length ? <p className="pg-muted">还没有满足的条目</p> : null}
    </div>
  </section>
);

/** 交付话题此刻：在跑的写那一步和第几步；已结束的标待负责人核对 */
const TopicLine: React.FC<{ x: Placed }> = ({ x }) => {
  if (x.why === 'lost') return <div className="pg-cm"><span className="pg-ended short">交付话题不在网页上 · 待负责人核对</span></div>;
  const t: SnapshotTopic | undefined = x.topic;
  const now = topicNow(t);
  if (!t) return <div className="pg-cm"><span className="t3">还没派话题</span></div>;
  return (
    <>
      <div className="pg-cm">
        {now.live ? <span className="pg-live"><i />{now.word}</span> : <span className="pg-ended short">{endedWords(t)}</span>}
        <Link to={topicHref(t)} onClick={(e) => e.stopPropagation()}><TopicBadge number={t.number} /></Link>
        {now.live && now.phase ? <span className="pg-ph" title={now.phase}>{now.phase}</span> : null}
      </div>
      {now.live && now.total ? (
        <div className="pg-steps">
          <div className="pg-sb"><i style={{ width: `${Math.round((100 * now.done) / now.total)}%` }} /></div>
          <span>{now.done}/{now.total} 步</span>
        </div>
      ) : null}
    </>
  );
};

const DoingCol: React.FC<{ b: Board; pick: (id: string) => void }> = ({ b, pick }) => (
  <section className="pg-col">
    <Head col="doing" n={b.counts.doing} hint="交付话题此刻在哪一步" />
    <div className="pg-cb">
      {b.doing.map((x: Placed) => (
        <div key={x.item.id} role="button" tabIndex={0} className="pg-card" onClick={() => pick(x.item.id)} onKeyDown={(e) => { if (e.key === 'Enter') pick(x.item.id); }}>
          <div className="pg-ch"><span className={`pg-ic ${kOf(x)}`} aria-label="在做">▶</span><b className="pg-id">{x.item.id}</b><Title x={x} /></div>
          <TopicLine x={x} />
          {x.item.needs.length ? <div className="pg-kv"><span>依赖</span>{x.item.needs.map((n: string) => <Chip key={n} id={n} x={b.byId.get(n)} pick={pick} />)}</div> : null}
          {x.unlocks.length ? <div className="pg-kv"><span>完成后解锁</span>{x.unlocks.map((u: string) => <Chip key={u} id={u} x={b.byId.get(u)} pick={pick} />)}</div> : null}
          {x.item.gap ? <div className="pg-nx" title={x.item.gap}>缺口：{x.item.gap}</div> : null}
        </div>
      ))}
      {!b.doing.length ? <p className="pg-muted">没有在做的条目</p> : null}
    </div>
  </section>
);

const NextCol: React.FC<{ b: Board; pick: (id: string) => void }> = ({ b, pick }) => {
  const ready: Placed[] = b.next.filter((x: Placed) => x.why === 'ready');
  return (
    <section className="pg-col">
      <Head col="next" n={b.counts.next} hint="被卡的写在等谁" />
      <div className="pg-cb">
        {b.next.map((x: Placed) => (
          <div key={x.item.id} role="button" tabIndex={0} className="pg-card" onClick={() => pick(x.item.id)} onKeyDown={(e) => { if (e.key === 'Enter') pick(x.item.id); }}>
            <div className="pg-ch"><span className={`pg-ic ${kOf(x)}`} aria-label={stateWord(x)}>○</span><b className="pg-id">{x.item.id}</b><Title x={x} /></div>
            {x.why === 'needs' ? (
              <div className="pg-kv"><span>在等</span>{x.waiting.map((n: string) => <Chip key={n} id={n} x={b.byId.get(n)} pick={pick} />)}</div>
            ) : x.why === 'blocked' ? (
              <div className="pg-nx" title={x.item.gap}>卡住：{x.item.gap || '负责人标了卡住'}</div>
            ) : (
              <div className="pg-kv"><span>可开始</span>依赖都满足了</div>
            )}
            <div className="pg-cm">{x.topic ? <TopicBadge number={x.topic.number} /> : <span className="t3">{x.item.topic ? '交付话题不在网页上' : '还没派话题'}</span>}</div>
          </div>
        ))}
        {!b.next.length ? <p className="pg-muted">没有排着的条目</p> : null}
        <div className="pg-sub">解锁预告</div>
        {b.previews.length ? (
          b.previews.map((v) => (
            <div key={v.from}>
              <div className="pg-pv"><Chip id={v.from} x={b.byId.get(v.from)} pick={pick} /><span className="pg-pw">做完后：</span></div>
              {v.to.map((u) => (
                <div key={u.id} className="pg-pv pg-pi">
                  <span className="pg-pw">→</span>
                  <Chip id={u.id} x={b.byId.get(u.id)} pick={pick} />
                  <span className="pg-pw">{u.after === 'met' ? '已满足' : u.after === 'ready' ? '可开始' : `还在等 ${u.rest.join('、')}`}</span>
                </div>
              ))}
            </div>
          ))
        ) : (
          <div className="pg-muted">没有</div>
        )}
        <div className="pg-sub">可开始、还没派话题</div>
        <div className="pg-muted">{ready.filter((x: Placed) => !x.item.topic).map((x: Placed) => x.item.id).join('、') || '没有'}</div>
      </div>
    </section>
  );
};

/* ---- 依赖图：只画有依赖的条目，一串一行、从左往右按先后；节点按状态上色，同时带图标和字。
 * 节点宽跟着可用宽度走（NW_MIN 到 NW_MAX），放不下时横向滚动 ---- */
const NW_MIN = 112;
const NW_MAX = 220;
const NH = 28;
const XG = 28;
const YG = 10;
const PAD = 6;
/** 按宽度截（中文算 2、其余算 1）：SVG 的字没有 CSS 省略号；全文在 title 里 */
function fit(s: string, units: number): string {
  let used = 0;
  let out = '';
  for (const ch of Array.from(s)) {
    used += (ch.codePointAt(0) ?? 0) > 0xff ? 2 : 1;
    if (used > units) return `${out}…`;
    out += ch;
  }
  return out;
}

const DepMap: React.FC<{ b: Board; g: DepGraph; pick: (id: string) => void }> = ({ b, g, pick }) => {
  const wrap = useRef<HTMLDivElement>(null);
  const [room, setRoom] = useState<number>(0);
  useLayoutEffect(() => {
    const el = wrap.current;
    if (!el) return undefined;
    const on = (): void => setRoom(el.clientWidth);
    on();
    const ro = new ResizeObserver(on);
    ro.observe(el);
    return () => ro.disconnect();
  }, [g.nodes.length]);
  if (!g.nodes.length) {
    return (
      <section className="pg-dep">
        <h3 className="pg-h">依赖：做完的解锁了什么</h3>
        <p className="pg-muted">条目之间没有写依赖</p>
      </section>
    );
  }
  const NW: number = Math.max(NW_MIN, Math.min(NW_MAX, Math.floor(((room || NW_MAX * g.cols) - PAD * 2 - (g.cols - 1) * XG) / g.cols)));
  // 一行放得下几个字宽（中文算 2）：去掉图标、编号和边距，每单位约 6.3px
  const units: number = Math.max(8, Math.floor((NW - 46) / 6.3));
  const pos = new Map<string, { x: number; y: number }>(g.nodes.map((n) => [n.id, { x: PAD + n.x * (NW + XG), y: PAD + n.y * (NH + YG) }]));
  const w: number = PAD * 2 + g.cols * (NW + XG) - XG;
  const h: number = PAD * 2 + g.rows * (NH + YG) - YG;
  return (
    <section className="pg-dep">
      <h3 className="pg-h">
        依赖：做完的解锁了什么
        <span className="pg-hint">只画有依赖的 {g.nodes.length} 条{g.lone ? `，另 ${g.lone} 条互不依赖` : ''} · 蓝色连线 = 前置已满足、后面的还没满足</span>
      </h3>
      <div className="pg-depw" ref={wrap}>
        {/* 全局 svg 规则把图标定成 16px、描边：这里写死尺寸 */}
        <svg width={w} height={h} style={{ width: w, height: h }} viewBox={`0 0 ${w} ${h}`} role="img" aria-label="条目依赖图">
          <defs>
            <marker id="pg-ar" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto">
              <path d="M0,0 L8,4 L0,8 z" className="pg-arh" />
            </marker>
          </defs>
          {g.edges.map((e) => {
            const a = pos.get(e.from);
            const z = pos.get(e.to);
            if (!a || !z) return null;
            const y1: number = a.y + NH / 2;
            const y2: number = z.y + NH / 2;
            return <path key={`${e.from}>${e.to}`} className={`pg-edge${e.live ? ' hot' : ''}`} d={`M${a.x + NW},${y1} C${a.x + NW + 24},${y1} ${z.x - 24},${y2} ${z.x - 2},${y2}`} markerEnd="url(#pg-ar)" />;
          })}
          {g.nodes.map((n) => {
            const x: Placed | undefined = b.byId.get(n.id);
            const p = pos.get(n.id) as { x: number; y: number };
            if (!x) return null;
            return (
              <g
                key={n.id}
                className={`pg-node ${kOf(x)}`}
                transform={`translate(${p.x},${p.y})`}
                role="button"
                tabIndex={0}
                onClick={() => pick(n.id)}
                onKeyDown={(e) => { if (e.key === 'Enter') pick(n.id); }}
              >
                <title>{`${n.id} ${x.item.criterion} · ${stateWord(x)}`}</title>
                <rect width={NW} height={NH} rx={6} />
                <text x={9} y={18}>
                  <tspan className="pg-ni">{iconOf(x)}</tspan> <tspan className="pg-nid">{n.id}</tspan> {fit(x.item.criterion, units)}
                </text>
              </g>
            );
          })}
        </svg>
      </div>
    </section>
  );
};

/** 右栏：主人答过的近 10 条决定（专项记忆），最近里程碑按天归组 */
const Rail: React.FC<{ p: SnapshotProject; decisions: Decision[]; now: number }> = ({ p, decisions, now }) => {
  const days = milestoneDays(p.milestones);
  return (
    <aside className="pg-rail">
      <section>
        <h3 className="pg-h">近 10 条决定<span className="pg-hint">主人答过的，自动记</span></h3>
        {decisions.length ? (
          decisions.map((d: Decision) => (
            <div key={d.id || d.text} className="pg-dc" title={d.text}>
              <span className="pg-tm">{shortWhen(d.at, now)}</span>
              {d.number ? <TopicBadge number={d.number} /> : null}
              <span className="pg-dq">{d.question}</span>
              {d.answer ? <span className="pg-da">→ {d.answer}</span> : null}
            </div>
          ))
        ) : (
          <p className="pg-muted">还没有主人答过的决定</p>
        )}
      </section>
      <section>
        <h3 className="pg-h">最近里程碑<span className="pg-hint">负责人记的，按天</span></h3>
        {days.length ? (
          days.map((g) => (
            <div key={g.day} className="pg-day">
              <div className="pg-dd">{g.day}</div>
              {g.rows.map((r) => (
                <div key={r.id || r.text} className="pg-ms" title={r.text}>
                  <span className="pg-tm">{shortWhen(r.at, now).split(' ').pop()}</span>
                  {r.kind === 'finish' ? <span className="pg-fin">收尾</span> : null}
                  <span className="pg-mt">{r.text}</span>
                </div>
              ))}
            </div>
          ))
        ) : (
          <p className="pg-muted">还没有里程碑</p>
        )}
      </section>
    </aside>
  );
};

const Row: React.FC<{ k: string; children: React.ReactNode }> = ({ k, children }) => (
  <>
    <div className="pg-dl">{k}</div>
    <div className="pg-dv">{children}</div>
  </>
);

/** 详情抽屉：标准、交付话题此刻、依赖和解锁、证据、缺口、相关决定；「带着这条和负责人讨论」 */
const ItemDrawer: React.FC<{
  x: Placed;
  b: Board;
  decisions: Decision[];
  lead: SnapshotTopic | undefined;
  now: number;
  pick: (id: string) => void;
  onClose: () => void;
  onDiscuss: (x: Placed) => void;
}> = ({ x, b, decisions, lead, now, pick, onClose, onDiscuss }) => {
  const t: SnapshotTopic | undefined = x.topic;
  const tn = topicNow(t);
  const related: Decision[] = x.item.topic ? decisions.filter((d: Decision) => d.topicKey === x.item.topic).slice(0, 3) : [];
  return (
    <div className="drawer pg-drw" role="dialog" aria-label={`${x.item.id} 详情`}>
      <div className="dh">
        <div className="pg-dh">
          <span className={`pg-ic ${kOf(x)}`} aria-hidden="true">{iconOf(x)}</span>
          <b>{x.item.id}</b>
          <span className={`pg-st ${kOf(x)}`}>{stateWord(x)}</span>
          <a role="button" aria-label="关闭" onClick={onClose} className="pg-x"><X /></a>
        </div>
        <div className="pg-dsub">检查表 {shortWhen(x.item.at, now) || '—'} 改过（条目最后改动，不是完成时间）</div>
      </div>
      <div className="pg-dbody">
        <Row k="完成标准">{x.item.criterion}</Row>
        <Row k="交付话题">
          {t ? (
            <>
              <Link to={topicHref(t)}><TopicBadge number={t.number} /> {t.title}</Link>
              <div className="t3">
                {x.why === 'ended' && x.col === 'doing' ? endedWords(t) : `${tn.word}${tn.live && tn.phase ? ` · ${tn.phase}` : ''}${tn.live && tn.total ? ` · ${tn.done}/${tn.total} 步` : ''}`}
              </div>
            </>
          ) : x.item.topic ? '交付话题不在网页上' : '还没指定话题'}
        </Row>
        {x.item.needs.length ? <Row k="依赖">{x.item.needs.map((n: string) => <Chip key={n} id={n} x={b.byId.get(n)} pick={pick} />)}</Row> : null}
        {x.unlocks.length ? <Row k="完成后解锁">{x.unlocks.map((u: string) => <Chip key={u} id={u} x={b.byId.get(u)} pick={pick} />)}</Row> : null}
        {x.item.evidence ? <Row k="证据">{x.item.evidence}</Row> : null}
        {x.item.gap ? <Row k={x.col === 'owner' ? '缺口（按缺口推断：下一步在你手上）' : x.tail ? '缺口（尾巴）' : '缺口'}>{x.item.gap}</Row> : null}
        {related.length ? (
          <Row k="相关决定">
            {related.map((d: Decision) => <div key={d.id || d.text}>{shortWhen(d.at, now)} {d.question}{d.answer ? ` → ${d.answer}` : ''}</div>)}
          </Row>
        ) : null}
        <button type="button" className="btn pri pg-say" disabled={!lead} onClick={() => onDiscuss(x)}>
          <MessageSquareQuote /> 带着这条和负责人讨论
        </button>
        <p className="t3 pg-sayn">
          {lead ? `把“${cut(quoteOf(x), 30)}”放进负责人对话的输入框（原来的草稿接在后面），发出去和在「对话」里说一样` : '这个专项还没有负责人对话'}
        </p>
      </div>
    </div>
  );
};

const ProjectProgress: React.FC<{ p: SnapshotProject; snap: SnapshotResponse; lead: SnapshotTopic | undefined; base: string; hint?: string }> = ({ p, snap, lead, base, hint }) => {
  const desktop: boolean = useIsDesktop();
  const nav = useNavigate();
  const now: number = useTick(30000);
  const [params, setParams] = useSearchParams();
  const sel: string | null = params.get('sel');
  const topics = useMemo(() => new Map<string, SnapshotTopic>(snap.topics.map((t: SnapshotTopic) => [t.key, t])), [snap.topics]);
  const b: Board = useMemo(() => board(p.checklist, topics), [p.checklist, topics]);
  const g: DepGraph = useMemo(() => depGraph(p.checklist), [p.checklist]);
  const waits: WaitTopic[] = useMemo(() => waitingTopics(snap, p), [snap, p]);
  const all: Decision[] = useMemo(() => ownerDecisions(p.memory, snap.topics, 50), [p.memory, snap.topics]);
  const pick = (id: string): void => setParams(sel === id ? {} : { sel: id }, { replace: true });
  const discuss = (x: Placed): void => {
    if (!lead) return;
    setDraft(lead.key, withQuote(quoteOf(x), getDraft(lead.key)));
    nav(base);
  };
  const cur: Placed | undefined = sel ? b.byId.get(sel) : undefined;
  const rail = <Rail p={p} decisions={all.slice(0, 10)} now={now} />;
  if (!b.placed.length) {
    return (
      <div className={`pg${desktop ? '' : ' m'}`}>
        {hint ? <div className="pg-hintbar" role="note">{hint}</div> : null}
        <div className="pg-main">
          <div className="pg-empty">
            <b>这个专项还没有目标检查表</b>
            <p className="t3">负责人写下“做到哪些才算完”以后，这里按做完、正在做、将要做分栏显示；Covey 版本还没推检查表时也是这一句。</p>
          </div>
          {rail}
        </div>
      </div>
    );
  }
  return (
    <div className="pg-wrap">
      <div className={`pg${desktop ? '' : ' m'}`}>
        {hint ? <div className="pg-hintbar" role="note">{hint}</div> : null}
        <SumLine b={b} now={now} />
        <OwnerBand b={b} waits={waits} pick={pick} />
        <div className="pg-main">
          <div className="pg-left">
            <div className="pg-cols">
              <DoneCol b={b} pick={pick} now={now} />
              <DoingCol b={b} pick={pick} />
              <NextCol b={b} pick={pick} />
            </div>
            <DepMap b={b} g={g} pick={pick} />
          </div>
          {rail}
        </div>
      </div>
      {cur ? <ItemDrawer key={cur.item.id} x={cur} b={b} decisions={all} lead={lead} now={now} pick={pick} onClose={() => setParams({}, { replace: true })} onDiscuss={discuss} /> : null}
    </div>
  );
};
export default ProjectProgress;
