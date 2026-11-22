import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { ChevronDown, ChevronRight, CornerUpLeft, ExternalLink, Square } from 'lucide-react';
import type { CollabEvidence, CollabView, SnapshotResponse, TurnView } from '@shared/api.interface';
import { DONE, CANCELLED, TOPIC, stoppable } from '@shared/collab';
import { newOpId } from '@client/src/hooks/use-workbench';
import { Md } from './Md';
import { hhmm, type ToneKey } from './lib';
import { Pill } from './ui';
import { askLines, collabHead, collabHref, mentionInfo, participantOf, nameOf, type AskLine, type QuoteRef, type Receipt } from './collab';
import { Who } from './RoomBits';
import { sendAndWait } from './sendOp';
import './collab.css';

/* 协作往返（汇总方的话题页、大厅）和协助方的回执（协助方的话题页），包 E，docs/web.md 协作与三层记忆 */

const ASK_TONE: Record<string, ToneKey> = {
  checking: 'queued', queued: 'queued', taken: 'running', replied: 'done', read: 'done',
  not_taken: 'stopped', failed: 'stopped', expired: 'stopped', cancelled: 'cancelled',
};
const collabTone = (state: string): ToneKey => (state === DONE ? 'done' : state === CANCELLED ? 'cancelled' : 'running');

/** 去一个话题的那一轮：普通话题去话题页（带 seq），管家、负责人在大厅 */
function turnHref(key: string, seq: number | undefined, snap: SnapshotResponse | undefined, butler: string | null): string {
  const who = participantOf(key, snap, butler);
  if (who.role !== TOPIC) return '/butler';
  return `/topics/${encodeURIComponent(key)}${seq ? `?seq=${seq}` : ''}`;
}

/** 一条证据：一小块，外链能点开，带出处的点过去看那一轮 */
const Evidence: React.FC<{ e: CollabEvidence; snap: SnapshotResponse | undefined; butler: string | null }> = ({ e, snap, butler }) => (
  <li className="cb-evi">
    {e.link ? (
      <a href={e.link} target="_blank" rel="noreferrer">{e.text}<ExternalLink /></a>
    ) : (
      <span>{e.text}</span>
    )}
    {e.topic_key ? (
      <Link className="cb-src" to={turnHref(e.topic_key, e.seq, snap, butler)}>
        {nameOf(e.topic_key, snap, butler)}{e.seq ? ` 第 ${e.seq} 轮` : ''}
      </Link>
    ) : null}
  </li>
);

/** 一位的头像（话题是 T 号，管家、负责人带名字） */
const WhoKey: React.FC<{ k: string; snap: SnapshotResponse | undefined; butler: string | null }> = ({ k, snap, butler }) => <Who info={mentionInfo(k, snap, butler)} />;

const AskRow: React.FC<{
  l: AskLine; snap: SnapshotResponse | undefined; butler: string | null; onQuote?: (l: AskLine) => void;
}> = ({ l, snap, butler, onQuote }) => {
  const reply = l.ask.reply;
  return (
    <li className={`cb-ask${l.live ? ' is-live' : ''}`} data-ask={l.id}>
      <div className="cb-line">
        <b className="cb-dir" aria-label={`${l.from} 问 ${l.to}`}><WhoKey k={l.fromKey} snap={snap} butler={butler} /> → <WhoKey k={l.toKey} snap={snap} butler={butler} /></b>
        <span className="cb-what">{l.what}</span>
        <Pill tone={ASK_TONE[l.state] ?? 'idle'} text={l.word} />
        <span className="sp" />
        {onQuote && (reply || l.text) ? (
          <button type="button" className="rm-act" onClick={() => onQuote(l)} title="引用这句：话进这次协作，由它的汇总方接">
            <CornerUpLeft />引用
          </button>
        ) : null}
      </div>
      {l.text ? <div className="cb-q">{l.text}</div> : null}
      {l.ask.reason && !reply ? <div className="cb-why" data-testid="ask-reason">原因：{l.ask.reason}</div> : null}
      {l.ask.late ? <div className="cb-late">迟到的答复（只留档，不再叫醒谁）：{l.ask.late.text}</div> : null}
      {reply ? (
        <div className="cb-reply">
          <div className="cb-rwho"><WhoKey k={l.toKey} snap={snap} butler={butler} /> 答 <WhoKey k={l.fromKey} snap={snap} butler={butler} /></div>
          {reply.text ? <Md body={reply.text} dim={false} /> : null}
          {reply.evidence.length ? (
            <div className="cb-evrow">
              <span className="cb-evl">证据</span>
              <ul className="cb-ev" aria-label="证据">
                {reply.evidence.map((e: CollabEvidence, i: number) => <Evidence key={i} e={e} snap={snap} butler={butler} />)}
              </ul>
            </div>
          ) : null}
          {reply.topic_key || reply.at ? (
            <div className="cb-meta">
              {reply.topic_key ? (
                <Link to={turnHref(reply.topic_key, reply.seq, snap, butler)}>出处 {nameOf(reply.topic_key, snap, butler)}{reply.seq ? ` 第 ${reply.seq} 轮` : ''}</Link>
              ) : null}
              {reply.at ? <span>核查于 {hhmm(reply.at)}</span> : null}
            </div>
          ) : null}
        </div>
      ) : null}
    </li>
  );
};

/** ▾ 协作往返：谁汇总、谁协助、每次咨询和澄清（谁问谁、状态、问的话、答复、证据和出处）；开着、有排队或在跑的咨询时能停 */
export const CollabBlock: React.FC<{
  c: CollabView | undefined;
  seq: number;
  snap: SnapshotResponse | undefined;
  butler: string | null;
  /** 链接里的 ?collab= 指着它：展开、闪一下 */
  focus?: boolean;
  onQuote?: (q: QuoteRef) => void;
}> = ({ c, seq, snap, butler, focus = false, onQuote }) => {
  const [open, setOpen] = useState<boolean>(() => focus || c?.state === 'open');
  const [stopping, setStopping] = useState<boolean>(false);
  useEffect(() => {
    if (focus) setOpen(true);
  }, [focus]);
  if (!c) return null;
  const head = collabHead(c, snap, butler);
  const lines: AskLine[] = askLines(c, snap, butler);
  const canStop: boolean = stoppable(c);
  const stop = async (): Promise<void> => {
    setStopping(true);
    // 只停这次协作排队和在跑的咨询轮，汇总方和协助方别的工作不动（stop 带 payload.collab）
    await sendAndWait({ op_id: newOpId(), kind: 'stop', topic_key: c.integrator, payload: { collab: c.key } }, '已发出：停止本次协作');
    setStopping(false);
  };
  const quote = (l: AskLine): void => onQuote?.({
    key: `ask-${l.id}`, topic_key: l.ask.reply?.topic_key ?? l.ask.to, ...(l.ask.reply?.seq ? { seq: l.ask.reply.seq } : {}), collab: c.key,
    who: `${l.ask.reply ? l.to : l.from}（协作往返）`, text: l.ask.reply?.text || l.text,
  });
  return (
    <div className={`cb${open ? ' open' : ''}${focus ? ' hl' : ''}`} data-seq={seq} data-collab={c.key} data-testid="collab-block">
      <div className="cb-top">
        <button type="button" className="cb-head" onClick={() => setOpen(!open)} aria-expanded={open}>
          {open ? <ChevronDown /> : <ChevronRight />}
          <b>协作往返</b>
          <span className="cb-who" title={`由 ${head.integrator} 汇总${head.helpers.length ? ` · 协助 ${head.helpers.join('、')}` : ''}`}>
            由 <WhoKey k={c.integrator} snap={snap} butler={butler} /> 汇总
            {c.helpers.length ? <> · 协助 {c.helpers.map((k: string) => <WhoKey key={k} k={k} snap={snap} butler={butler} />)}</> : null}
          </span>
          <Pill tone={collabTone(c.state)} text={head.word} />
          <span className="t3 cb-n">{head.asks ? `${head.replied}/${head.asks} 已答复` : '还没发出咨询'}</span>
        </button>
        {canStop ? (
          <button type="button" className="btn sm cb-stop" onClick={() => void stop()} disabled={stopping} title="只停这次协作排队和在跑的咨询，大家别的工作不动">
            <Square />{stopping ? '停止中…' : '停止本次协作'}
          </button>
        ) : null}
      </div>
      {open ? (
        lines.length ? (
          <ol className="cb-asks">
            {lines.map((l: AskLine) => <AskRow key={l.id} l={l} snap={snap} butler={butler} onQuote={onQuote ? quote : undefined} />)}
          </ol>
        ) : (
          <p className="t3 cb-none">{c.state === 'open' ? '汇总方还在准备要问的话。' : '这次没有发出咨询。'}</p>
        )
      ) : null}
    </div>
  );
};

const PHASE_WORD: Record<Receipt['phase'], string> = { done: '已协助', live: '正在协助', off: '没接手' };

/** 协助方话题里的一行回执：“已协助 T3（看这次协作）”，能去看这次协作、回复这次协作，点开看汇总方问的和自己答的；不当这个话题自己的一轮 */
export const CollabReceipt: React.FC<{
  r: Receipt;
  rows: TurnView[];
  c: CollabView | undefined;
  snap: SnapshotResponse | undefined;
  butler: string | null;
  onReply: () => void;
}> = ({ r, rows, c, snap, butler, onReply }) => {
  const [open, setOpen] = useState<boolean>(false);
  const said: string = rows.find((t: TurnView) => t.role === 'event')?.body ?? '';
  const title: React.ReactNode = r.name && r.integrator
    ? <>{PHASE_WORD[r.phase]} <WhoKey k={r.integrator} snap={snap} butler={butler} /></>
    : r.name ? `${PHASE_WORD[r.phase]} ${r.name}` : said || PHASE_WORD[r.phase];
  return (
    <div className={`cb-rcpt ph-${r.phase}`} data-seq={r.seq || undefined} data-collab={r.collab} data-testid="collab-receipt">
      <div className="cb-rline">
        <span className={`cb-dot ph-${r.phase}`} />
        <b>{title}</b>
        {r.word ? <span className="t3">{r.word}</span> : null}
        {r.reason && r.phase === 'off' ? <span className="cb-why" data-testid="receipt-reason">{r.reason}</span> : null}
        <span className="sp" />
        {c ? <Link className="rm-act" to={collabHref(c, snap, butler)}>看这次协作 ›</Link> : null}
        {c ? (
          <button type="button" className="rm-act" onClick={onReply} title="话进这次协作，由它的汇总方接">
            <CornerUpLeft />回复这次协作
          </button>
        ) : null}
        {r.asked || r.answer ? (
          <button type="button" className="rm-act" onClick={() => setOpen(!open)} aria-expanded={open}>{open ? '收起' : '问了什么、答了什么'}</button>
        ) : null}
      </div>
      {open ? (
        <div className="cb-rbody">
          {r.asked ? <div className="cb-q"><b>{r.name || '汇总方'} 问：</b>{r.asked}</div> : null}
          {r.answer ? <Md body={r.answer} dim={false} /> : <p className="t3">还没答。</p>}
        </div>
      ) : null}
    </div>
  );
};
