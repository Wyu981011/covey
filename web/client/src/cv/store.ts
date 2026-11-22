import { useSyncExternalStore } from 'react';
import { pref, setPref } from './lib';

/** 界面小状态：主题、侧栏收起、手机侧栏抽屉。主题和收起记在本地。 */
interface UiState {
  light: boolean;
  collapsed: boolean;
  menu: boolean;
  /** 手机底部标签打开抽屉时滚到哪一段：专项或话题 */
  focus: '' | 'projects' | 'topics';
}
let state: UiState = { light: pref('theme', 'dark') === 'light', collapsed: pref('collapsed', '0') === '1', menu: false, focus: '' };
const listeners = new Set<() => void>();
const set = (p: Partial<UiState>): void => {
  state = { ...state, ...p };
  listeners.forEach((l: () => void) => l());
};
export const useUi = (): UiState =>
  useSyncExternalStore(
    (cb: () => void) => {
      listeners.add(cb);
      return () => listeners.delete(cb);
    },
    () => state,
  );
export const setLight = (v: boolean): void => {
  setPref('theme', v ? 'light' : 'dark');
  set({ light: v });
};
export const setCollapsed = (v: boolean): void => {
  setPref('collapsed', v ? '1' : '0');
  set({ collapsed: v });
};
export const setMenu = (v: boolean, focus: UiState['focus'] = ''): void => set({ menu: v, focus });

/** 先放着：主人在网页上把某一轮没做完的先搁下，它就不再出现在“等你的事”和看板的等你里（记在本地） */
const LATER_KEY = 'covey.later';
let later: ReadonlySet<string> = (() => {
  try {
    return new Set<string>(JSON.parse(window.localStorage.getItem(LATER_KEY) ?? '[]') as string[]);
  } catch {
    return new Set<string>();
  }
})();
const laterListeners = new Set<() => void>();
export const useLater = (): ReadonlySet<string> =>
  useSyncExternalStore(
    (cb: () => void) => {
      laterListeners.add(cb);
      return () => laterListeners.delete(cb);
    },
    () => later,
  );
export const putLater = (turnKey: string): void => {
  later = new Set<string>([...later, turnKey].slice(-200));
  try {
    window.localStorage.setItem(LATER_KEY, JSON.stringify([...later]));
  } catch {
    /* 隐私模式 */
  }
  laterListeners.forEach((l: () => void) => l());
};
