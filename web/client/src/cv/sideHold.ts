/** 侧栏在鼠标底下不挪（T779）：鼠标在侧栏里动着时，侧栏画鼠标进来那一刻的快照，同步来的新先后、新分组先不画；
 *  鼠标移出侧栏，或停着不动 IDLE_MS，再换成最新的。快照每秒取一次，话题开始做、做完、来了问题都会让下面整列挪一行，
 *  正要点的那行就从鼠标底下滑走了。只认鼠标和触控笔：手指没有悬停，手机抽屉照常跟着同步。 */
import type React from 'react';
import { useCallback, useEffect, useRef, useState } from 'react';

/** 鼠标停着不动多久就换成最新的：停着多半是在看别处，不是正要点 */
export const IDLE_MS = 5000;

const pointing = (e: { pointerType?: string }): boolean => e.pointerType === undefined || e.pointerType === 'mouse' || e.pointerType === 'pen';

export interface Held<T> {
  /** 该画的那份：拿着时是鼠标进来那刻的，否则是最新的 */
  view: T;
  /** 挂在侧栏最外层 */
  bind: {
    onPointerEnter: (e: React.PointerEvent) => void;
    onPointerMove: (e: React.PointerEvent) => void;
    onPointerLeave: (e: React.PointerEvent) => void;
    onWheel: () => void;
  };
}

export function useHeld<T>(live: T): Held<T> {
  // 存成 { v } 再拿：live 本身可能是 undefined（快照还没到），不能拿 null/undefined 当“没拿着”
  const [held, setHeld] = useState<{ v: T } | null>(null);
  const latest = useRef<T>(live);
  latest.current = live;
  const timer = useRef<number>(0);
  const release = useCallback((): void => {
    window.clearTimeout(timer.current);
    timer.current = 0;
    setHeld(null);
  }, []);
  const touch = useCallback((): void => {
    setHeld((h: { v: T } | null) => h ?? (latest.current == null ? null : { v: latest.current }));
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(release, IDLE_MS);
  }, [release]);
  const onPointer = useCallback((e: React.PointerEvent): void => {
    if (pointing(e)) touch();
  }, [touch]);
  const onLeave = useCallback((e: React.PointerEvent): void => {
    if (pointing(e)) release();
  }, [release]);
  useEffect(() => () => window.clearTimeout(timer.current), []);
  return { view: held ? held.v : live, bind: { onPointerEnter: onPointer, onPointerMove: onPointer, onPointerLeave: onLeave, onWheel: touch } };
}
