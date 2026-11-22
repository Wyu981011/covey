/* eslint-disable no-restricted-syntax -- 这里就是替代平台 logger 的那一处：自托管只写浏览器控制台，不上报 */
/** 替代 @lark-apaas/client-toolkit/logger：只写浏览器控制台，不上报 */
export const logger = {
  debug: (...a: unknown[]): void => console.debug(...a),
  info: (...a: unknown[]): void => console.info(...a),
  log: (...a: unknown[]): void => console.log(...a),
  warn: (...a: unknown[]): void => console.warn(...a),
  error: (...a: unknown[]): void => console.error(...a),
};
export default logger;
