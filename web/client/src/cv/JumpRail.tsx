import React, { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { activeIndex, cardTop, gap, tickLength, type Mark } from './jumpMarks';
import './jumprail.css';

/** 刻度区上下留的空：底下躲开「回到最新」 */
const PAD_TOP = 16;
const PAD_BOTTOM = 56;

/**
 * 对话区左边的刻度导航（T621，照 Codex）：一句你说的话（话题页是一轮）一条刻度，眼前这条最长；
 * 鼠标停在刻度上出预览卡（你说的那句 + 它怎么答的开头），点一下跳过去。只在电脑上、至少两条时画。
 */
export const JumpRail: React.FC<{
  marks: Mark[];
  feed: React.RefObject<HTMLDivElement | null>;
  onJump: (seq: number) => void;
}> = ({ marks, feed, onJump }) => {
  const [boxH, setBoxH] = useState<number>(0);
  const [active, setActive] = useState<number>(marks.length - 1);
  const [hover, setHover] = useState<number | null>(null);
  const [focus, setFocus] = useState<number | null>(null);
  const [cardH, setCardH] = useState<number>(96);
  const card = useRef<HTMLDivElement>(null);
  const btns = useRef<(HTMLButtonElement | null)[]>([]);
  const seqKey: string = marks.map((m: Mark) => m.seq).join(',');

  // 眼前这条：滚动时（每帧最多一次）和内容变了时重算
  useEffect(() => {
    const el: HTMLDivElement | null = feed.current;
    if (!el) return;
    let raf = 0;
    const measure = (): void => {
      raf = 0;
      const base: number = el.getBoundingClientRect().top - el.scrollTop;
      const at = new Map<number, number>();
      el.querySelectorAll<HTMLElement>('[data-seq]').forEach((x: HTMLElement) => {
        const s = Number(x.dataset.seq);
        if (!at.has(s)) at.set(s, x.getBoundingClientRect().top - base);
      });
      const tops: (number | null)[] = marks.map((m: Mark) => at.get(m.seq) ?? null);
      setActive(activeIndex(tops, { top: el.scrollTop, client: el.clientHeight, height: el.scrollHeight }));
      setBoxH(el.clientHeight);
    };
    const later = (): void => {
      if (!raf) raf = window.requestAnimationFrame(measure);
    };
    measure();
    el.addEventListener('scroll', later, { passive: true });
    const ro: ResizeObserver | null = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(later);
    ro?.observe(el);
    if (el.firstElementChild) ro?.observe(el.firstElementChild);
    return () => {
      el.removeEventListener('scroll', later);
      ro?.disconnect();
      if (raf) window.cancelAnimationFrame(raf);
    };
  }, [feed, seqKey]);

  const shown: number | null = hover ?? focus;
  useLayoutEffect(() => {
    if (shown !== null && card.current) setCardH(card.current.offsetHeight);
  }, [shown]);

  if (marks.length < 2 || !boxH) return null;
  const room: number = Math.max(0, boxH - PAD_TOP - PAD_BOTTOM);
  const g: number = gap(marks.length, room);
  const total: number = g * marks.length;
  const top: number = Math.max(PAD_TOP, Math.round((boxH - PAD_BOTTOM + PAD_TOP - total) / 2));
  const cur: number = Math.min(Math.max(active, 0), marks.length - 1);
  const m: Mark | undefined = shown === null ? undefined : marks[shown];

  const go = (i: number): void => {
    const x: Mark | undefined = marks[i];
    if (x) onJump(x.seq);
  };
  const onKey = (e: React.KeyboardEvent, i: number): void => {
    const to: number | null = e.key === 'ArrowUp' ? i - 1 : e.key === 'ArrowDown' ? i + 1 : e.key === 'Home' ? 0 : e.key === 'End' ? marks.length - 1 : null;
    if (to === null) return;
    e.preventDefault();
    btns.current[Math.max(0, Math.min(marks.length - 1, to))]?.focus();
  };

  return (
    <>
      <nav className="jr" aria-label="按你说的话跳转" style={{ top, height: total }} onMouseLeave={() => setHover(null)}>
        {marks.map((x: Mark, i: number) => (
          <button
            type="button"
            key={x.seq}
            ref={(b: HTMLButtonElement | null) => { btns.current[i] = b; }}
            className={`jr-t${i === cur ? ' on' : ''}${i === shown ? ' hv' : ''}${x.quiet ? ' quiet' : ''}`}
            style={{ height: g }}
            tabIndex={i === cur ? 0 : -1}
            aria-label={`${x.meta}：${x.title}`}
            aria-current={i === cur ? 'location' : undefined}
            onMouseEnter={() => setHover(i)}
            // 只有键盘移过来才出卡片：鼠标点完焦点留在刻度上，卡片不该一直盖着正文
            onFocus={(e: React.FocusEvent<HTMLButtonElement>) => setFocus(e.currentTarget.matches(':focus-visible') ? i : null)}
            onBlur={() => setFocus(null)}
            onKeyDown={(e: React.KeyboardEvent) => onKey(e, i)}
            onClick={() => go(i)}
          >
            <i style={{ width: tickLength(i, cur, shown) }} />
          </button>
        ))}
      </nav>
      {m && shown !== null ? (
        <div className="jr-card" ref={card} aria-hidden="true" style={{ top: cardTop(top + shown * g + g / 2, cardH, boxH) }}>
          <div className="jr-h">
            <b>{m.title}</b>
            <span>{m.meta}</span>
          </div>
          {m.body ? <p>{m.body}</p> : null}
        </div>
      ) : null}
    </>
  );
};
