import React, { useLayoutEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { Maximize2, Minus, Plus, X } from 'lucide-react';
import type { SnapshotProject, SnapshotTopic, StepView, TurnView } from '@shared/api.interface';
import { useIsDesktop } from '@client/src/hooks/use-breakpoint';
import { useTurns } from '@client/src/hooks/use-workbench';
import { oneLineText } from '@client/src/lib/workbench-format';
import type { ProjectMetrics } from './projectData';
import { Avatar, Hx, Pill, useTick } from './ui';
import { engineText, fmtDur, fmtShort, fmtTok, harnessName, hhmm, isRunning, legacyCls, toneOf, toneWord, type ToneKey } from './lib';
import { listTone } from './topicText';
import { denseFor, fitLayout, groupOf, layout, roundedPath, type Dense, type GEdge, type GFrame, type GLabel, type GNode, type GraphLayout, type GroupKey, type LTopic } from './graphLayout';

/** 每组的颜色和组名 */
const GROUP_TONE: Record<GroupKey, ToneKey> = { waiting: 'waiting', stopped: 'stopped', running: 'running', result: 'result', queued: 'queued', done: 'done' };
function groupName(g: GroupKey, list: SnapshotTopic[]): string {
  if (g === 'queued') {
    const tones = new Set(list.map((t: SnapshotTopic) => toneOf(t)));
    return tones.size > 1 ? '排队、空闲' : tones.has('idle') ? '空闲' : '排队';
  }
  return { waiting: '等你', stopped: '停住了', running: '在做', result: '有结果', done: '做完' }[g];
}

/** 组内从小到大：等你等得久的在前，在做开始早的在前，其余新的在前 */
function sortKey(t: SnapshotTopic, g: GroupKey): number {
  if (g === 'waiting') return t.updated_at;
  if (g === 'running') return t.running?.started_at ?? t.updated_at;
  return -t.updated_at;
}

/** 卡上的第二行：在做的写此刻那一步，其余写话题要点的目标（不用 latest：它会带出模型中途的英文） */
function cardLine(t: SnapshotTopic): string {
  // running 只在真的在做时才读：推送里排队、空闲的话题也可能带着上一轮留下的 running
  if (t.running && isRunning(t)) return t.running.plan_doing || t.running.step_label || '在做';
  const g: string = t.gist?.goal || t.gist?.essence || t.progress?.phase || '';
  if (g) return oneLineText(g, 40);
  // 只有没在跑的话题才用最新一轮的开头：在跑那一轮的正文是模型中途的话
  return t.latest_role !== 'owner' && t.latest_status !== 'running' ? oneLineText(t.latest, 40) : '';
}

/** 负责人自己这一轮的状态 */
function leadState(lead: SnapshotTopic | undefined): { tone: ToneKey; word: string } {
  if (!lead) return { tone: 'idle', word: '还没有负责人' };
  if (isRunning(lead)) return { tone: 'running', word: '在派活' };
  if (toneOf(lead) === 'waiting') return { tone: 'waiting', word: '在等你' };
  return { tone: 'idle', word: '空闲' };
}

const cvar = (k: ToneKey): string => `var(--st-${k})`;

const Drawer: React.FC<{ t: SnapshotTopic; m: ProjectMetrics; onClose: () => void }> = ({ t, m, onClose }) => {
  const nav = useNavigate();
  const { data } = useTurns(t.key);
  const now: number = useTick(1000);
  const agent: TurnView[] = (data?.turns ?? []).filter((x: TurnView) => x.role !== 'owner' && x.role !== 'event');
  const last: TurnView | undefined = agent.find((x: TurnView) => x.status === 'running') ?? agent[agent.length - 1];
  const steps: StepView[] = [...(last?.steps ?? [])].reverse().slice(0, 7);
  const per = m.per.get(t.key);
  const ctx = last?.context ?? t.context;
  return (
    <div className="drawer">
      <div className="dh">
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <Hx harness={t.harness} />
          <b style={{ fontSize: 14, flex: 1, minWidth: 0 }}>T{t.number} {t.title}</b>
          <a role="button" aria-label="关闭" onClick={onClose} style={{ color: 'var(--t3)' }}><X /></a>
        </div>
        <div style={{ display: 'flex', gap: 6, marginTop: 8 }}>
          <Pill tone={toneOf(t)} />
          {t.round ? <span className="tag">第 {t.round} 轮</span> : null}
        </div>
      </div>
      <div className="kv">
        <span>Harness</span><b>{engineText(t) || '—'}</b>
        <span>用时</span><b>{per?.seconds ? fmtDur(per.seconds, false) : '—'}</b>
        <span>token</span><b>{per?.tokens ? fmtTok(per.tokens) : '—'}</b>
        <span>上下文</span><b>{ctx ? (ctx.limit > 0 ? `${fmtTok(ctx.used)} / ${fmtTok(ctx.limit)}` : fmtTok(ctx.used)) : '—'}</b>
        <span>此刻</span><b style={{ color: 'var(--run)' }}>{t.running && isRunning(t) ? `${t.running.step_label || '在做'}${t.running.started_at ? ` · ${fmtDur(now - t.running.started_at)}` : ''}` : '—'}</b>
      </div>
      <div className="sh" style={{ padding: '4px 16px 0' }}><b>最近的调用</b></div>
      <div className="calls" style={{ overflowY: 'auto', flex: 1 }}>
        {steps.length ? (
          steps.map((s: StepView, i: number) => (
            <div key={s.id ?? i} className={`call${s.status === 'running' ? ' live' : ''}`}>
              <span className="ic">›</span>
              <span className="nm">{s.label}</span>
              <span className="ms">{s.status === 'running' ? '在跑' : s.started_at && s.ended_at ? fmtShort(s.ended_at - s.started_at) : ''}</span>
            </div>
          ))
        ) : (
          <p className="t3" style={{ fontSize: 12 }}>还没有调用记录。</p>
        )}
      </div>
      <div style={{ display: 'flex', gap: 8, padding: 14 }}>
        <button type="button" className="btn pri" style={{ flex: 1, justifyContent: 'center' }} onClick={() => nav(`/topics/${encodeURIComponent(t.key)}`)}>打开话题 →</button>
        <button type="button" className="btn" onClick={() => nav(`/topics/${encodeURIComponent(t.key)}`)}>补充</button>
      </div>
    </div>
  );
};

const ProjectGraph: React.FC<{ p: SnapshotProject; topics: SnapshotTopic[]; lead: SnapshotTopic | undefined; m: ProjectMetrics }> = ({ p, topics, lead, m }) => {
  const desktop: boolean = useIsDesktop();
  const [params, setParams] = useSearchParams();
  const sel: string | null = params.get('sel');
  /** null＝适应（打开时默认）；点了 + −、展开或收起一组就是手动的倍数和档位，保持到再点“适应” */
  const [manual, setManual] = useState<{ z: number; d: Dense } | null>(null);
  const [toggled, setToggled] = useState<ReadonlySet<GroupKey>>(new Set<GroupKey>());
  const [box, setBox] = useState<{ w: number; h: number }>({ w: 0, h: 0 });
  const wrap = useRef<HTMLDivElement>(null);
  const now: number = useTick(30000);
  useLayoutEffect(() => {
    const el = wrap.current;
    if (!el) return undefined;
    const on = (): void => setBox((b) => (b.w === el.clientWidth && b.h === el.clientHeight ? b : { w: el.clientWidth, h: el.clientHeight }));
    on();
    const ro = new ResizeObserver(on);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const byKey = useMemo(() => new Map(topics.map((t: SnapshotTopic) => [t.key, t])), [topics]);
  const lt: LTopic[] = useMemo(
    () =>
      topics.map((t: SnapshotTopic) => {
        const g: GroupKey = groupOf(toneOf(t), t.board);
        return { key: t.key, number: t.number ?? 0, group: g, sort: sortKey(t, g) };
      }),
    [topics],
  );
  const { L, z } = useMemo((): { L: GraphLayout; z: number } => {
    const build = (d: Dense): GraphLayout => layout(lt, { compact: !desktop, dense: d, toggled });
    if (manual !== null) return { L: build(manual.d), z: manual.z };
    if (!box.w) return { L: build(0), z: 1 };
    return fitLayout(build, box.w, box.h);
  }, [lt, desktop, toggled, manual, box]);
  const toggle = (g: GroupKey): void => {
    // 展开一组不重新适应（不然整张图一下子缩小）：停在现在的倍数，多出来的往下滚
    if (manual === null) setManual({ z, d: L.dense });
    setToggled((s) => {
      const n = new Set(s);
      if (n.has(g)) n.delete(g);
      else n.add(g);
      return n;
    });
  };
  /** 放大往细里换档（紧凑行换回完整卡），缩小往粗里换档；倍数下限 0.5 */
  const zoomTo = (next: number): void => {
    const d: Dense = !desktop ? 1 : next > z ? (Math.min(L.dense, denseFor(next)) as Dense) : (Math.max(L.dense, denseFor(next)) as Dense);
    setManual({ z: next, d });
  };
  const pick = (key: string): void => setParams(sel === key ? {} : { sel: key }, { replace: true });
  const members = (g: GroupKey): SnapshotTopic[] => lt.filter((x: LTopic) => x.group === g).map((x: LTopic) => byKey.get(x.key) as SnapshotTopic);
  const waiting: SnapshotTopic[] = members('waiting');
  const doneN: number = lt.filter((x: LTopic) => x.group === 'done').length;
  const selTopic: SnapshotTopic | undefined = topics.find((t: SnapshotTopic) => t.key === sel);
  const ls = leadState(lead);

  const edgeEl = (e: GEdge): React.ReactNode => {
    const d: string = roundedPath(e.pts);
    if (e.kind === 'flow') return <path key={e.key} className="comet" pathLength={200} d={d} style={{ ['--c' as string]: cvar('running') }} />;
    if (e.kind === 'wait')
      return (
        <g key={e.key} style={{ ['--c' as string]: 'var(--wait)' }}>
          <path className="edge dash" d={d} style={{ strokeOpacity: 0.75 }} />
          <path className="comet" pathLength={200} d={d} />
        </g>
      );
    if (e.kind === 'delegate') return <path key={e.key} className="edge dash" d={d} style={{ ['--c' as string]: 'var(--a1)', strokeOpacity: 0.6 }} />;
    if (e.kind === 'branch') return <path key={e.key} className="edge" d={d} style={{ ['--c' as string]: e.group ? cvar(GROUP_TONE[e.group]) : 'var(--t3)', strokeOpacity: 0.6 }} />;
    return <path key={e.key} className="edge" d={d} style={{ ['--c' as string]: 'var(--a1)', strokeOpacity: 0.45 }} />;
  };

  const frameEl = (f: GFrame): React.ReactNode => {
    const list: SnapshotTopic[] = members(f.group);
    const foldable: boolean = f.group !== 'waiting' || L.dense === 2;
    return (
      <div key={`f${f.group}`} className="gframe" style={{ left: f.x, top: f.y, width: f.w, height: f.h, ['--c' as string]: cvar(GROUP_TONE[f.group]) }}>
        <div className={`gfh${foldable ? ' tap' : ''}`} onClick={foldable ? () => toggle(f.group) : undefined}>
          <i className="gdot" />
          <b>{groupName(f.group, list)}</b>
          <span className="n">{f.n}</span>
          {foldable ? <span className="tg">收起 ‹</span> : null}
        </div>
      </div>
    );
  };

  const nodeEl = (n: GNode): React.ReactNode => {
    if (n.kind === 'you')
      return (
        <div key="you" className="gn you single" style={{ left: n.x, top: n.y, width: n.w, height: n.h }}>
          <Avatar size={24} />
          <b>你</b>
          {waiting.length ? <span className="pill tone-waiting" style={{ marginLeft: 'auto' }}><i className="dot tone-waiting" />等你 {waiting.length}</span> : null}
        </div>
      );
    if (n.kind === 'lead') {
      const line: string = !lead ? '' : lead.running && ls.tone === 'running' ? lead.running.plan_doing || lead.running.step_label || '在派活' : ls.tone === 'waiting' ? '等你回答' : oneLineText(lead.gist?.goal || p.goal || '', 40);
      const tok: number | undefined = lead ? m.per.get(lead.key)?.tokens : undefined;
      return (
        <div
          key="lead"
          className={`gn single lead ${lead ? (isRunning(lead) ? 'run' : '') : 'stop'} ${lead && sel === lead.key ? 'sel' : ''}`}
          style={{ left: n.x, top: n.y, width: n.w, height: n.h, ['--c' as string]: 'var(--a1)', borderColor: 'color-mix(in srgb,var(--a1) 55%,transparent)' }}
        >
          <div className="h"><Hx harness="" lead /><b>负责人</b><span className="rt" style={{ color: cvar(ls.tone) }}>{ls.word}</span></div>
          <div className="tki" style={{ border: 0, padding: 0, display: 'block', height: 'auto', whiteSpace: 'nowrap', textOverflow: 'ellipsis' }}>{lead ? `${harnessName(lead.harness)}${line ? ` · ${line}` : ''}` : '专项还在建'}</div>
          {lead ? <div className="f"><span>{lead.model_name ?? lead.model}</span><span className="sp" /><span className="mono short">{tok ? fmtTok(tok) : ''}</span></div> : null}
        </div>
      );
    }
    if (n.kind === 'empty')
      return (
        <div key="empty" className="gn ghost gempty" style={{ left: n.x, top: n.y, width: n.w, minHeight: n.h, height: 'auto' }}>
          <b style={{ fontSize: 13 }}>这个专项还没有话题</b>
          <span className="t3" style={{ fontSize: 12, lineHeight: 1.6 }}>
            {lead ? '负责人派出的话题、挂进专项的已有话题会按等你、在做、做完分组画在这里，连到负责人。' : '专项还在建：负责人到位、派出话题以后，这里画出负责人和各话题的关系。'}
          </span>
        </div>
      );
    if (n.kind === 'fold') {
      const g = n.group as GroupKey;
      const list: SnapshotTopic[] = members(g);
      const last: SnapshotTopic | undefined = [...list].sort((a: SnapshotTopic, b: SnapshotTopic) => b.updated_at - a.updated_at)[0];
      const stoppedN: number = g === 'done' ? list.filter((t: SnapshotTopic) => !['done', 'result'].includes(toneOf(t))).length : 0;
      return (
        <div key={n.key} className="gn fold" role="button" style={{ left: n.x, top: n.y, width: n.w, height: n.h, ['--c' as string]: cvar(GROUP_TONE[g]) }} onClick={() => toggle(g)}>
          <i className="gdot" />
          <div style={{ flex: 1, minWidth: 0 }}>
            <b>{groupName(g, list)} {list.length} 个</b>
            {stoppedN ? <span className="t3">（含已停止 {stoppedN}）</span> : null}
            {last ? <div className="sub">最近 T{last.number} {hhmm(last.updated_at)}</div> : null}
          </div>
          <span className="tg">›</span>
        </div>
      );
    }
    const t = byKey.get(n.key) as SnapshotTopic;
    const tone: ToneKey = listTone(t);
    const per = m.per.get(t.key);
    if (n.kind === 'row') {
      const sec: number | null = t.running?.started_at && isRunning(t) ? now - t.running.started_at : null;
      return (
        <div key={n.key} className={`gn gt row ${legacyCls(tone)} ${sel === t.key ? 'sel' : ''}`} style={{ left: n.x, top: n.y, width: n.w, height: n.h, ['--c' as string]: cvar(tone) }} onClick={() => pick(t.key)} title={`T${t.number} ${t.title}`}>
          <i className="gdot" />
          <span className="no">T{t.number}</span>
          <span className="ttl">{t.title}</span>
          <span className="rt">· {sec ? fmtDur(sec, false) : toneWord(tone)}</span>
        </div>
      );
    }
    const line: string = cardLine(t);
    return (
      <div key={n.key} className={`gn gt ${legacyCls(tone)} ${sel === t.key ? 'sel' : ''}`} style={{ left: n.x, top: n.y, width: n.w, height: n.h, cursor: 'pointer' }} onClick={() => pick(t.key)}>
        <div className="h"><Hx harness={t.harness} /><b style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>T{t.number} {t.title}</b><span className="rt">{t.round ? `第 ${t.round} 轮` : ''}</span></div>
        <div className="tki" style={{ border: 0, padding: 0, display: 'block', height: 34, overflow: 'hidden' }}>{harnessName(t.harness)}{line ? ` · ${line}` : ''}</div>
        <div className="f"><Pill tone={tone} /><span className="sp" /><span className="mono short">{per ? `${per.seconds ? fmtDur(per.seconds, false) : ''}${per.tokens ? ` · ${fmtTok(per.tokens)}` : ''}` : ''}</span></div>
      </div>
    );
  };

  const labelEl = (l: GLabel): React.ReactNode => {
    const cls: string = l.anchor === 'left' ? ' left' : '';
    if (l.kind === 'delegate') return <div key="ld" className={`elb${cls}`} style={{ left: l.x, top: l.y }}>交代</div>;
    if (l.kind === 'dispatch') {
      if (!topics.length) return null;
      return <div key="lp" className={`elb run${cls}`} style={{ left: l.x, top: l.y }}>派活 · {topics.length} 个话题{doneN ? ` · ${doneN} 做完` : ''}</div>;
    }
    return <div key="lw" className={`elb wait${cls}`} style={{ left: l.x, top: l.y }}>{waiting.length === 1 ? `T${waiting[0].number} 等你回答` : `${waiting.length} 个等你回答`}</div>;
  };

  return (
    <div className="gwrap">
      <div className="gcanvas-wrap" ref={wrap} style={{ overflow: 'auto', right: desktop && sel ? 316 : 0 }}>
        <div style={{ width: L.W * z, height: L.H * z, position: 'relative', margin: desktop ? 16 : 4 }}>
          <div className={`gcanvas d${L.dense}`} style={{ width: L.W, height: L.H, transform: `scale(${z})`, transition: 'none' }}>
            <svg className="edges" viewBox={`0 0 ${L.W} ${L.H}`} style={{ width: L.W, height: L.H }}>
              {L.edges.map(edgeEl)}
            </svg>
            {L.frames.map(frameEl)}
            {L.nodes.map(nodeEl)}
            {L.labels.map(labelEl)}
          </div>
        </div>
      </div>
      <div className="legend">
        <span><i style={{ ['--c' as string]: 'var(--wait)' }} />等你</span>
        <span><i style={{ ['--c' as string]: 'var(--run)' }} />在做</span>
        <span><i style={{ ['--c' as string]: 'var(--done)' }} />做完</span>
      </div>
      <div className="zc" style={sel && desktop ? { right: 336 } : undefined}>
        <a role="button" aria-label="放大" onClick={() => zoomTo(Math.min(1.6, z + 0.15))}><Plus /></a>
        <a role="button" aria-label="缩小" onClick={() => zoomTo(Math.max(0.5, z - 0.15))}><Minus /></a>
        <a role="button" aria-label="适应" onClick={() => setManual(null)}><Maximize2 /></a>
      </div>
      {selTopic ? <Drawer t={selTopic} m={m} onClose={() => setParams({}, { replace: true })} /> : null}
    </div>
  );
};
export default ProjectGraph;
