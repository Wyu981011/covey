import React from 'react';
import { AlertTriangle } from 'lucide-react';
import type { TurnFailure, TurnView } from '@shared/api.interface';
import { DismissButton, RecoverActions, useBoardOn, useRecentSaid } from './RecoverBits';
import { OLD_FAILURE_TITLE } from './recover';
import { splitTitle } from './topicText';
/* 话题页的一轮按聊天画（chatTurn.tsx，T623）；这里只剩没做完那一轮的原因和按钮 */

/** 没成功的一轮，历史里那行回答就是停止的原话（已在“技术详情”里）：不再当正文画一遍 */
export function stopWords(a: TurnView): boolean {
  const body: string = a.body.trim();
  return a.status === 'failed' && !!body && !!a.failure?.detail && a.failure.detail.includes(body.slice(0, 60));
}

/** 失败说明：一句人话（原因在第一行，能做什么在第二行）+ 按钮，内部用语折进“技术详情”。
 * 按钮照 v33 的 failure（labels、how、auto_retry）画，点了发 recover，和飞书任务卡上点同名按钮是同一件事（RecoverBits） */
export const FailBox: React.FC<{
  failure: TurnFailure | undefined;
  /** 这一轮（job_id 给 recover） */
  turn: Pick<TurnView, 'key' | 'job_id'>;
  /** 这一轮所在的话题（管家、负责人也行） */
  topicKey: string;
  actionable: boolean;
  /** 还在看板上（要你处理）才给「不管了」；看板不列了就没什么可拿掉 */
  pressing?: boolean;
  /** 旧数据（没有 how）时换个模型能不能在网页上换：普通话题能 */
  canSwitch?: boolean;
}> = ({ failure, turn, topicKey, actionable, pressing = true, canSwitch = true }) => {
  const board: boolean = useBoardOn();
  // 点过检查并继续、新的一轮已经开了：这一轮不再给按钮，点的结果还写在这里
  const said = useRecentSaid(topicKey, turn.job_id);
  if (!failure) {
    // 旧数据没有 failure：只说停住了，不编按钮
    return (
      <div className="a-oldfail">
        <p style={{ color: 'var(--fail)', fontSize: 12 }}>{OLD_FAILURE_TITLE}</p>
        {actionable ? <p className="t3" style={{ fontSize: 12 }}>在下面写一句话，会开始下一轮。</p> : null}
      </div>
    );
  }
  const [head, rest] = splitTitle(failure.title);
  return (
    <div className="a-fail" role="note">
      <AlertTriangle className="a-fic" />
      <div className="a-ft">
        <b>{head}</b>
        {rest ? <span className="a-frest">{rest}</span> : null}
        {failure.detail ? (
          <details>
            <summary>技术详情</summary>
            <code>{failure.detail}</code>
          </details>
        ) : null}
      </div>
      {actionable ? (
        <RecoverActions
          className="a-fb"
          failure={failure}
          topicKey={topicKey}
          jobId={turn.job_id}
          canSwitch={canSwitch}
          extra={pressing && board ? <DismissButton topicKey={topicKey} className="btn sm a-ghost" /> : null}
        />
      ) : said && !actionable ? (
        <span className={`rc-said${said.bad ? ' bad' : ''}`} role="status">{said.line}</span>
      ) : null}
    </div>
  );
};
