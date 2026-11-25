import React, { useState, useSyncExternalStore } from 'react';
import { RotateCcw } from 'lucide-react';
import { toast } from 'sonner';
import type { FailureButton, TurnFailure } from '@shared/api.interface';
import { newOpId, useSettings, useSnapshot } from '@client/src/hooks/use-workbench';
import { boardOn } from './lib';
import { useTick } from './ui';
import { autoRetryWords, recoverPayload, recoverPlan, type RecoverButton, type RecoverPlan } from './recover';
import { useOutboxOp, type OpResult } from './sendOp';
import { opWords } from './opWords';
import { openSwitch } from './switchOpen';
import './recover.css';

/* 点过的那一颗的回执记在这一页里（内存，不存本机）：点了检查并继续，新的一轮一开，停住的那一轮就不再给按钮，回执还留在它下面 */
interface Said {
  line: string;
  bad: boolean;
  at: number;
}
let said: ReadonlyMap<string, Said> = new Map<string, Said>();
const saidListeners = new Set<() => void>();
const SAID_MS = 10 * 60 * 1000;
const saidKey = (topicKey: string, jobId: string | null | undefined): string => `${topicKey}:${jobId ?? ''}`;
function putSaid(topicKey: string, jobId: string | null | undefined, v: Said): void {
  said = new Map<string, Said>([...said, [saidKey(topicKey, jobId), v]]);
  saidListeners.forEach((l: () => void) => l());
}
/** 这一轮最近一次在网页上点的按钮的回执（10 分钟内），没有是 null；回执到了会重画 */
export function useRecentSaid(topicKey: string, jobId: string | null | undefined): Said | null {
  const all: ReadonlyMap<string, Said> = useSyncExternalStore(
    (cb: () => void) => {
      saidListeners.add(cb);
      return () => saidListeners.delete(cb);
    },
    () => said,
  );
  const v: Said | undefined = all.get(saidKey(topicKey, jobId));
  return v && Date.now() - v.at < SAID_MS ? v : null;
}

/** 只有飞书能做的那一颗（管家、负责人的换个模型）：有机器人链接就给链接，没有就说去哪点 */
function feishuHint(feishu: string): void {
  if (feishu) {
    toast.message('换模型要在飞书里做', { action: { label: '去飞书', onClick: () => window.open(feishu, '_blank', 'noopener,noreferrer') } });
  } else {
    toast.message('换模型要在飞书话题里点「换配置」');
  }
}

/**
 * 没成功的一轮的按钮（T647 P0-5，v33）：看板的停住卡、话题页顶上的结论带、对话里那一轮下面共用。
 * - recover：发 recover 操作，和飞书任务卡上点同名按钮是同一个调用；点了以后按钮收起，原地写 Covey 的回执；
 * - switch：展开同页的换配置面板；feishu：说去飞书；
 * - 排着自动重试：写倒计时，只给“现在重试”“停止自动重试”，不做主按钮。
 * topicKey 是这一轮所在的话题（管家、负责人也行）；jobId 是这一轮的任务号，没有（旧数据）时点了走 noJob（看板：进话题）。
 */
export const RecoverActions: React.FC<{
  failure: TurnFailure;
  topicKey: string;
  jobId: string | null | undefined;
  /** 旧数据（没有 how）时换个模型能不能在网页上换：普通话题能，管家、负责人不能 */
  canSwitch?: boolean;
  /** 跟在按钮后面的（话题页的“先放着”、看板的“不管了”） */
  extra?: React.ReactNode;
  /** 没有任务号时点 recover 按钮做什么；不给就不画这几颗 */
  noJob?: () => void;
  /** 这一页没有换配置面板时「换个模型」怎么办（看板：进话题页并展开它）；不给就说去飞书 */
  onSwitch?: () => void;
  className?: string;
}> = ({ failure, topicKey, jobId, canSwitch, extra, noJob, onSwitch, className }) => {
  // 停住的一轮、右栏总览、看板卡各有一组按钮：点一处，处处锁住（同一个话题同一时刻只有一条恢复操作在等）
  const op = useOutboxOp(`recover:${topicKey}`);
  const feishu: string = useSettings().data?.data?.feishu ?? '';
  const now: number = useTick(15000);
  const plan: RecoverPlan = recoverPlan(failure, { canSwitch: canSwitch ?? true });
  const [pressed, setPressed] = useState<FailureButton | null>(null);
  // 办好了就收起按钮（新的一轮会接着出来）；停止自动重试例外：推回来的这一轮不再排着自动重试时，照新的 failure 再给按钮（检查并继续）
  const done: boolean = op.phase === 'done' && (pressed !== 'stop_auto_retry' || !!plan.auto);
  const press = (b: RecoverButton): void => {
    if (b.how === 'switch') {
      if (!openSwitch(topicKey)) {
        if (onSwitch) onSwitch();
        else feishuHint(feishu);
      }
      return;
    }
    if (b.how === 'feishu') {
      feishuHint(feishu);
      return;
    }
    const payload = recoverPayload(jobId, b.key);
    if (!payload) {
      noJob?.();
      return;
    }
    setPressed(b.key);
    // 新的一轮一开，这几颗按钮就收起了（组件卸下）：回执照样等到，记下来写在那一轮下面
    void op.run({ op_id: newOpId(), kind: 'recover', topic_key: topicKey, payload: { ...payload } }, true).then((r: OpResult) => {
      putSaid(topicKey, jobId, { line: opWords(r.phase, r.message), bad: r.phase === 'failed' || r.phase === 'unsent', at: Date.now() });
    });
  };
  const shown: RecoverButton[] = plan.buttons.filter((b: RecoverButton) => b.how !== 'recover' || !!recoverPayload(jobId, b.key) || !!noJob);
  return (
    <div className={`rc-acts${className ? ` ${className}` : ''}`}>
      {plan.auto ? <span className="rc-auto" role="status">{autoRetryWords(plan.auto, now, failure.title)}</span> : null}
      {done ? null : (
        <span className="rc-btns">
          {shown.map((b: RecoverButton) => (
            <button type="button" key={b.key} className={`btn sm${b.primary ? ' pri' : ''}`} disabled={op.busy} onClick={() => press(b)}>
              {b.primary && (b.key === 'continue' || b.key === 'retry') ? <RotateCcw /> : null}
              {b.label}
            </button>
          ))}
          {extra}
        </span>
      )}
      {op.line ? (
        <span className={`rc-said${op.phase === 'failed' || op.phase === 'unsent' ? ' bad' : ''}`} role={op.phase === 'failed' || op.phase === 'unsent' ? 'alert' : 'status'}>
          {op.line}
        </span>
      ) : null}
    </div>
  );
};

/**
 * 「不管了」（T647 P1-C3：以前话题页的“先放着”只记在这台浏览器上，现在和看板卡一样告诉 Covey）：发 dismiss，Covey 把话题从看板拿掉
 * （同飞书看板卡上的不管了），推回来 board 为空，看板、侧栏、话题页的要你处理一起少一件。只在开着看板时有用，调用方按 boardOn 决定画不画。
 * 点了以后按钮收起，原地写 Covey 的回执；没回音照 opWords 说，不当成失败。
 */
export const DismissButton: React.FC<{ topicKey: string; className?: string }> = ({ topicKey, className }) => {
  // 话题页上停住的一轮和右栏总览各有一个：点一处，另一处也收起、写同一句话
  const op = useOutboxOp(`dismiss:${topicKey}`);
  const failed: boolean = op.phase === 'failed' || op.phase === 'unsent';
  return (
    <>
      {op.busy || op.phase === 'done' ? null : (
        <button
          type="button"
          className={className ?? 'btn sm txt'}
          onClick={() => void op.run({ op_id: newOpId(), kind: 'dismiss', topic_key: topicKey, payload: {} })}
          title="这一轮不再算进要你处理（告诉 Covey 从看板拿掉，同看板卡上的不管了）"
        >
          不管了
        </button>
      )}
      {op.line ? <span className={`rc-said${failed ? ' bad' : ''}`} role={failed ? 'alert' : 'status'}>{op.line}</span> : null}
    </>
  );
};

/** 开着看板（话题带 board）：只有这时「不管了」才画（没开看板时 Covey 拿不掉，飞书里也只有看板卡上有不管了） */
export function useBoardOn(): boolean {
  const { data } = useSnapshot();
  return boardOn(data?.topics ?? []);
}
