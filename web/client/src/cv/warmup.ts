/* 预热话题轮次什么时候开始（P1-9）：话题页、大厅马上开始；记忆中心、设置这类非话题页让出首屏，3 秒后再开始，
 * 免得 24 个话题请求抢在记忆首屏数据前面占满并发连接。 */
export const WARMUP_LATE_MS = 3000;
export const warmupDelay = (pathname: string): number => (/^\/(memory|settings)(\/|$)/u.test(pathname) ? WARMUP_LATE_MS : 0);
