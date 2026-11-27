/* 「换个模型」直接展开同页输入框下沿的换配置面板（T647 P0-5，v33 how=switch），不再提示去飞书点「换配置」。
 * ConfigBar 挂上时登记自己（按话题），按钮叫 openSwitch；没有能换的面板（旧数据没有 config、设置里没有模型目录）就返回 false。 */
/** model：从「换个模型」打开（面板标题写“换个模型”，设备和仓库照旧折着）；不给是点配置栏打开的换配置 */
export type OpenWhy = 'model' | undefined;
type Opener = (why?: OpenWhy) => void;
const openers = new Map<string, Set<Opener>>();

/** ConfigBar 登记：这个话题的面板能被「换个模型」打开；返回注销 */
export function onOpenSwitch(topicKey: string, open: Opener): () => void {
  const set: Set<Opener> = openers.get(topicKey) ?? new Set<Opener>();
  set.add(open);
  openers.set(topicKey, set);
  return () => {
    set.delete(open);
    if (!set.size) openers.delete(topicKey);
  };
}

/** 打开这个话题的换配置面板；页面上没有能换的面板时返回 false（由调用方说一句怎么办） */
export function openSwitch(topicKey: string, why: OpenWhy = 'model'): boolean {
  const set: Set<Opener> | undefined = openers.get(topicKey);
  if (!set?.size) return false;
  set.forEach((open: Opener) => open(why));
  return true;
}

/** 这个话题现在有没有能被打开的换配置面板 */
export const canOpenSwitch = (topicKey: string): boolean => !!openers.get(topicKey)?.size;
