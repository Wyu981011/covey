import React, { useEffect, useId, useRef, useState } from 'react';
import { AlertTriangle, Asterisk, Check, CheckCircle2, Clock, Code2, Loader2, Sparkles, User } from 'lucide-react';
import { useMe } from '@client/src/hooks/use-workbench';
import { harnessKind } from './lib';
import { STATES, type ToneKey } from './look.gen';
import './look.gen.css';

/** 每秒重算一次“现在”（秒）；reduced-motion 也照走，只是数字 */
export function useTick(ms = 1000): number {
  const [n, setN] = useState<number>(() => Date.now() / 1000);
  useEffect(() => {
    const id: number = window.setInterval(() => setN(Date.now() / 1000), ms);
    return () => window.clearInterval(id);
  }, [ms]);
  return n;
}

/** 状态点：颜色来自 look（.tone-*）；等你、停住了慢慢呼吸，可能卡住外加一圈淡环（docs/ui.md 第 9 节） */
export const Dot: React.FC<{ tone: ToneKey }> = ({ tone }) => <i className={`dot tone-${tone}`} />;

const PILL_ICON: Partial<Record<ToneKey, React.FC<{ className?: string }>>> = {
  waiting: Clock, stopped: AlertTriangle, stuck: AlertTriangle, result: CheckCircle2, running: Loader2, done: Check,
};
/** 状态胶囊 state_pill：图标加状态词，状态色 12% 底 */
export const Pill: React.FC<{ tone: ToneKey; text?: string; big?: boolean }> = ({ tone, text, big }) => {
  const Icon = PILL_ICON[tone];
  return (
    <span className={`pill tone-${tone}${big ? ' big' : ''}`}>
      {Icon ? <Icon className={tone === 'running' ? 'spin' : undefined} /> : <i className={`dot tone-${tone}`} />}
      {text ?? STATES[tone].word}
    </span>
  );
};

const reduced = (): boolean => typeof window !== 'undefined' && !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;

/** 数字变化时滚到新值（300ms）；减少动态效果时直接换 */
export const RollNum: React.FC<{ value: number }> = ({ value }) => {
  const [shown, setShown] = useState<number>(value);
  const from = useRef<number>(value);
  useEffect(() => {
    const start: number = from.current;
    if (start === value || reduced()) {
      from.current = value;
      setShown(value);
      return undefined;
    }
    const t0: number = performance.now();
    let id = 0;
    const step = (t: number): void => {
      const k: number = Math.min(1, (t - t0) / 300);
      const v: number = Math.round(start + (value - start) * (1 - (1 - k) ** 3));
      setShown(v);
      from.current = v;
      if (k < 1) id = requestAnimationFrame(step);
    };
    id = requestAnimationFrame(step);
    return () => cancelAnimationFrame(id);
  }, [value]);
  return <>{shown}</>;
};

/** 结论带 conclusion_band：小标签、大字（数字等宽）、灰色补充，最后是要你做条或分段状态条。背后一块上亮下暗的真渐变，1px 细边 */
export const ConclusionBand: React.FC<{
  label: React.ReactNode;
  n?: number | null;
  words: React.ReactNode;
  breathe?: ToneKey | null;
  sub?: React.ReactNode;
  /** 右下角各状态的件数（夜航 v2）：是 0 的压暗，不是 0 的亮 */
  counts?: [ToneKey, number][];
  action?: React.ReactNode;
  children?: React.ReactNode;
}> = ({ label, n, words, breathe, sub, counts, action, children }) => (
  <section className="nb-band" aria-live="polite">
    <div className="nb-l1">{label}</div>
    <div className="nb-main">
      <div className="nb-left">
        <div className="nb-l2">
          {typeof n === 'number' ? <b className="nb-n"><RollNum value={n} /></b> : null}
          <span className="nb-w">{words}</span>
          {breathe ? <i className={`dot breathe tone-${breathe}`} aria-hidden /> : null}
        </div>
        {sub ? <div className="nb-l3">{sub}</div> : null}
      </div>
      {counts ? (
        <div className="nb-counts">
          {counts.map(([k, c]) => (
            <span key={k} className={`tone-${k}${c ? '' : ' zero'}`}><b><RollNum value={c} /></b><em><i />{STATES[k].word}</em></span>
          ))}
        </div>
      ) : null}
      {action ? <div className="nb-act1">{action}</div> : null}
    </div>
    {children}
  </section>
);

/** 步骤格（夜航 v2）：每步一格，做完的灰、正在做的用状态色、没到的暗；比满宽进度条更说得清“到第几步” */
export const StepCells: React.FC<{ done: number; total: number; tone?: ToneKey }> = ({ done, total, tone = 'running' }) => {
  if (total <= 0) return null;
  const n: number = Math.min(total, 12);
  const on: number = Math.round((Math.min(done, total) / total) * n);
  return (
    <span className={`nb-steps tone-${tone}`} role="img" aria-label={`步骤 ${done} / ${total}`}>
      {Array.from({ length: n }).map((_, i: number) => <i key={i} className={i < on ? 'on' : i === on && done < total ? 'cur' : ''} />)}
    </span>
  );
};

/** 要你做条 todo_bar */
export const TodoBar: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <div className="nb-todo"><b>要你做</b><span>{children}</span></div>
);

/** 分段状态条 seg_bar：一条 6px 横条按件数分段，下面一行图例 */
export const StateBar: React.FC<{ parts: [ToneKey, number][]; legend?: boolean }> = ({ parts, legend = true }) => {
  const shown: [ToneKey, number][] = parts.filter(([, n]) => n > 0);
  if (!shown.length) return null;
  return (
    <div className="nb-seg">
      <div className="nb-segbar">
        {shown.map(([k, n]) => <i key={k} className={`tone-${k}`} style={{ flexGrow: n }} />)}
      </div>
      {legend ? (
        <div className="nb-legend">
          {shown.map(([k, n]) => (
            <span key={k} className={`tone-${k}`}><i />{n} {STATES[k].word}</span>
          ))}
        </div>
      ) : null}
    </div>
  );
};

/** 进度条 progress：5px，按步数；在做时一道光从左扫到右，可能卡住时不扫、变橙 */
export const Progress: React.FC<{ done: number; total: number; stuck?: boolean; live?: boolean }> = ({ done, total, stuck, live = true }) => {
  if (total <= 0) return null;
  const pct: number = Math.max(4, Math.min(100, (done / total) * 100));
  return (
    <div className={`nb-prog${stuck ? ' stuck' : ''}${live && !stuck ? ' live' : ''}`} role="progressbar" aria-valuemin={0} aria-valuemax={total} aria-valuenow={done}>
      <i style={{ width: `${pct}%` }} />
    </div>
  );
};

export const Hx: React.FC<{ harness: string; lead?: boolean }> = ({ harness, lead }) => {
  if (lead) {
    return (
      <span className="hxi lead">
        <Sparkles />
      </span>
    );
  }
  const k: 'cx' | 'cl' = harnessKind(harness);
  return <span className={`hxi ${k}`}>{k === 'cx' ? <Code2 /> : <Asterisk />}</span>;
};

/** 迷你折线（磁贴底部）；series 全 0 时不画 */
export const Spark: React.FC<{ series: number[]; color: string; className?: string; h?: number }> = ({ series, color, className, h = 26 }) => {
  const id: string = useId().replace(/:/gu, '');
  const max: number = Math.max(...series, 0);
  if (series.length < 2 || max <= 0) return null;
  const pts: string[] = series.map((v: number, i: number) => `${((i / (series.length - 1)) * 100).toFixed(1)},${(h - 3 - (v / max) * (h - 8)).toFixed(1)}`);
  const line = `M${pts.join(' L')}`;
  return (
    <svg className={className ?? 'sp'} viewBox={`0 0 100 ${h}`} preserveAspectRatio="none">
      <defs>
        <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={color} stopOpacity=".28" />
          <stop offset="1" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={`${line} L100,${h} L0,${h} Z`} fill={`url(#${id})`} stroke="none" />
      <path d={line} fill="none" stroke={color} strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
    </svg>
  );
};

export const Tile: React.FC<{
  label: React.ReactNode;
  value: React.ReactNode;
  sub?: React.ReactNode;
  cls?: string;
  series?: number[];
  color?: string;
}> = ({ label, value, sub, cls, series, color }) => (
  <div className={`tile ${cls ?? ''}`}>
    <div className="k">{label}</div>
    <div className="v">{value}</div>
    <div className="sub">{sub}</div>
    {series ? <Spark series={series} color={color ?? 'var(--accent-t)'} /> : null}
  </div>
);

/** “18 分 52 秒”拆成数字加小字单位 */
export const DurValue: React.FC<{ sec: number | null }> = ({ sec }) => {
  if (sec === null || !Number.isFinite(sec)) return <>—</>;
  const s: number = Math.round(sec);
  const h: number = Math.floor(s / 3600);
  const m: number = Math.floor((s % 3600) / 60);
  if (h > 0) return <>{h}<small>小时</small>{m}<small>分</small></>;
  if (m > 0) return <>{m}<small>分钟</small></>;
  return <>{s}<small>秒</small></>;
};

/** 当前登录用户的头像：名字第一个字；取不到时是中性图标，不编名字 */
export const Avatar: React.FC<{ size?: number }> = ({ size }) => {
  const { data } = useMe();
  const name: string = data?.name ?? '';
  const style: React.CSSProperties | undefined = size ? { width: size, height: size } : undefined;
  return (
    <span className="av" style={style} title={name || undefined} aria-label={name ? `当前用户 ${name}` : '当前用户'}>
      {name ? Array.from(name)[0] : <User style={{ width: '60%', height: '60%' }} />}
    </span>
  );
};
