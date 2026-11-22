import { useSyncExternalStore } from 'react';
import { dropLegacy, pref, setPref } from './lib';

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

/* 以前的「先放着」只记在这台浏览器上（covey.later）、只改这一端的计数；T647 P1-C3 起并成会告诉 Covey 的「不管了」（dismiss，
 * RecoverBits.tsx DismissButton）。旧缓存打开页面时删掉（lib.ts dropLegacy），不再读 */
try {
  dropLegacy(typeof window === 'undefined' ? null : window.localStorage);
} catch {
  /* 隐私模式 */
}
