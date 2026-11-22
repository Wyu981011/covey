import React, { useState } from 'react';
import { Check, ChevronDown, ChevronRight, Copy } from 'lucide-react';
import { toast } from 'sonner';
import type { TurnAnswer, TurnRanWith, TurnView } from '@shared/api.interface';
import { ArtifactFold } from './ArtifactFold';
import { Md } from './Md';
import { QuoteButton } from './RoomBits';
import { Waterfall } from './Waterfall';
import { Pill, useTick } from './ui';
import { ctxLimitOk, fmtDur, fmtTok, fmtWindow, hhmm, turnStats } from './lib';
import { isAnswerBody, saidLabel, shownText } from './topicText';
import { Notes, StartedChips } from './turnBits';
import { SentImages, ShownImages, withoutImageLine } from './TurnImages';

/* 一轮对话在大厅（管家、负责人）和话题页里画法一样（T623）：你说的是靠右的气泡，回答前一行是谁、几点，
   下面一颗“工具 N · 用时”点开是过程（瀑布和 token、速度、上下文），再是正文、产物（折叠，T645）、输入/输出两行、图。
   话题页只多一行“第 N 轮 → 结论”当目录。 */

/** 回答问题卡的那一句：问题 → 选择。bare 时不画自己的标题（在气泡里，标题是气泡那一行） */
export const AnswerTable: React.FC<{ answers: TurnAnswer[]; label?: string; bare?: boolean }> = ({ answers, label = '你的回答', bare }) => (
  <div className="a-blk">
    {bare ? null : <div className="a-bl">{label}（问题 → {label === '你的回答' ? '你的选择' : '选择'}）</div>}
    <table className="a-qa">
      <thead>
        <tr><th>问题</th><th aria-hidden="true" /><th>{label === '你的回答' ? '你的选择' : '选择'}</th></tr>
      </thead>
      <tbody>
        {answers.map((a: TurnAnswer, i: number) => (
          <tr key={i}>
            <td className="q"><span className="a-qq" title={a.question}>{a.question}</span></td>
            <td className="ar" aria-hidden="true">→</td>
            <td className={`a${a.choice === '没答' || a.choice === '跳过' ? ' skip' : ''}`}>{a.choice}</td>
          </tr>
        ))}
      </tbody>
    </table>
  </div>
);

const isAnswer = (o: TurnView): boolean => !!o.answers?.length || isAnswerBody(o.body);

/** 你说的一句（或负责人、管家替你说的）：靠右的气泡。答题的那句画成“问题 → 选择”的表，选项外写的字跟在下面；改过的能看原文 */
export const OwnerBubble: React.FC<{
  o: TurnView; answers?: TurnAnswer[] | null; hl?: boolean;
  /** 大厅（T624）：这句交给了谁（“→ 管家 → T12”），写在时间后面 */
  route?: React.ReactNode;
}> = ({ o, answers, hl, route }) => {
  const [raw, setRaw] = useState<boolean>(false);
  const answer: boolean = isAnswer(o);
  const qa: TurnAnswer[] | null = answer ? (o.answers?.length ? o.answers : answers ?? null) : null;
  const label: string | null = answer || (o.by && o.by !== 'owner') || o.via || o.edited ? saidLabel(o, answer) : null;
  return (
    <div className={`um${o.images?.length ? ' has-img' : ''}${qa ? ' has-qa' : ''}`} data-seq={o.seq} style={hl ? { boxShadow: '0 0 0 2px var(--wait)' } : undefined}>
      <div className="um-tx">
        {label ? (
          <span className="a-who">
            {label}
            {o.edited ? ' · 改过' : ''}
            {o.edited ? (
              <button type="button" className="a-x um-raw" onClick={() => setRaw(!raw)}>{raw ? '看改后的' : '看原文'}</button>
            ) : null}
          </span>
        ) : null}
        {raw ? (
          <div className="a-saytx">{o.body}</div>
        ) : qa ? (
          <>
            <AnswerTable answers={qa} label={saidLabel(o, true)} bare />
            {o.note ? <Md body={o.note} said /> : null}
          </>
        ) : (
          <Md body={withoutImageLine(shownText(o), o.images)} said />
        )}
      </div>
      <span className="tm">
        {hhmm(o.started_at)}
        {route ? <span className="rm-route"> {route}</span> : null}
      </span>
      {o.images?.length ? <SentImages images={o.images} /> : null}
    </div>
  );
};

/** 过程面板下面的数：token、速度、上下文 */
const Figures: React.FC<{ turn: TurnView }> = ({ turn }) => {
  if (!turn.usage && !turn.speed && !turn.context) return null;
  return (
    <div className="a-figs">
      {turn.usage ? (
        <span>
          token {fmtTok(turn.usage.total)}
          {turn.usage.input !== undefined ? ` · 输入 ${fmtTok(turn.usage.input)}` : ''}
          {turn.usage.input !== undefined && turn.usage.cache_read ? `（其中缓存 ${fmtTok(turn.usage.cache_read)}）` : ''}
          {turn.usage.output !== undefined ? ` · 输出 ${fmtTok(turn.usage.output)}` : ''}
        </span>
      ) : null}
      {turn.speed ? <span>速度 {Math.round(turn.speed)} token/s</span> : null}
      {turn.context ? (
        <span>
          上下文 {fmtTok(turn.context.used)}
          {ctxLimitOk(turn.context) ? ` / ${fmtWindow(turn.context.limit)}（${Math.round((turn.context.used / turn.context.limit) * 100)}%）` : ''}
        </span>
      ) : null}
    </div>
  );
};

/** 复制一段字：先用剪贴板接口，嵌在飞书里拿不到时退回选中再复制 */
async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    // 落到下面的老办法
  }
  try {
    const area: HTMLTextAreaElement = document.createElement('textarea');
    area.value = text;
    area.setAttribute('readonly', '');
    area.style.position = 'fixed';
    area.style.opacity = '0';
    document.body.appendChild(area);
    area.select();
    const ok: boolean = document.execCommand('copy');
    area.remove();
    return ok;
  } catch {
    return false;
  }
}

/** 回答下面一行的“输入”：Harness ｜ 供应商 ｜ 模型 ｜ 思考 ｜ 脱敏 ｜ 工作区（v27 ran_with，没有的不写） */
export function inputBits(r: TurnRanWith | undefined): string[] {
  if (!r) return [];
  return [r.harness, r.provider, r.model, r.effort ? `思考 ${r.effort}` : '', r.redaction ? (r.redaction === 'on' ? '脱敏开' : '脱敏关') : '', r.workspace]
    .filter((x): x is string => !!x);
}

/** “输出”：用时 ｜ 速度 ｜ token ｜ 缓存命中（缓存读到的占输入的几成） */
export function outputBits(t: TurnView): string[] {
  const out: string[] = [];
  const secs: number | null | undefined = turnStats(t)?.seconds ?? t.seconds;
  if (secs) out.push(`用时 ${fmtDur(secs)}`);
  if (t.speed) out.push(`${Math.round(t.speed)} token/s`);
  if (t.usage?.total) out.push(`token ${fmtTok(t.usage.total)}`);
  const input: number = t.usage?.input ?? 0;
  if (input > 0 && t.usage?.cache_read !== undefined) out.push(`缓存命中 ${((t.usage.cache_read / input) * 100).toFixed(1)}%`);
  return out;
}

/** 回答下面两行（像 Codex，和飞书答案卡一样）：输入（用的什么配置）、输出（用了多久、多少 token），各占一行、两个字左对齐；
 *  复制正文放在最后一行的末尾（T645：放在最前面时把“输入”挤到右边，和下一行的“输出”错开了） */
export const AnswerFoot: React.FC<{ turn: TurnView }> = ({ turn }) => {
  const [done, setDone] = useState<boolean>(false);
  const rows: { label: string; tip: string; bits: string[] }[] = [
    { label: '输入', tip: '这一轮用的配置', bits: inputBits(turn.ran_with) },
    { label: '输出', tip: '这一轮的用时和用量', bits: outputBits(turn) },
  ].filter((r) => r.bits.length > 0);
  const copy = (): void => {
    void copyText(turn.body).then((ok: boolean) => {
      if (!ok) {
        toast.error('没复制上，请手动选中');
        return;
      }
      setDone(true);
      window.setTimeout(() => setDone(false), 1500);
    });
  };
  const button: React.ReactNode = (
    <button type="button" className="afoot-copy" onClick={copy} title="复制这条回答" aria-label="复制这条回答">
      {done ? <Check /> : <Copy />}
      <span>{done ? '已复制' : '复制'}</span>
    </button>
  );
  return (
    <div className="afoot">
      {rows.map((r, i: number) => (
        <div className="afoot-row" key={r.label}>
          <b>{r.label}</b>
          <span className="afoot-bits">
            {r.bits.map((x: string, j: number) => <span key={j} title={r.tip}>{x}</span>)}
            {i === rows.length - 1 ? button : null}
          </span>
        </div>
      ))}
      {rows.length ? null : <div className="afoot-row">{button}</div>}
    </div>
  );
};

/** 回答的那一轮：谁、几点 → 工具（点开是过程）→ 正文 → 图、说明、开的话题、产物 → 没做完时的那一块 */
export const AgentTurn: React.FC<{
  turn: TurnView;
  hl: boolean;
  who: string;
  /** 头像：不给就是名字的第一个字 */
  avatar?: React.ReactNode;
  /** 没做完时画在最后的（话题页是原因和按钮）；不给就是一行字 */
  fail?: React.ReactNode;
  /** 这一轮的正文不画（话题页：停止时只有一句“已停止”） */
  hideBody?: boolean;
  /** 大厅（T624）：名字旁的“引用”，和选中一段时认出是哪一条 */
  onQuote?: () => void;
  roomKey?: string;
}> = ({ turn, hl, who, avatar, fail, hideBody, onQuote, roomKey }) => {
  const live: boolean = turn.status === 'running';
  const now: number = useTick(live ? 1000 : 3600000);
  const [open, setOpen] = useState<boolean>(false);
  const st = turnStats(turn);
  const elapsed: number | null = live && turn.started_at ? now - turn.started_at : (st?.seconds ?? turn.seconds ?? null);
  const hasFigs: boolean = !!(turn.usage || turn.speed || turn.context);
  const chip: boolean = !live && !!(st || hasFigs);
  const showFall: boolean = (live && !!turn.steps?.length) || (open && (!!turn.steps?.length || hasFigs));
  const ring: React.CSSProperties = hl ? { boxShadow: '0 0 0 2px var(--wait)', borderRadius: 10 } : {};
  return (
    <div className="msg" data-seq={turn.seq} data-room-key={roomKey} style={ring}>
      <div className="who">
        {avatar ?? <span className="avc">{who.slice(0, 1)}</span>}
        <b>{who}</b>
        <span>{hhmm(turn.ended_at || turn.started_at)}</span>
        {live ? <Pill tone="running" /> : null}
        {onQuote && !live ? <QuoteButton onClick={onQuote} /> : null}
      </div>
      {chip ? (
        <button type="button" className="fold" onClick={() => setOpen(!open)} aria-expanded={open} style={{ border: 0, cursor: 'pointer' }}>
          {open ? <ChevronDown /> : <ChevronRight />}
          {st ? <>工具 {st.tools}{st.thinks ? ` · 思考 ${st.thinks}` : ''}</> : '过程'}
          {elapsed ? ` · ${fmtDur(elapsed)}` : ''}
        </button>
      ) : null}
      {showFall ? (
        <div className="wfc">
          <div className="wh">
            <b>过程</b>
            <span className="t3">{live ? `本轮 ${fmtDur(elapsed)}` : ''}</span>
            <span className="sp" />
            {st ? <span className="t3">工具 {st.tools}{st.thinks ? ` · 思考 ${st.thinks}` : ''}</span> : null}
          </div>
          {turn.steps?.length ? <Waterfall steps={turn.steps} live={live} /> : null}
          {live ? null : <Figures turn={turn} />}
        </div>
      ) : null}
      {/* 在做的那一轮不显示模型中途的过程话（常是英文的半句），做完才显示结论 */}
      {turn.body && !live && !hideBody ? <Md body={turn.body} dim={false} /> : null}
      {live ? null : <ArtifactFold items={turn.artifacts} />}
      {!live && turn.body && !hideBody ? <AnswerFoot turn={turn} /> : null}
      {turn.images?.length ? <ShownImages images={turn.images} /> : null}
      {live ? (
        <div className="typing">
          <span className="dots"><i /><i /><i /></span>
          {turn.steps?.length ? '正在做' : '在做…'}
        </div>
      ) : null}
      {turn.notes?.length ? <Notes notes={turn.notes} /> : null}
      {turn.started_topics?.length ? <StartedChips items={turn.started_topics} /> : null}
      {turn.status === 'failed' ? fail ?? <p style={{ color: 'var(--fail)', fontSize: 12 }}>这一轮失败了</p> : null}
      {turn.status === 'stopped' ? <p className="t3" style={{ fontSize: 12 }}>这一轮被停止了</p> : null}
    </div>
  );
};

/** 一轮：你说的几句（气泡）和回答 */
export const ChatRound: React.FC<{
  owner: TurnView[];
  agent: TurnView | null;
  hl: number | null;
  who: string;
  avatar?: React.ReactNode;
  fail?: React.ReactNode;
  hideBody?: boolean;
}> = ({ owner, agent, hl, who, avatar, fail, hideBody }) => (
  <>
    {owner.map((o: TurnView) => (
      <OwnerBubble key={o.key} o={o} answers={agent?.answers} hl={hl === o.seq} />
    ))}
    {agent ? <AgentTurn turn={agent} hl={hl === agent.seq} who={who} avatar={avatar} fail={fail} hideBody={hideBody} /> : null}
  </>
);
