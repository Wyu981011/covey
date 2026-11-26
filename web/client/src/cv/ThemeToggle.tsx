import React from 'react';
import { Moon, Sun } from 'lucide-react';
import { setLight, useUi } from './store';
import { themeFlip, type ThemeFlip } from './theme';

/** 深色、浅色切换的图标按钮（T842，theme.ts 说放在哪）：Shell.tsx 的侧栏底部和手机顶栏各放一个，样式在 covey.css 的 .theme-tg */
export const ThemeToggle: React.FC = () => {
  const ui = useUi();
  const f: ThemeFlip = themeFlip(ui.light);
  return (
    <button type="button" className="theme-tg" title={f.label} aria-label={f.label} onClick={() => setLight(f.next)}>
      {f.icon === 'sun' ? <Sun aria-hidden="true" /> : <Moon aria-hidden="true" />}
    </button>
  );
};
