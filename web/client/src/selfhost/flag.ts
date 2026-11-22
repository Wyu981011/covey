/** 自托管构建（vite.selfhost.config.ts）在构建期把 __SELFHOST__ 定义成 true；妙搭构建里没有这个常量，值是 false */
declare const __SELFHOST__: boolean | undefined;

export const SELFHOST: boolean = typeof __SELFHOST__ !== 'undefined' && __SELFHOST__ === true;
