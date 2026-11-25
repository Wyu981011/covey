import React, { useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import type { UpgradeChange, UpgradeData } from '@shared/api.interface';
import { newOpId, useUpgrade } from '@client/src/hooks/use-workbench';
import { clock, shortTime } from '@client/src/lib/workbench-format';
import { useOutboxOp, type OutboxOp } from './sendOp';
import { useTick } from './ui';
import {
  canCheck,
  checkedLine,
  confirmWords,
  lastLine,
  moreChanges,
  runState,
  upgradeHeadline,
  versionLine,
  webLine,
} from './upgrade';
import './upgrade.css';

/* 设置页「更新」页签（数据约定 v39）：现网和最新的版本、更新内容、网页会不会跟着更新；「全部更新」把机器人和网页一起换成新版，
 * 「检查更新」叫 Covey 马上查一次。两颗按钮都发 upgrade 操作，按钮锁到回执（useOutboxOp），之后的进度看条目的 running、last。 */

const ChangeRow: React.FC<{ c: UpgradeChange }> = ({ c }) => (
  <li className="up-ch">
    <span className="up-sha short">{c.sha.slice(0, 8)}</span>
    <span className="up-subj">{c.subject || '（没有说明）'}</span>
    <span className="up-meta short">{c.repo}{c.at ? ` · ${shortTime(c.at)}` : ''}</span>
  </li>
);

const Tail: React.FC<{ lines: string[] }> = ({ lines }) => {
  const [open, setOpen] = useState<boolean>(false);
  if (!lines.length) return null;
  return (
    <div className="up-tail">
      <button type="button" className="st-link" aria-expanded={open} onClick={() => setOpen(!open)}>
        {open ? <ChevronDown /> : <ChevronRight />}升级输出最后 {lines.length} 行
      </button>
      {open ? <pre className="up-pre">{lines.join('\n')}</pre> : null}
    </div>
  );
};

const Buttons: React.FC<{ d: UpgradeData; run: OutboxOp; check: OutboxOp }> = ({ d, run, check }) => {
  const [asking, setAsking] = useState<boolean>(false);
  const go = runState(d);
  const busy: boolean = run.busy || check.busy;
  const confirm: string = confirmWords(d);
  if (asking) {
    return (
      <div className="up-confirm" role="group" aria-label="确认全部更新">
        <span className="up-cq">{confirm || '把机器人和网页换成最新版本？'}</span>
        <span className="up-acts">
          <button
            type="button"
            className="btn sm pri"
            disabled={busy || !go.ok}
            onClick={() => {
              setAsking(false);
              void run.run({ op_id: newOpId(), kind: 'upgrade', payload: { action: 'run' } });
            }}
          >
            确认更新
          </button>
          <button type="button" className="btn sm txt" onClick={() => setAsking(false)}>取消</button>
        </span>
      </div>
    );
  }
  return (
    <div className="up-acts">
      <button type="button" className="btn pri" disabled={busy || !go.ok} title="机器人和网页一起换成最新版本" onClick={() => setAsking(true)}>
        全部更新
      </button>
      <button
        type="button"
        className="btn"
        disabled={busy || !canCheck(d)}
        title="叫 Covey 马上查一次有没有新版本"
        onClick={() => void check.run({ op_id: newOpId(), kind: 'upgrade', payload: { action: 'check' } })}
      >
        检查更新
      </button>
      {!go.ok && go.why && !busy ? <span className="st-faint">{go.why}</span> : null}
    </div>
  );
};

export const UpgradePanel: React.FC = () => {
  const q = useUpgrade();
  const now: number = useTick(30000);
  const run: OutboxOp = useOutboxOp('upgrade:run');
  const check: OutboxOp = useOutboxOp('upgrade:check');
  const d: UpgradeData | undefined = q.data?.data;
  if (!d) return <p className="st-faint">{q.isLoading ? '读取中…' : 'Covey 还没推送版本信息'}</p>;
  const web: string = webLine(d);
  const last = lastLine(d, now);
  const checked: string = checkedLine(d, now);
  const more: number = moreChanges(d);
  const said: string = run.line || check.line;
  const saidBad: boolean = run.phase === 'failed' || run.phase === 'unsent' || check.phase === 'failed' || check.phase === 'unsent';
  return (
    <>
      <h3 className="st-h">版本与更新</h3>
      <div className="st-list">
        <div className="st-r up-head">
          <div className="up-hl">
            <span className={`up-big${d.available || d.running ? ' on' : ''}`}>{upgradeHeadline(d)}</span>
            {/* release 号里的连字符换成不断行的（U+2011），只在空格处换行 */}
            <span className="st-faint">{versionLine(d).replace(/-/g, '\u2011')}</span>
            {checked ? <span className="st-faint">{checked}</span> : null}
          </div>
          <Buttons d={d} run={run} check={check} />
          {said ? <div className={`st-rc${saidBad ? ' bad' : ''}`} role={saidBad ? 'alert' : 'status'}>{said}</div> : null}
          {d.error ? <div className="st-rc bad">上次检查没成功：{d.error}</div> : null}
          {d.blocked ? <div className="st-rc bad">现在不能更新：{d.blocked}</div> : null}
        </div>
        {d.running ? (
          <div className="st-r up-run">
            <div className="st-l">更新中</div>
            <div className="up-v">
              <span className="st-usev">{d.running.started_at ? `${clock(d.running.started_at)} 开始` : '已开始'}；机器人重启的几秒里网页连不上 Covey，是正常的</span>
              {d.running.log ? <span className="st-faint up-path">日志 {d.running.log}</span> : null}
            </div>
          </div>
        ) : null}
        {web ? (
          <div className="st-r">
            <div className="st-l">网页</div>
            <div className="up-v"><span className="st-usev">{web}</span></div>
          </div>
        ) : null}
        {last ? (
          <div className="st-r">
            <div className="st-l">上次更新</div>
            <div className="up-v">
              <span className={last.bad ? 'up-bad' : 'st-usev'}>{last.text}</span>
              {d.last?.log ? <span className="st-faint up-path">日志 {d.last.log}</span> : null}
              <Tail lines={d.last?.tail ?? []} />
            </div>
          </div>
        ) : null}
      </div>
      {d.changes.length ? (
        <>
          <h3 className="st-h">更新内容</h3>
          <ul className="st-list up-list">
            {d.changes.map((c: UpgradeChange) => <ChangeRow key={`${c.repo}:${c.sha}`} c={c} />)}
          </ul>
          {more ? <p className="st-note">还有 {more} 个更早的提交没列出</p> : null}
        </>
      ) : null}
      <p className="st-note">「全部更新」拉 Covey 和扩展的新代码，先预检，过了再换机器人，最后把网页换成同一版。在跑的任务由新进程接管，不会中断。</p>
    </>
  );
};
