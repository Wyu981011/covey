/** 深色、浅色切换（T842）：一个常驻的图标，任何页面都能点。电脑上在侧栏底部「设置」旁（收起的侧栏里叠在设置上面），
 * 手机在顶栏最右；设置页不再另有一块「外观」。图标画的是点了以后换成的那一种：深色时是太阳，浅色时是月亮。
 * 选了哪种照旧记在这台浏览器上（store.ts setLight，localStorage 的 covey.theme）。纯函数，单测直接导入（npm run test:theme） */

export interface ThemeFlip {
  /** 点了以后是不是浅色 */
  next: boolean;
  /** 按钮的 title 和 aria-label */
  label: string;
  /** 画哪个线性图标（lucide 的 Sun、Moon） */
  icon: 'sun' | 'moon';
}

export const themeFlip = (light: boolean): ThemeFlip =>
  light ? { next: false, label: '换成深色', icon: 'moon' } : { next: true, label: '换成浅色', icon: 'sun' };
