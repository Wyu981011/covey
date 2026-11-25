/**
 * 输入框下沿往上浮的面板（换配置 .cfg-pop）放在哪（T789）：按输入框在视口里的位置固定定位，不再靠外层容器给的地方。
 * 原来是 absolute 挂在输入框上沿外面：对话区（.conv）是 overflow:hidden，输入框长高或放大编辑时上面只剩几十像素，面板上半截被裁掉，
 * 只看得见「取消 / 确认更换」。固定定位不受祖先的裁切；高度不超过输入框上沿到视口顶的那段（放不下就在面板里滚）。
 * 纯函数，不碰 DOM：防回归 scripts/switch-config.test.mjs。
 */

/** 面板和输入框上沿隔多少、离视口顶至少留多少 */
export const POP_GAP = 8;
export const POP_EDGE = 8;

export interface PopPlace {
  left: number;
  width: number;
  /** 离视口底多少（面板下沿贴着输入框上沿往上 gap） */
  bottom: number;
  /** 最多多高：输入框上沿往上到视口顶（留 edge）；CSS 里再和 70vh、620px 取小 */
  room: number;
}

/** host：输入框（手机是配置栏那一行）的框，视口坐标；vh：视口高 */
export function popPlace(host: { top: number; left: number; width: number }, vh: number, gap: number = POP_GAP, edge: number = POP_EDGE): PopPlace {
  const top: number = Math.min(Math.max(host.top, 0), vh);
  return {
    left: Math.round(host.left),
    width: Math.round(host.width),
    bottom: Math.round(vh - top + gap),
    room: Math.max(0, Math.floor(top - gap - edge)),
  };
}
