import React, { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ChevronDown, ChevronRight, Clock3, Database, Diamond, HelpCircle, Undo2, Zap } from 'lucide-react';
import type { ReportResponse, SnapshotProject, SnapshotTopic } from '@shared/api.interface';
import { useIsDesktop } from '@client/src/hooks/use-breakpoint';
import { DurValue, Tile, useTick } from './ui';
import type { ProjectMetrics } from './projectData';
import { buildReport, ticks, type Lane, type Plan, type ReportModel, type Round } from './reportData';
import { DONE_SHOWN, WAIT_LABEL, groupLanes, lastAt, planSummary, segments, windows, type Overrun, type PlanSummary, type Seg, type Window } from './reportView';
import { fmtDur, fmtTok, hhmm, isWaiting as topicWaits } from './lib';

const GREY = '#6f7a99';
const mins = (sec: number): string => `${Math.max(0, Math.round(sec / 60))} 分`;
/** 短时长：“47分”“4时06分”，放在时间轴右边一列 */
const short = (sec: number): string => {
  const m: number = Math.max(0, Math.round(sec / 60));
  return m < 60 ? `${m}分` : `${Math.floor(m / 60)}时${String(m % 60).padStart(2, '0')}分`;
};
/** 时间轴上的时刻：今天只写钟点，别的日子带日期 */
const when = (v: number, now: number): string => {
  const a = new Date(v * 1000);
  const b = new Date(now * 1000);
  return a.toDateString() === b.toDateString() ? hhmm(v) : `${a.getMonth() + 1}/${a.getDate()} ${hhmm(v)}`;
};

/** 一行：话题名 | 段、等你的细线、做完的勾 | 几轮 · 用时 · 等你 */
const LaneRow: React.FC<{ l: Lane; w: Window; now: number; desktop: boolean; onOpen: (key: string) => void }> = ({ l, w, now, desktop, onOpen }) => {
  const span: number = Math.max(w.w1 - w.w0, 60);
  const pct = (v: number): number => Math.min(100, Math.max(0, ((v - w.w0) / span) * 100));
  const segs: Seg[] = segments(l.rounds).filter((g: Seg) => g.e >= w.w0 && g.s <= w.w1);
  const waits = l.waits.filter((x) => x.e >= w.w0 && x.s <= w.w1);
  const longest = waits.reduce<(typeof waits)[number] | undefined>((a, x) => (!a || x.e - x.s > a.e - a.s ? x : a), undefined);
  const doneAt: number | null = l.state === '做完' && l.rounds.length ? lastAt(l) : null;
  const wait: number = l.waits.reduce((s: number, x) => s + (x.e - x.s), 0);
  const work: number = l.rounds.reduce((s: number, r: Round) => s + r.seconds, 0);
  const name: string = l.title ? `${l.label} ${l.title}` : l.label;
  return (
    <div className="rtl-row">
      <a className="rtl-nm" role="button" title={`${name}（点开话题）`} onClick={() => onOpen(l.key)}>
        <span className="n">{l.label}</span>
        {desktop ? <span>{l.title}</span> : null}
      </a>
      <div className="rtl-tr">
        {segs.map((g: Seg, i: number) => {
          const a: number = pct(g.s);
          const b: number = pct(g.e);
          return (
            <i key={i} className={`rtl-bar${g.live ? ' live' : g.failed ? ' fail' : ''}`} style={{ left: `${a}%`, width: `${Math.max(b - a, 0.5)}%` }} title={`${g.k} 轮 · ${when(g.s, now)}–${g.live ? '现在' : hhmm(g.e)}${g.failed ? ' · 没做成' : ''}`}>
              {desktop && g.k >= 3 && b - a > 2.5 ? <span className="k">{g.k} 轮</span> : null}
            </i>
          );
        })}
        {waits.map((x, i: number) => {
          const a: number = pct(x.s);
          const b: number = pct(x.e);
          if (b - a < 0.3) return null;
          return (
            <React.Fragment key={`w${i}`}>
              <i className="rtl-wait" style={{ left: `${a}%`, width: `${b - a}%` }} title={`${x.open ? '还在等你' : '等过你'} ${fmtDur(x.e - x.s, false)}（${when(x.s, now)} 起）`} />
              {x === longest && x.e - x.s >= WAIT_LABEL ? <span className="rtl-wt" style={{ left: `calc(${a}% + 2px)` }}>等你 {fmtDur(x.e - x.s, false)}{x.open ? '（还在等）' : ''}</span> : null}
            </React.Fragment>
          );
        })}
        {doneAt && doneAt >= w.w0 && doneAt <= w.w1 ? <i className="rtl-ok" style={{ left: `${pct(doneAt)}%` }} title={`${when(doneAt, now)} 做完`}>✓</i> : null}
        {l.due && l.due <= w.w1 + 3600 ? <i className="rtl-due" style={{ left: `${pct(Math.min(l.due, w.w1))}%` }} title={`预计 ${hhmm(l.due)} 做完`} /> : null}
      </div>
      {desktop ? (
        <div className="rtl-sm">
          {l.rounds.length} 轮 · {short(work)}
          {wait >= 1800 ? <span className="w"> · 等你 {short(wait)}</span> : null}
        </div>
      ) : null}
    </div>
  );
};

const Fold: React.FC<{ open: boolean; label: string; names: string; desktop: boolean; onToggle: () => void }> = ({ open, label, names, desktop, onToggle }) => (
  <a className="rtl-fold" role="button" onClick={onToggle}>
    {open ? <ChevronDown /> : <ChevronRight />}
    <span>{label}</span>
    {desktop && !open ? <span className="t3 names">{names}</span> : null}
    <span className="more">{open ? '收起' : '展开'}</span>
  </a>
);

/** 时间轴（方案 A，精简泳道）：默认最近 24 小时；在做的排最上，做完的显示最近 DONE_SHOWN 个，其余、更早做完的、停掉的各折一行；
 * 连着的几轮合成一段，等你画细线，负责人一行只画刻度 */
/** 手机上时间范围的字短一点，五六个选项排得下一行：“最近 24 小时”写“24 小时”，“全部 69 小时”写“全部” */
const shortWindow = (o: Window): string => (o.key === '24h' ? '24 小时' : o.key === 'all' ? '全部' : o.label);

const Timeline: React.FC<{ model: ReportModel; lead: Lane | undefined; now: number; desktop: boolean }> = ({ model, lead, now, desktop }) => {
  const nav = useNavigate();
  const opts: Window[] = useMemo(() => windows(model.t0, now), [model.t0, now]);
  const [key, setKey] = useState<string>('24h');
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const w: Window = opts.find((o: Window) => o.key === key) ?? opts[0];
  const g = groupLanes(model.lanes, w);
  const shownDone: Lane[] = open.done ? g.done : g.done.slice(0, DONE_SHOWN);
  const moreDone: Lane[] = g.done.slice(DONE_SHOWN);
  const span: number = Math.max(w.w1 - w.w0, 60);
  const pct = (v: number): number => Math.min(100, Math.max(0, ((v - w.w0) / span) * 100));
  const leadRounds: Round[] = lead ? lead.rounds.filter((r: Round) => r.e >= w.w0 && r.s <= w.w1) : [];
  const onOpen = (k: string): void => {
    void nav(`/topics/${encodeURIComponent(k)}`);
  };
  const toggle = (k: string): void => setOpen((o) => ({ ...o, [k]: !o[k] }));
  const nowIn: boolean = now >= w.w0 && now <= w.w1 + 60;
  const row = (l: Lane) => <LaneRow key={l.key} l={l} w={w} now={now} desktop={desktop} onOpen={onOpen} />;
  const tn = (ls: Lane[]): string => ls.map((l: Lane) => l.label).join('、');
  return (
    <div className="rtl">
      <div className="rtl-head">
        <span className="rlg">
          <span><i className="sw" style={{ background: 'var(--run)' }} />在做</span>
          <span><i className="sw" style={{ background: GREY }} />做完的轮次</span>
          <span><i className="sw" style={{ background: 'var(--fail)' }} />没做成</span>
          <span><i className="sw" style={{ background: 'var(--wait)', height: 2 }} />等你</span>
          <span><span style={{ color: 'var(--done)' }}>●</span>&nbsp;话题做完</span>
        </span>
        <span className="rtl-seg">
          {opts.map((o: Window) => (
            <a key={o.key} role="button" className={o.key === w.key ? 'on' : ''} onClick={() => setKey(o.key)}>{desktop ? o.label : shortWindow(o)}</a>
          ))}
        </span>
      </div>
      <div className="rtl-body">
        <div className="rtl-ax">
          {ticks(w.w0, w.w1).map((v: number) => (
            <span key={v} style={{ left: `${pct(v)}%` }}>{hhmm(v)}</span>
          ))}
          {nowIn ? <span className="nowt" style={{ left: `${pct(now)}%`, transform: pct(now) > 85 ? 'translateX(-100%)' : undefined }}>现在 {hhmm(now)}</span> : null}
        </div>
        {lead ? (
          <div className="rtl-row lead">
            <span className="rtl-nm" style={{ color: 'var(--accent-t)' }}><span>负责人</span></span>
            <div className="rtl-tr">
              {leadRounds.map((r: Round) => (
                <i key={r.turn.seq} className={`rtl-tick${r.live ? ' live' : ''}`} style={{ left: `${pct(r.e)}%` }} title={`负责人第 ${r.n} 轮 · ${when(r.e, now)}`} />
              ))}
            </div>
            {desktop ? <div className="rtl-sm">醒了 {leadRounds.length} 次</div> : null}
          </div>
        ) : null}
        {g.live.length ? <div className="rtl-grp">在做 {g.live.length}</div> : null}
        {g.live.map(row)}
        {g.done.length ? <div className="rtl-grp">做完 {g.done.length}{moreDone.length && !open.done ? `（显示最近 ${DONE_SHOWN} 个）` : ''}</div> : null}
        {shownDone.map(row)}
        {moreDone.length ? <Fold open={!!open.done} label={`这段时间还做完 ${moreDone.length} 个`} names={tn(moreDone)} desktop={desktop} onToggle={() => toggle('done')} /> : null}
        {g.older.length ? <Fold open={!!open.older} label={`更早做完 ${g.older.length} 个`} names={tn(g.older)} desktop={desktop} onToggle={() => toggle('older')} /> : null}
        {open.older ? g.older.map(row) : null}
        {g.idle.length ? <Fold open={!!open.idle} label={`停掉或专项里没跑过 ${g.idle.length} 个`} names={g.idle.map((l: Lane) => `${l.label} ${l.title}`).join('、')} desktop={desktop} onToggle={() => toggle('idle')} /> : null}
        {open.idle ? g.idle.map(row) : null}
        {nowIn ? <div className="rtl-nowbox"><i style={{ left: `${pct(now)}%` }} /></div> : null}
      </div>
    </div>
  );
};

interface TokenGroup {
  lane: Lane;
  rounds: Round[];
  tokens: number;
  input: number;
  output: number;
  cache: number;
  seconds: number;
  live: boolean;
  failed: boolean;
}

const FIRST = 6;
const roundTok = (r: Round): number => r.turn.usage?.total ?? 0;

/** token 花在哪：先一句结论（前 3 个话题占多少、多少是缓存读），表里默认一个话题一行、只列前 FIRST 个；点开一行看各轮的输入、输出 */
const TokenTable: React.FC<{ model: ReportModel; desktop: boolean; overs: Set<string> }> = ({ model, desktop, overs }) => {
  const [open, setOpen] = useState<Set<string>>(() => new Set<string>());
  const [all_, setAll] = useState<boolean>(false);
  const [by, setBy] = useState<'tok' | 'time'>('tok');
  // 网页只给最近几轮推了用量：没有 token 也没有用时的轮次不算进话题，合成表尾一句
  const counted = (r: Round): boolean => r.live || r.hold || roundTok(r) > 0 || r.seconds > 0;
  const all: Round[] = model.lanes.flatMap((l: Lane) => l.rounds);
  const groups: TokenGroup[] = model.lanes
    .map((lane: Lane): TokenGroup => {
      const rounds: Round[] = lane.rounds.filter(counted);
      const sum = (f: (r: Round) => number): number => rounds.reduce((s: number, r: Round) => s + f(r), 0);
      return {
        lane,
        rounds,
        tokens: sum(roundTok),
        input: sum((r: Round) => r.turn.usage?.input ?? 0),
        output: sum((r: Round) => r.turn.usage?.output ?? 0),
        cache: sum((r: Round) => r.turn.usage?.cache_read ?? 0),
        seconds: sum((r: Round) => r.seconds),
        live: rounds.some((r: Round) => r.live),
        failed: rounds.some((r: Round) => r.failed),
      };
    })
    .filter((g: TokenGroup) => g.rounds.length)
    .sort((a: TokenGroup, b: TokenGroup) => (by === 'tok' ? b.tokens - a.tokens || b.seconds - a.seconds : b.seconds - a.seconds || b.tokens - a.tokens));
  const total: number = groups.reduce((s: number, g: TokenGroup) => s + g.tokens, 0);
  const byTok: TokenGroup[] = [...groups].sort((a, b) => b.tokens - a.tokens);
  const top3: TokenGroup[] = byTok.slice(0, 3).filter((g: TokenGroup) => g.tokens > 0);
  const share: number = total ? Math.round((top3.reduce((s: number, g: TokenGroup) => s + g.tokens, 0) / total) * 100) : 0;
  const input: number = groups.reduce((s: number, g: TokenGroup) => s + g.input, 0);
  const cache: number = groups.reduce((s: number, g: TokenGroup) => s + g.cache, 0);
  const output: number = groups.reduce((s: number, g: TokenGroup) => s + g.output, 0);
  const cachePct: number | null = input > 0 ? Math.round((cache / input) * 100) : null;
  const bare: number = all.length - groups.reduce((s: number, g: TokenGroup) => s + g.rounds.length, 0);
  const max: number = Math.max(1, ...groups.map((g: TokenGroup) => g.tokens));
  const shown: TokenGroup[] = all_ ? groups : groups.slice(0, FIRST);
  const rest: TokenGroup[] = groups.slice(FIRST);
  const work: number = groups.filter((g: TokenGroup) => !g.lane.lead).reduce((s: number, g: TokenGroup) => s + g.seconds, 0);
  const toggle = (key: string): void =>
    setOpen((prev: Set<string>) => {
      const next = new Set<string>(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  const colour = (lane: Lane, live: boolean, failed: boolean): string => (live ? 'var(--run)' : failed ? 'var(--fail)' : lane.lead ? 'var(--a1)' : GREY);
  const nameOf = (l: Lane): string => (l.lead ? '负责人' : l.title ? `${l.label} ${l.title}` : l.label);
  const cols: number = desktop ? 6 : 4;
  return (
    <div className="card rt-card rpt-tok" style={{ minWidth: 0 }}>
      <div className="rpt-h">
        <b>token 花在哪</b>
        <span className="rtl-seg">
          <a role="button" className={by === 'tok' ? 'on' : ''} onClick={() => setBy('tok')}>按 token</a>
          <a role="button" className={by === 'time' ? 'on' : ''} onClick={() => setBy('time')}>按用时</a>
        </span>
      </div>
      {total ? (
        <p className="rpt-big">
          {groups.length > 2 ? (
            <>
              共 {fmtTok(total)}，<b>前 {top3.length} 个话题占 {share}%</b>：{top3.map((g: TokenGroup) => `${nameOf(g.lane)}（${g.rounds.length} 轮）`).join('、')}。
            </>
          ) : (
            <>共 {fmtTok(total)}。</>
          )}
          {cachePct !== null ? <span className="t3">其中 {cachePct}% 是缓存读（按缓存价算），新读入 {fmtTok(Math.max(0, input - cache))}、输出 {fmtTok(output)}。</span> : null}
        </p>
      ) : null}
      <div style={{ overflowX: 'auto' }}>
        <table className="rpt-tb">
          <thead>
            <tr>
              <th>话题</th>
              <th className="r">用时</th>
              <th className="r">token</th>
              {desktop ? <th className="r">占比</th> : null}
              {desktop ? <th /> : null}
              <th />
            </tr>
          </thead>
          <tbody>
            {shown.map((g: TokenGroup) => {
              const { lane } = g;
              const unfolded: boolean = open.has(lane.key);
              const c: string = colour(lane, g.live, g.failed && !g.live);
              const Chev = unfolded ? ChevronDown : ChevronRight;
              return (
                <React.Fragment key={lane.key}>
                  <tr className="grp" onClick={() => toggle(lane.key)} title={unfolded ? '收起各轮' : '点开看各轮的输入、输出'}>
                    <td>
                      <div className="nm">
                        <Chev />
                        <i className="dot" style={{ background: c }} />
                        <span className="tt">{nameOf(lane)}</span>
                        {desktop ? <span className="t3" style={{ flex: 'none' }}>{g.rounds.length} 轮</span> : null}
                        {desktop && overs.has(lane.key) ? <span className="rpt-flag">超时</span> : null}
                      </div>
                      {/* 手机：轮数和“超时”挪到第二行，话题名不再被挤成“T538 …” */}
                      {desktop ? null : (
                        <div className="nm2">
                          <span>{g.rounds.length} 轮</span>
                          {overs.has(lane.key) ? <span className="rpt-flag">超时</span> : null}
                        </div>
                      )}
                    </td>
                    <td className="r mono t2">{g.seconds ? mins(g.seconds) : g.live ? '在跑' : '—'}</td>
                    <td className="r mono">{g.tokens ? fmtTok(g.tokens) : '—'}</td>
                    {desktop ? <td className="r mono t3">{total ? `${Math.round((g.tokens / total) * 100)}%` : ''}</td> : null}
                    {desktop ? <td style={{ width: '28%' }}><div className="rpt-bar"><i style={{ width: `${(g.tokens / max) * 100}%`, background: c }} /></div></td> : null}
                    <td />
                  </tr>
                  {unfolded
                    ? g.rounds.map((r: Round) => {
                        const u = r.turn.usage;
                        return (
                          <tr key={`${lane.key}:${r.turn.seq}`} className="sub">
                            <td><div className="nm"><span className="t3">第 {r.n} 轮 · {hhmm(r.s)}</span><span className="t3 io">输入 {u?.input ? fmtTok(u.input) : '—'} · 输出 {u?.output ? fmtTok(u.output) : '—'}</span></div></td>
                            <td className="r mono t2">{r.seconds ? mins(r.seconds) : r.live ? '在跑' : '—'}</td>
                            <td className="r mono">{roundTok(r) ? fmtTok(roundTok(r)) : '—'}</td>
                            {desktop ? <td /> : null}
                            {desktop ? <td /> : null}
                            <td />
                          </tr>
                        );
                      })
                    : null}
                </React.Fragment>
              );
            })}
            {rest.length ? (
              <tr className="more-row" onClick={() => setAll(!all_)}>
                <td colSpan={cols} className="t3">{all_ ? '收起' : `其余 ${rest.length} 个 · 共 ${fmtTok(rest.reduce((s: number, g: TokenGroup) => s + g.tokens, 0))} · 展开`}</td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
      <p className="rpt-note">合计 {fmtTok(total)} · 话题共 {mins(work)}{bare ? ` · 另有 ${bare} 轮没有用量记录` : ''}</p>
    </div>
  );
};

/** 预计 vs 实际：先一句总体，再按超出从大到小列前 3 个（预计→实际、百分比、超得最多那一轮回答的第一句）；
 * 差 OVER_SEC 或 OVER_PCT 以内的折叠不点名；条形默认按偏差，可切回按 T 号 */
const PlanVsActual: React.FC<{ model: ReportModel; sum: PlanSummary }> = ({ model, sum }) => {
  const [by, setBy] = useState<'dev' | 'num'>('dev');
  const [showAll, setShowAll] = useState<boolean>(false);
  const rows: Overrun[] = sum.rows;
  const plans: Plan[] = model.plans.filter((p: Plan) => p.plan > 0);
  if (!model.plans.length) return null;
  const head = !plans.length ? (
    <>Covey 在一轮做到一半、步骤清单走过几步后才估得出还要多久；这 {model.plans.length} 个话题还没估出来过。</>
  ) : (
    <>
      估过 {rows.length} 个话题：<b>{sum.within.length} 个在预计内</b>
      {sum.under.length ? `，${sum.under.length} 个提前（共省 ${fmtDur(sum.underSec, false)}）` : ''}
      {sum.over.length ? (
        <>
          ，<b className="f">{sum.over.length} 个明显超出，合计多花 {fmtDur(sum.overSec, false)}</b>
          {sum.over.length > 3 ? '，大头是这 3 个：' : '：'}
        </>
      ) : '，没有明显超出的。'}
    </>
  );
  const rest: Overrun[] = sum.over.slice(3);
  const tail: string =
    (rest.length ? `还有 ${rest.map((r) => `${r.lane.label} 多 ${mins(r.d)}`).join('、')}。` : '') +
    (sum.never.length ? `没估出来的 ${sum.never.length} 个：${sum.never.map((l: Lane) => l.label).join('、')}（一轮太短或步骤太少，估不出来）。` : '');
  const listed: Overrun[] =
    by === 'dev' ? (showAll ? [...rows].sort((a, b) => b.d - a.d) : [...sum.over, ...sum.under]) : [...rows].sort((a, b) => a.lane.label.localeCompare(b.lane.label, 'zh', { numeric: true }));
  const scale: number = Math.max(1, ...rows.map((r) => Math.max(r.plan.plan, r.plan.act)));
  return (
    <div className="card rpt-pva" style={{ minWidth: 0 }}>
      <div className="rpt-h">
        <b>预计 vs 实际用时</b>
        <span className="rtl-seg">
          <a role="button" className={by === 'dev' ? 'on' : ''} onClick={() => setBy('dev')}>按偏差</a>
          <a role="button" className={by === 'num' ? 'on' : ''} onClick={() => setBy('num')}>按 T 号</a>
        </span>
      </div>
      <p className="rpt-big">{head}</p>
      {sum.over.slice(0, 3).map((r) => (
        <div className="rpt-it" key={r.lane.key}>
          <div className="h">
            <span className="mono t3 short">{r.lane.label}</span>
            <b>{r.lane.title}</b>
            <span className="d">+{mins(r.d)}（+{Math.round(r.pct * 100)}%）</span>
          </div>
          <div className="m">预计 {fmtDur(r.plan.plan, false)} → 实际 {fmtDur(r.plan.act, false)}</div>
          {r.worst ? (
            <div className="why">
              第 {r.worst.n} 轮超得最多（预计 {fmtDur(r.worst.turn.estimate_seconds ?? 0, false)}，用了 {fmtDur(r.worst.seconds, false)}）{r.why ? `：${r.why}` : '。'}
            </div>
          ) : null}
        </div>
      ))}
      {tail ? <p className="rpt-note">{tail}</p> : null}
      {rows.length ? (
        <>
          <div className="rpt-lg">
            <span><i style={{ background: 'var(--s3)', boxShadow: 'inset 0 0 0 1px var(--line2)' }} />预计</span>
            <span><i style={{ background: 'var(--fail)' }} />超出</span>
            <span><i style={{ background: 'var(--done)' }} />提前</span>
            <span><i style={{ background: GREY }} />在预计内</span>
          </div>
          {listed.map((r) => (
            <div className="rpt-pv" key={r.lane.key} title={`${r.lane.label} ${r.lane.title}：预计 ${mins(r.plan.plan)}，实际 ${mins(r.plan.act)}`}>
              <span className="nm"><span className="mono t3 short">{r.lane.label}</span> {r.lane.title}</span>
              <div className="tr">
                <i className="p" style={{ width: `${(r.plan.plan / scale) * 100}%` }} />
                <i className={`a${r.over ? ' o' : r.under ? ' u' : ''}`} style={{ width: `${Math.max((r.plan.act / scale) * 100, 1)}%` }} />
              </div>
              <span className={`dd${r.over ? ' f' : r.under ? ' dn' : ' t3'}`}>{r.d >= 0 ? '+' : '−'}{mins(Math.abs(r.d))}</span>
            </div>
          ))}
          {by === 'dev' && sum.within.length ? (
            <a className="rtl-fold" role="button" onClick={() => setShowAll(!showAll)}>
              {showAll ? <ChevronDown /> : <ChevronRight />}
              <span>{showAll ? '只看明显超出和提前的' : `其余 ${sum.within.length} 个在预计内（差 10 分钟或 20% 以内）`}</span>
              <span className="more">{showAll ? '收起' : '展开'}</span>
            </a>
          ) : null}
        </>
      ) : null}
    </div>
  );
};

const ProjectReport: React.FC<{ p: SnapshotProject; topics: SnapshotTopic[]; lead: SnapshotTopic | undefined; m: ProjectMetrics; rep: ReportResponse | undefined }> = ({ p, topics, lead, m, rep }) => {
  const desktop: boolean = useIsDesktop();
  const now: number = useTick(5000);
  const model: ReportModel = useMemo(() => buildReport(rep, topics, lead, now, p.started_at), [rep, topics, lead, now, p.started_at]);
  if (!rep) return <div className="page" />;
  const start: number | null = m.startedAt ?? (model.rounds.length ? model.t0 : null);
  // 还在等你的题：只有 state open 的（和看板的“等你”同一个来源）；关掉、代答、过期的不算
  const openQ = model.waiting;
  const longest = openQ.reduce<(typeof openQ)[number] | undefined>((a, q) => (!a || (q.asked_at ?? 0) < (a.asked_at ?? 0) ? q : a), undefined);
  const waits: number[] = model.answeredWaits;
  const avgWait: number | null = waits.length ? waits.reduce((s: number, w: number) => s + w, 0) / waits.length : null;
  const openTopics: string[] = [...new Set(openQ.map((q) => `T${q.number ?? ''}`))];
  // 等你的话题和专项头部、看板同一个读法（话题的 tone）：有题在等的，也有等你点开始的
  const waitingTopics: SnapshotTopic[] = topics.filter(topicWaits);
  const lastRework: Round | undefined = model.reworks[model.reworks.length - 1];
  const reworkLane: Lane | undefined = lastRework ? model.lanes.find((l: Lane) => l.rounds.includes(lastRework)) : undefined;
  const noTopics: boolean = !topics.length;
  const leadLane: Lane | undefined = model.lanes.find((l: Lane) => l.lead);
  const sum: PlanSummary = planSummary(model);
  const overs = new Set<string>(sum.over.map((r: Overrun) => r.lane.key));
  return (
    <div className="page scroll rpt-page" style={{ overflowY: 'auto', paddingTop: 12 }}>
      <div className="card rt-card">
        <div className="rpt-h">
          <b>时间轴</b>
          <span className="t3" style={{ fontSize: 12 }}>一行一个话题 · 连着的几轮合成一段 · 点话题名打开</span>
        </div>
        {model.lanes.length ? <Timeline model={model} lead={leadLane} now={now} desktop={desktop} /> : null}
        {noTopics ? (
          <div className="rempty">
            <b>这个专项还没有话题</b>
            <span>负责人派出话题，或者把已有话题挂进这个专项以后，这里按话题一行，画出每一轮的起止、等你的时间和做完的时刻。{lead ? '现在只有负责人这一行。' : ''}</span>
          </div>
        ) : null}
      </div>
      <div className="rtiles" style={{ gridTemplateColumns: desktop ? 'repeat(6,1fr)' : 'repeat(2,1fr)', marginTop: 10 }}>
        <Tile label={<><Clock3 />用时</>} value={start ? <DurValue sec={Math.max(60, now - start)} /> : '—'} sub={start ? `${hhmm(start)} – ${hhmm(now)}` : ''} series={model.series.span} color="var(--run)" />
        <Tile label={<><Zap />话题共工作</>} value={model.work ? <DurValue sec={model.work} /> : '—'} sub={topics.length ? `${topics.length} 个话题${model.parallel > 1 ? ` · 最多 ${model.parallel} 个并行` : ''}` : '还没有话题'} series={model.series.work} color="var(--a1)" />
        <Tile
          label={<><HelpCircle />等你</>}
          value={
            longest ? <DurValue sec={now - (longest.asked_at ?? now)} /> : waitingTopics.length ? `${waitingTopics.length} 个话题` : avgWait !== null ? <DurValue sec={avgWait} /> : '—'
          }
          sub={
            longest
              ? `T${longest.number ?? ''} 还在等${waitingTopics.length > 1 ? ` · 共 ${waitingTopics.length} 个话题` : ''}`
              : waitingTopics.length
                ? `${waitingTopics.slice(0, 2).map((t: SnapshotTopic) => `T${t.number ?? ''}`).join('、')} 等你`
                : avgWait !== null
                  ? '平均 · 现在没在等'
                  : '没等过你'
          }
          cls={longest || waitingTopics.length ? 'c-wait' : ''}
          series={model.series.wait}
          color="var(--wait)"
        />
        <Tile label={<><Database />token</>} value={model.tokens ? fmtTok(model.tokens) : '—'} sub={model.cachePct !== null ? `缓存命中 ${model.cachePct}%` : ''} series={model.series.tokens} color="var(--a1)" />
        <Tile label={<><Undo2 />返工</>} value={model.reworks.length} sub={lastRework && reworkLane ? `${reworkLane.label} 第 ${lastRework.n} 轮` : '没有返工'} series={model.series.rework} color="var(--fail)" />
        <Tile
          label={<><Diamond />问题</>}
          value={model.questions.length}
          sub={
            !model.questions.length
              ? '没问过你'
              : openQ.length
                ? `等你答 ${openQ.length}（${openTopics.slice(0, 2).join('、')}）`
                : `都答了${model.leadAnswered ? ` · 负责人答 ${model.leadAnswered}` : ''}`
          }
          cls={openQ.length ? 'c-wait' : ''}
          series={model.series.questions}
          color="var(--wait)"
        />
      </div>
      {model.rounds.length ? (
        <div className="rgrid" style={{ display: 'grid', gridTemplateColumns: desktop ? 'minmax(0,1.1fr) minmax(0,1fr)' : 'minmax(0,1fr)', gap: 10, marginTop: 10, alignItems: 'start' }}>
          <TokenTable model={model} desktop={desktop} overs={overs} />
          {noTopics ? null : <PlanVsActual model={model} sum={sum} />}
        </div>
      ) : null}
      {p.status_reason ? <p className="t3" style={{ fontSize: 12, marginTop: 10 }}>{p.status_reason}</p> : null}
    </div>
  );
};
export default ProjectReport;
