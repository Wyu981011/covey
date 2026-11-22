import { useEffect, useState } from 'react';

const QUERY = '(min-width: 1024px)';

/** 桌面（≥1024px）：侧栏 + 两栏；否则顶栏 + 底部标签 */
export function useIsDesktop(): boolean {
  const [on, setOn] = useState<boolean>(() => typeof window !== 'undefined' && window.matchMedia(QUERY).matches);
  useEffect(() => {
    const mql: MediaQueryList = window.matchMedia(QUERY);
    const onChange = (): void => setOn(mql.matches);
    mql.addEventListener('change', onChange);
    onChange();
    return () => mql.removeEventListener('change', onChange);
  }, []);
  return on;
}

/** 每隔 ms 重算一次“现在”，给“最后同步”的灰点用 */
export function useNow(ms: number): number {
  const [now, setNow] = useState<number>(() => Date.now());
  useEffect(() => {
    const id: number = window.setInterval(() => setNow(Date.now()), ms);
    return () => window.clearInterval(id);
  }, [ms]);
  return now;
}
