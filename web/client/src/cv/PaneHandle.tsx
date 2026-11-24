import React, { useEffect, useRef, useState } from 'react';
import { MAIN_MIN, dragWidth, keyWidth, saveWidth, showWidth, type PaneSpec } from './panes';
import './panes.css';

/* 两侧栏的拖动分界（T741）：放在面板和中间区之间的零宽把手。拖动调宽、双击回到默认、聚焦后 ← → 微调；宽度记在这台浏览器上（panes.ts） */

/** 把手调的那块面板：左侧栏在把手前面，右栏在把手后面 */
const paneOf = (h: HTMLElement, spec: PaneSpec): HTMLElement | null =>
  (spec.edge === 'left' ? h.previousElementSibling : h.nextElementSibling) as HTMLElement | null;

/** 中间区：把手另一边那块 */
const centerOf = (h: HTMLElement, spec: PaneSpec): HTMLElement | null =>
  (spec.edge === 'left' ? h.nextElementSibling : h.previousElementSibling) as HTMLElement | null;

const widthOf = (el: Element | null): number => (el ? el.getBoundingClientRect().width : 0);

/**
 * 面板这次最多能多宽：对话区至少留 MAIN_MIN。左侧栏的另一边是整个主区，里面若还有右栏，右栏的宽也要留着
 */
function roomOf(h: HTMLElement, spec: PaneSpec): number {
  const center: HTMLElement | null = centerOf(h, spec);
  if (!center) return Infinity;
  const inner: number = spec.edge === 'left' ? widthOf(center.querySelector('aside.a-rail, aside.nb-rail, aside.a-prail')) : 0;
  return widthOf(paneOf(h, spec)) + widthOf(center) - inner - MAIN_MIN;
}

interface Drag {
  id: number;
  x: number;
  start: number;
  room: number;
  last: number;
  frame: number;
}

export const PaneHandle: React.FC<{ spec: PaneSpec }> = ({ spec }) => {
  const ref = useRef<HTMLDivElement>(null);
  const drag = useRef<Drag | null>(null);
  const [on, setOn] = useState<boolean>(false);
  const [now, setNow] = useState<number>(spec.def);
  const measure = (): number => Math.round(ref.current ? widthOf(paneOf(ref.current, spec)) : spec.def) || spec.def;
  // 只在挂上时量一次；之后的宽度变化都经这里的拖动、键盘和双击，那时顺手更新
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => setNow(measure()), []);

  const end = (commit: boolean): void => {
    const d: Drag | null = drag.current;
    if (!d) return;
    drag.current = null;
    window.cancelAnimationFrame(d.frame);
    showWidth(spec, d.last);
    // 只点了一下、没挪：不记，免得把默认宽度写死
    if (commit && d.last !== d.start) saveWidth(spec, d.last);
    setOn(false);
    setNow(d.last);
    document.body.classList.remove('cv-resizing');
  };

  return (
    <div
      ref={ref}
      className={`pane-h ${spec.edge}${on ? ' on' : ''}`}
      role="separator"
      aria-orientation="vertical"
      aria-label={`调整${spec.label}宽度`}
      aria-valuemin={spec.min}
      aria-valuemax={spec.max}
      aria-valuenow={now}
      tabIndex={0}
      title="拖动调整宽度，双击恢复默认"
      data-testid={`pane-${spec.pref}`}
      onPointerDown={(e: React.PointerEvent<HTMLDivElement>) => {
        if (e.button !== 0 || !ref.current) return;
        e.preventDefault();
        e.currentTarget.setPointerCapture(e.pointerId);
        const start: number = measure();
        drag.current = { id: e.pointerId, x: e.clientX, start, room: roomOf(ref.current, spec), last: start, frame: 0 };
        setOn(true);
        document.body.classList.add('cv-resizing');
      }}
      onPointerMove={(e: React.PointerEvent<HTMLDivElement>) => {
        const d: Drag | null = drag.current;
        if (!d || e.pointerId !== d.id) return;
        const w: number = dragWidth(spec, d.start, e.clientX - d.x, d.room);
        if (w === d.last) return;
        d.last = w;
        window.cancelAnimationFrame(d.frame);
        d.frame = window.requestAnimationFrame(() => showWidth(spec, w));
      }}
      onPointerUp={() => end(true)}
      onPointerCancel={() => end(true)}
      onLostPointerCapture={() => end(true)}
      onDoubleClick={() => {
        showWidth(spec, null);
        saveWidth(spec, null);
        window.requestAnimationFrame(() => setNow(measure()));
      }}
      onKeyDown={(e: React.KeyboardEvent<HTMLDivElement>) => {
        if (!ref.current) return;
        const w: number | null = keyWidth(spec, measure(), e.key, e.shiftKey, roomOf(ref.current, spec));
        if (w === null) return;
        e.preventDefault();
        showWidth(spec, w);
        saveWidth(spec, w);
        setNow(w);
      }}
    />
  );
};
