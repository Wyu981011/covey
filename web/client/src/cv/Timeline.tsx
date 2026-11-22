import React from 'react';
import { AlertTriangle, RotateCcw } from 'lucide-react';
import { toast } from 'sonner';
import type { FailureAction, TurnFailure, TurnView } from '@shared/api.interface';
import { putLater, useLater } from './store';
import { ACTION_LABEL, ACTION_SAY } from './topicText';
/* 话题页的一轮按聊天画（chatTurn.tsx，T623）；这里只剩没做完那一轮的原因和按钮 */

/** 没成功的一轮，历史里那行回答就是停止的原话（已在“技术详情”里）：不再当正文画一遍 */
export function stopWords(a: TurnView): boolean {
  const body: string = a.body.trim();
  return a.status === 'failed' && !!body && !!a.failure?.detail && a.failure.detail.includes(body.slice(0, 60));
}

/** 「检查并继续」这类按钮：发一句话给话题；换模型网页上做不了，指去飞书 */
export function runAction(a: FailureAction, say: (text: string) => void): void {
  const text: string | undefined = ACTION_SAY[a];
  if (text) say(text);
  else toast.message('换模型请在飞书话题里点「🔁 换配置」');
}

/** 失败说明：一句人话 + 按钮，内部用语折进“技术详情” */
export const FailBox: React.FC<{
  failure: TurnFailure | undefined;
  turnKey: string;
  actionable: boolean;
  say: (text: string) => void;
  /** 还在看板上（要你处理）才给“先放着”；看板不列了就没什么可放 */
  pressing?: boolean;
}> = ({ failure, turnKey, actionable, say, pressing = true }) => {
  const later = useLater();
  if (!failure) {
    // 旧数据没有 failure：照现在的显示
    return (
      <div className="a-oldfail">
        <p style={{ color: 'var(--fail)', fontSize: 12 }}>这一轮失败了</p>
        {actionable ? <p className="t3" style={{ fontSize: 12 }}>这一轮没有做完。在下面写一句话，会开始下一轮。</p> : null}
      </div>
    );
  }
  const acts: FailureAction[] = failure.actions;
  return (
    <div className="a-fail" role="note">
      <AlertTriangle className="a-fic" />
      <div className="a-ft">
        <b>{failure.title}</b>
        {failure.detail ? (
          <details>
            <summary>技术详情</summary>
            <code>{failure.detail}</code>
          </details>
        ) : null}
      </div>
      {actionable && !later.has(turnKey) ? (
        <div className="a-fb">
          {acts.map((a: FailureAction, i: number) => (
            <button type="button" key={a} className={`btn sm${i === 0 ? ' pri' : ''}`} onClick={() => runAction(a, say)}>
              {a === 'continue' ? <RotateCcw /> : null}
              {ACTION_LABEL[a]}
            </button>
          ))}
          {pressing ? <button type="button" className="btn sm a-ghost" onClick={() => putLater(turnKey)}>先放着</button> : null}
        </div>
      ) : null}
    </div>
  );
};

/** 问题 → 你的选择（负责人、管家替你答的，标题照实写） */
