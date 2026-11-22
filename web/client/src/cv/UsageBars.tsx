import React, { useEffect, useLayoutEffect, useRef, useState } from 'react';
import type { UsageDay } from '@shared/api.interface';
import { axisText, cachePct, dayWords, niceTicks, tokText } from './usageData';
import './usage.css';

/** 一天一根柱子（token），鼠标停上去、手指点一下或键盘左右键看那天的数。看板的「本周用量」和用量页共用 */
export const UsageBars: React.FC<{
  days: UsageDay[];
  /** 今天的日期：还没过完，柱子浅一档 */
  today: string;
  /** 柱子那块的高（不含横轴的字） */
  height: number;
  /** 纵轴刻度和横线（用量页）；看板里不画 */
  axis?: boolean;
  /** 最高那根的顶上写数 */
  peak?: boolean;
  /** 横轴第 i 天写什么；null 不写 */
  label: (d: UsageDay, i: number) => string | null;
  /** 选中的那天（用量页表格里同一行亮着） */
  picked?: string | null;
  onPick?: (date: string) => void;
  /** Covey 算到几点（21:30）：今天的浮窗写“今天到 21:30” */
  asOf?: string;
  /** 读屏念的一句话 */
  name: string;
}> = ({ days, today, height, axis = false, peak = false, label, picked = null, onPick, asOf = '', name }) => {
  const box = useRef<HTMLDivElement>(null);
  const tipBox = useRef<HTMLDivElement>(null);
  const [w, setW] = useState<number>(0);
  const [on, setOn] = useState<number | null>(null);
  const [tipW, setTipW] = useState<number>(180);
  const touch = useRef<boolean>(false);
  useLayoutEffect(() => {
    const el: HTMLDivElement | null = box.current;
    if (!el) return undefined;
    const measure = (): void => setW(el.clientWidth);
    measure();
    if (typeof ResizeObserver === 'undefined') return undefined;
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  // 手指点过一根以后，点图外面别处才收起浮窗
  useEffect(() => {
    if (on === null) return undefined;
    const away = (e: PointerEvent): void => {
      if (box.current && !box.current.contains(e.target as Node)) setOn(null);
    };
    document.addEventListener('pointerdown', away);
    return () => document.removeEventListener('pointerdown', away);
  }, [on]);
  useEffect(() => {
    if (on !== null && on >= days.length) setOn(null);
  }, [on, days.length]);
  // 浮窗按它自己的宽度收在图里，不伸出左右两边（手机上会伸出屏幕）
  useLayoutEffect(() => {
    if (on !== null && tipBox.current) setTipW(tipBox.current.offsetWidth);
  }, [on, days]);

  const n: number = days.length;
  const padL: number = axis ? 36 : 0;
  const padT: number = peak ? 18 : 6;
  const xBand = 18;
  const base: number = padT + height;
  const max: number = Math.max(0, ...days.map((d: UsageDay) => d.tokens));
  const ticks: number[] = axis ? niceTicks(max, 3) : [];
  const top: number = axis ? ticks[ticks.length - 1] || 1 : max || 1;
  const y = (v: number): number => padT + height * (1 - v / top);
  const band: number = n ? Math.max(0, w - padL) / n : 0;
  const barW: number = band >= 10 ? Math.min(24, band * 0.62) : Math.max(1, band - Math.min(2, band / 3));
  const cx = (i: number): number => padL + band * (i + 0.5);
  const clampX = (x: number, half: number): number => Math.min(Math.max(x, padL + half), Math.max(padL + half, w - half));
  const peakAt: number = peak && max > 0 ? days.findIndex((d: UsageDay) => d.tokens === max) : -1;

  const bar = (d: UsageDay, i: number): React.ReactNode => {
    if (d.tokens <= 0 || !band) return null;
    const y0: number = Math.min(base - 1.5, y(d.tokens));
    const h: number = base - y0;
    const x: number = cx(i) - barW / 2;
    const r: number = Math.min(4, barW / 2, h);
    const path = `M${x},${base}V${y0 + r}Q${x},${y0} ${x + r},${y0}H${x + barW - r}Q${x + barW},${y0} ${x + barW},${y0 + r}V${base}Z`;
    const cls: string = `ub-bar${d.date === today ? ' today' : ''}${i === on || d.date === picked ? ' on' : ''}`;
    return <path key={d.date} className={cls} d={path} />;
  };

  const move = (e: React.KeyboardEvent<HTMLDivElement>): void => {
    if (!n) return;
    const at: number = on ?? n - 1;
    let next: number | null = null;
    if (e.key === 'ArrowLeft') next = Math.max(0, at - 1);
    else if (e.key === 'ArrowRight') next = Math.min(n - 1, at + 1);
    else if (e.key === 'Home') next = 0;
    else if (e.key === 'End') next = n - 1;
    else if ((e.key === 'Enter' || e.key === ' ') && on !== null && onPick) {
      e.preventDefault();
      onPick(days[on].date);
      return;
    }
    if (next === null) return;
    e.preventDefault();
    setOn(next);
  };

  const tip = (): React.ReactNode => {
    if (on === null || !w || !days[on]) return null;
    const d: UsageDay = days[on];
    const pct: number | null = cachePct(d);
    const when: string = d.date === today ? ` · 今天${asOf ? `到 ${asOf}` : ''}` : '';
    return (
      <div ref={tipBox} className="ub-tip" style={{ left: Math.min(Math.max(cx(on), tipW / 2), Math.max(tipW / 2, w - tipW / 2)), top: Math.max(0, y(d.tokens) - 8) }} role="status">
        <div><b>{tokText(d.tokens)}</b> <span className="k">token</span></div>
        <div>{dayWords(d.date)}{when}</div>
        <div className="k">{d.tasks ? `${d.tasks} 个任务 · ${d.topics} 个话题${pct === null ? '' : ` · 缓存命中 ${pct}%`}` : '没有任务'}</div>
      </div>
    );
  };

  return (
    <div
      ref={box}
      className="ub"
      style={{ height: base + xBand }}
      tabIndex={0}
      role="group"
      aria-label={name}
      onKeyDown={move}
      onBlur={() => setOn(null)}
    >
      {w ? (
        <svg width={w} height={base + xBand} viewBox={`0 0 ${w} ${base + xBand}`} onPointerLeave={(e: React.PointerEvent) => { if (e.pointerType === 'mouse') setOn(null); }}>
          {ticks.map((t: number) => (
            <g key={t}>
              {t > 0 ? <line className="ub-grid" x1={padL} x2={w} y1={Math.round(y(t)) + 0.5} y2={Math.round(y(t)) + 0.5} /> : null}
              <text className="ub-tick" x={padL - 6} y={y(t) + 3.5} textAnchor="end">{axisText(t)}</text>
            </g>
          ))}
          {days.map(bar)}
          <line className="ub-base" x1={padL} x2={w} y1={Math.round(base) + 0.5} y2={Math.round(base) + 0.5} />
          {peakAt >= 0 && peakAt !== on ? (
            <text className="ub-peak" x={clampX(cx(peakAt), 16)} y={y(max) - 6} textAnchor="middle">{tokText(max)}</text>
          ) : null}
          {days.map((d: UsageDay, i: number) => {
            const text: string | null = label(d, i);
            return text ? (
              <text key={d.date} className={`ub-x${d.date === today ? ' today' : ''}${i === on || d.date === picked ? ' on' : ''}`}
                x={clampX(cx(i), 15)} y={base + 13} textAnchor="middle">{text}</text>
            ) : null;
          })}
          {days.map((d: UsageDay, i: number) => (
            <rect key={d.date} className="ub-hit" x={padL + band * i} y={0} width={band} height={base + xBand}
              onPointerEnter={(e: React.PointerEvent) => { if (e.pointerType === 'mouse') setOn(i); }}
              onPointerDown={(e: React.PointerEvent) => { touch.current = e.pointerType !== 'mouse'; }}
              onClick={() => {
                setOn(i);
                // 手指点是“看这天”（鼠标的停上去），不跳到表里；鼠标点才是“在表里找到这天”
                if (!touch.current) onPick?.(d.date);
              }} />
          ))}
        </svg>
      ) : null}
      {tip()}
    </div>
  );
};
