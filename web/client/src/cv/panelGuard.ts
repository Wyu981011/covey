/**
 * 读机器人数据画出来的一块（换配置面板、配置栏、开新话题的选项）出错时，只在这一块说明、给「关闭」或「重试」，
 * 不再让根上的错误边界把整个工作台换成「页面出错了」（T97 11-27）。
 * 起因：机器人升到上游 T864 以后模型目录不带 workspaces、run_modes，同一次升级里网页没发布上，线上还是旧网页；
 * 旧网页的换配置面板一画就读 data.workspaces.find，抛 TypeError，点配置栏整页就崩了。网页和机器人版本对不上的事以后还会有，
 * 每块这样的面板自己兜住，其余地方照常能用。
 * 不写 JSX、只引 React 和 react-error-boundary：防回归 scripts/switch-config.test.mjs 能直接导入。
 */
import React from 'react';
import { ErrorBoundary, type FallbackProps } from 'react-error-boundary';

export interface GuardOpts {
  /** 这一块叫什么（“换配置面板”） */
  what: string;
  /** 打不开时还能去哪做（“在飞书话题里点「换配置」”） */
  elsewhere?: string;
  /** 有就画「关闭」（面板收起，下次打开重新画）；没有画「重试」 */
  onClose?: () => void;
  /** 变了就清掉错误重画（换了话题） */
  resetKey?: string;
  /** 小号：一行字，放在输入框下沿那一行里 */
  compact?: boolean;
}

/** 出错时那一句：哪一块、报错原文（截到 200 字）、多半为什么、怎么办 */
export function guardText(what: string, error: unknown, elsewhere = ''): string {
  const raw: string = error instanceof Error ? error.message : String(error ?? '');
  const message: string = raw.trim().slice(0, 200) || '未知错误';
  return `${what}读不懂机器人发来的数据（${message}），多半是网页比机器人旧：刷新页面${elsewhere ? `；还不行就${elsewhere}` : ''}。`;
}

/** 出错时画什么（react-error-boundary 的 fallbackRender） */
export function guardFallback(opts: GuardOpts): (p: FallbackProps) => React.ReactElement {
  return ({ error, resetErrorBoundary }: FallbackProps): React.ReactElement => {
    const text: string = guardText(opts.what, error, opts.elsewhere);
    const button: React.ReactElement = React.createElement(
      'button',
      { type: 'button', className: opts.compact ? 'guard-btn' : 'btn sm', onClick: opts.onClose ?? resetErrorBoundary },
      opts.onClose ? '关闭' : '重试',
    );
    if (opts.compact) {
      return React.createElement('span', { className: 'guard sm', role: 'alert', title: text, 'data-testid': 'panel-guard' }, `${opts.what}出错了`, button);
    }
    return React.createElement('div', { className: 'guard', role: 'alert', 'data-testid': 'panel-guard' },
      React.createElement('b', null, `${opts.what}打不开`), React.createElement('span', null, text), button);
  };
}

/** 把 children 兜住：出错只画 guardFallback，控制台留一行原始报错 */
export const PanelGuard: React.FC<GuardOpts & { children?: React.ReactNode }> = ({ children, ...opts }) =>
  React.createElement(
    ErrorBoundary,
    {
      fallbackRender: guardFallback(opts),
      resetKeys: [opts.resetKey ?? ''],
      onError: (error: unknown) => console.error(`[${opts.what}]`, error),
    },
    children,
  );
