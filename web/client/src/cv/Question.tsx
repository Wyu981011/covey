import React, { useState } from 'react';
import { ChevronDown, ChevronRight, CircleHelp } from 'lucide-react';
import { useIsDesktop } from '@client/src/hooks/use-breakpoint';
import type { OutboxView, QuestionItem, QuestionOption, QuestionView } from '@shared/api.interface';
import { newOpId, useSendOutbox } from '@client/src/hooks/use-workbench';
import { errorText } from '@client/src/lib/workbench-format';
import { SEND_KEY } from './composerText';

const REC = /[（(]?推荐[）)]?/u;
export const isRec = (o: QuestionOption): boolean => REC.test(o.label);
export const cleanLabel = (o: QuestionOption): string => o.label.replace(/\s*[（(]推荐[）)]\s*/u, '').trim() || o.label;

/** 单选、有选项、只有一道：看板上点选项就能答 */
export const quickAnswerable = (q: QuestionView): boolean =>
  q.questions.length === 1 && !q.questions[0].multiple && q.questions[0].options.length > 0;

/** 一道题的回答：选项原文（多选是列表）、自己写的字，或 {skip: true}（不回答此题，Covey v20） */
export type AnswerValue = string | string[] | { skip: true };
/** 一次动作是哪一种：提交回答、不处理、撤销不处理、停止 */
export type QuestionAct = 'answer' | 'aside' | 'restore' | 'stop';

/** 发出一条动作；结果（已发出 → 已执行 / 失败）由对话里的 OpStatus 从 outbox 行读出，这里只管发。发请求本身失败时写进 error。 */
export function useAnswer(topicKey: string): {
  send: (q: QuestionView, answers: Record<string, AnswerValue>, note?: string) => void;
  aside: (q: QuestionView) => void;
  restore: (q: QuestionView) => void;
  stop: () => void;
  pending: boolean;
  error: string;
  opId: string;
  act: QuestionAct | '';
} {
  const m = useSendOutbox();
  const [error, setError] = useState<string>('');
  const [opId, setOpId] = useState<string>('');
  const [act, setAct] = useState<QuestionAct | ''>('');
  const fire = (what: QuestionAct, payload: Record<string, unknown>): void => {
    setError('');
    const id: string = newOpId();
    setOpId(id);
    setAct(what);
    m.mutate({ op_id: id, kind: what === 'stop' ? 'stop' : 'answer', topic_key: topicKey, payload }, { onError: (e: Error) => setError(errorText(e)) });
  };
  return {
    pending: m.isPending,
    error,
    opId,
    act,
    send: (q: QuestionView, answers: Record<string, AnswerValue>, note = ''): void =>
      fire('answer', { token: q.token, answers, note: note.trim() }),
    aside: (q: QuestionView): void => fire('aside', { token: q.token, aside: true }),
    restore: (q: QuestionView): void => fire('restore', { token: q.token, restore: true }),
    stop: (): void => fire('stop', {}),
  };
}

/** 一道题现在的选择：点的选项、自己写的字、不回答此题、是不是点开了“都不合适，自己写” */
export interface Choice {
  picked: string[];
  typed: string;
  skip: boolean;
  other: boolean;
}
const NONE: Choice = { picked: [], typed: '', skip: false, other: false };

/**
 * 一张问题的回答，和飞书问题卡对齐：
 * - 每道题：点选项；选项都不合适时“都不合适，自己写”；不想答选“不回答此题”。三样互斥。
 * - 只有一道题：底部输入框就是这道题的回答框。没点选项时写的字是“自己写的回答”，点了选项或“不回答此题”时写的字是随回答带上的补充说明。
 * - 几道题：自己写的回答在面板里各有一个框；底部输入框写的是补充说明。写了补充说明，没处理的题算“不回答此题”（不是同意），
 *   只写补充说明就是题都不答（说问题不合适、给新要求、想先问一句都写这里）；没写时每题都处理了才能提交。
 * - 按钮只有“提交回答”和“不处理”（先放下，话题下一轮前可撤销），同飞书问题卡（T631，Covey v29）。
 */
export interface QuestionForm {
  question: QuestionView | null;
  /** 只有一道题：底部输入框就是它的回答框 */
  single: boolean;
  choices: Record<string, Choice>;
  choice: (q: QuestionItem) => Choice;
  pick: (q: QuestionItem, o: QuestionOption) => void;
  type: (q: QuestionItem, v: string) => void;
  /** 不回答此题（再点一次取消） */
  skipOne: (q: QuestionItem) => void;
  /** 都不合适，自己写（再点一次取消） */
  writeOwn: (q: QuestionItem) => void;
  /** 这道题处理了没有（几道题时；只有一道题时底部输入框的字也算） */
  answered: (q: QuestionItem, text?: string) => boolean;
  /** 底部输入框有 text 时，能不能提交回答（几道题时写了补充说明就能交，没处理的题算不回答） */
  complete: (text: string) => boolean;
  /** 还没处理的题数（几道题时；底部输入框的字不算） */
  missing: number;
  submit: (text: string) => void;
  aside: () => void;
  restore: () => void;
  stop: () => void;
  /** 最近这次动作是哪一种 */
  act: QuestionAct | '';
  phase: 'idle' | 'sent' | 'done' | 'failed';
  failedMsg: string;
  locked: boolean;
  pending: boolean;
  /** 几道题没答完就按了 Enter：面板上标出没答的题 */
  nudged: boolean;
  nudge: () => void;
}

const free = (q: QuestionItem): boolean => q.options.length === 0;

export function useQuestionForm(topicKey: string, question: QuestionView | null, ops: OutboxView[] = []): QuestionForm {
  const token: string = question?.token ?? '';
  const [state, setState] = useState<{ token: string; choices: Record<string, Choice>; nudged: boolean }>({ token, choices: {}, nudged: false });
  // 换了一张题：选过的、写过的都清掉
  const cur = state.token === token ? state : { token, choices: {}, nudged: false };
  const ans = useAnswer(topicKey);
  const [askedFor, setAskedFor] = useState<string>('');
  const opId: string = askedFor === token ? ans.opId : '';
  const row: OutboxView | undefined = opId ? ops.find((o: OutboxView) => o.op_id === opId) : undefined;
  const failedMsg: string = opId && ans.error ? ans.error : row?.state === 'failed' ? row.message || '没有成功' : '';
  const phase: QuestionForm['phase'] = !opId ? 'idle' : failedMsg ? 'failed' : row?.state === 'done' ? 'done' : 'sent';
  // 动作发出后锁住，等页面更新
  const closing: boolean = askedFor === token;
  const locked: boolean = (closing && (phase === 'sent' || phase === 'done')) || (ans.pending && askedFor === token);
  const items: QuestionItem[] = question?.questions ?? [];
  const single: boolean = items.length === 1;
  const choice = (q: QuestionItem): Choice => cur.choices[q.id] ?? NONE;
  const set = (q: QuestionItem, c: Choice): void => setState({ ...cur, choices: { ...cur.choices, [q.id]: c } });
  const answered = (q: QuestionItem, text = ''): boolean => {
    const c: Choice = choice(q);
    if (c.skip || c.picked.length) return true;
    return single ? text.trim().length > 0 : c.typed.trim().length > 0;
  };
  const missing: number = single ? 0 : items.filter((q: QuestionItem) => !answered(q)).length;
  const complete = (text: string): boolean => {
    if (!question || !items.length) return false;
    if (single) return answered(items[0], text);
    return missing === 0 || text.trim().length > 0;
  };
  const fire = (f: () => void): void => {
    setAskedFor(token);
    f();
    setState({ token, choices: {}, nudged: false });
  };
  const value = (q: QuestionItem): AnswerValue => {
    const c: Choice = choice(q);
    if (c.skip) return { skip: true };
    if (!c.picked.length) return c.typed.trim();
    return q.multiple ? c.picked : c.picked[0];
  };
  return {
    question,
    single,
    choices: cur.choices,
    choice,
    pick: (q: QuestionItem, o: QuestionOption): void => {
      const now: string[] = choice(q).picked;
      const on: boolean = now.includes(o.label);
      const next: string[] = q.multiple ? (on ? now.filter((x: string) => x !== o.label) : [...now, o.label]) : on ? [] : [o.label];
      set(q, { ...NONE, picked: next });
    },
    type: (q: QuestionItem, v: string): void => set(q, { ...NONE, other: !free(q), typed: v }),
    skipOne: (q: QuestionItem): void => set(q, choice(q).skip ? NONE : { ...NONE, skip: true }),
    writeOwn: (q: QuestionItem): void => set(q, choice(q).other ? NONE : { ...NONE, other: true }),
    answered,
    complete,
    missing,
    submit: (text: string): void => {
      if (!question || !complete(text)) return;
      const note: string = text.trim();
      const answers: Record<string, AnswerValue> = {};
      if (single) {
        const q: QuestionItem = items[0];
        const c: Choice = choice(q);
        if (!c.skip && !c.picked.length) {
          // 没点选项：底部写的字就是回答（不是选项原文的字，Covey 当作写的回答，同飞书卡上的回答框）
          answers[q.id] = note;
          fire(() => ans.send(question, answers, ''));
          return;
        }
        answers[q.id] = value(q);
        fire(() => ans.send(question, answers, note));
        return;
      }
      // 写了补充说明：没处理的题明说“不回答此题”（Covey v20 就认，v29 不写也算）
      for (const q of items) answers[q.id] = answered(q) ? value(q) : { skip: true };
      fire(() => ans.send(question, answers, note));
    },
    aside: (): void => {
      if (!question) return;
      setAskedFor(token);
      ans.aside(question);
    },
    restore: (): void => {
      if (!question) return;
      setAskedFor(token);
      ans.restore(question);
    },
    stop: (): void => {
      setAskedFor(token);
      ans.stop();
    },
    act: askedFor === token ? ans.act : '',
    phase,
    failedMsg,
    locked,
    pending: ans.pending,
    nudged: cur.nudged,
    nudge: (): void => setState({ ...cur, nudged: true }),
  };
}

/** 有题在等时，底部输入框的占位文字和下面那行小字 */
export function composerWords(form: QuestionForm, text: string): { placeholder: string; hint: string } {
  const q: QuestionView | null = form.question;
  const enter = `${SEND_KEY} 提交回答 · Enter 换行`;
  if (!q || !q.questions.length) return { placeholder: '写你的回答', hint: enter };
  if (form.single) {
    const item: QuestionItem = q.questions[0];
    const c: Choice = form.choice(item);
    if (c.skip) return { placeholder: '这道题不回答；可以补一句原因（可不写），随提交一起发出', hint: enter };
    if (c.picked.length) return { placeholder: '补一句（可不写），随回答一起发出', hint: enter };
    if (free(item) || c.other) return { placeholder: '写你的回答', hint: enter };
    return { placeholder: '点上面的选项，或在这里直接写你的回答', hint: enter };
  }
  const written: boolean = text.trim().length > 0;
  return {
    placeholder: '答上面的题，或在这里写补充说明（不答的原因、新要求、想先问的话）',
    hint: !form.missing
      ? written ? `${SEND_KEY} 提交回答，这句作为补充说明一起发出` : enter
      : written
        ? `${SEND_KEY} 提交回答：没处理的 ${form.missing} 题算不回答，这句作为补充说明`
        : `还差 ${form.missing} 题没处理 · 答完或写上补充说明后 ${SEND_KEY} 提交回答`,
  };
}

const SKIP_LABEL = '不回答此题';
const OWN_LABEL = '都不合适，自己写';
const ASIDE_TIP = '先不管这组题：每题记为不回答，从“等你”里撤下，话题下一轮开始时告诉模型；在那之前可以撤销';

const hm = (at: number | null | undefined): string => {
  if (!at) return '';
  const d = new Date(at * 1000);
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')} `;
};

/** 选项下面那一行小按钮：都不合适自己写、不回答此题（比选项次要，选中时和选项一样描边） */
const Lesser: React.FC<{ on: boolean; label: string; disabled: boolean; onClick: () => void }> = ({ on, label, disabled, onClick }) => (
  <button
    type="button"
    disabled={disabled}
    aria-pressed={on}
    className="btn sm"
    style={on ? { borderColor: 'var(--a1)', color: 'var(--t1)', background: 'color-mix(in srgb,var(--a1) 10%,var(--s1))' } : { color: 'var(--t2)' }}
    onClick={onClick}
  >
    {on ? '✓ ' : ''}
    {label}
  </button>
);

/** 话题页里的问题面板：编号选项、推荐标、背景，每题可以自己写或不回答；底下是提交回答、不处理和停止这个话题。 */
export const QuestionPanel: React.FC<{ form: QuestionForm; text: string; onWrite: () => void }> = ({ form, text, onWrite }) => {
  const desktop: boolean = useIsDesktop();
  const [folded, setFolded] = useState<boolean>(false);
  const [confirmStop, setConfirmStop] = useState<boolean>(false);
  const question: QuestionView | null = form.question;
  if (!question) return null;
  if (question.state !== 'open') return <AsidePanel form={form} />;
  const locked: boolean = form.locked;
  const can: boolean = form.complete(text) && !locked;
  const written: boolean = text.trim().length > 0;
  if (folded) {
    return (
      <button type="button" className="qc" aria-expanded="false" onClick={() => setFolded(false)} style={{ display: 'flex', alignItems: 'center', gap: 8, width: '100%', cursor: 'pointer', color: 'var(--wait)', fontSize: 12, textAlign: 'left' }}>
        <CircleHelp style={{ width: 14, height: 14 }} />
        <span>等你 · 要你定 · 展开</span>
        <span className="t3" style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{question.questions[0]?.question ?? ''}</span>
        <ChevronRight style={{ width: 14, height: 14 }} />
      </button>
    );
  }
  const only: QuestionItem | undefined = form.single ? question.questions[0] : undefined;
  const oc: Choice | undefined = only ? form.choice(only) : undefined;
  const guide: string = only && oc
    ? oc.skip
      ? `这道题记为不回答（不表示同意）；下面的输入框可以写原因，提交时一起发出。`
      : oc.picked.length
        ? '下面的输入框可以补一句，随回答一起发出。'
        : free(only) || oc.other
          ? `在下面的输入框写你的回答，${SEND_KEY} 提交。`
          : `点一个选项再提交；都不合适或有疑问，就在下面的输入框直接写；不想答选“${SKIP_LABEL}”。`
    : `每题选一个、自己写或选“${SKIP_LABEL}”${form.missing ? `（还差 ${form.missing} 题）` : ''}；下面的输入框写的话作为补充说明一起发出，写了补充说明时没处理的题算不回答。`;
  return (
    <div className="qc" aria-label="等你 · 要你定" style={desktop ? undefined : { maxHeight: '55vh', overflowY: 'auto' }}>
      <div className="qh">
        <CircleHelp />
        等你 · 要你定
        {question.questions.length > 1 ? <span className="t3">· {question.questions.length} 道题</span> : null}
        <span style={{ flex: 1 }} />
        <button type="button" aria-expanded="true" aria-label="收起问题" onClick={() => setFolded(true)} style={{ display: 'inline-flex', alignItems: 'center', gap: 2, background: 'none', border: 0, cursor: 'pointer', color: 'inherit', fontSize: 12 }}>
          收起 <ChevronDown style={{ width: 13, height: 13 }} />
        </button>
      </div>
      {question.questions.map((q: QuestionItem, qi: number) => {
        const c: Choice = form.choice(q);
        const flag: boolean = form.nudged && !form.single && !form.answered(q);
        const box: boolean = !form.single && !c.skip && (free(q) || c.other);
        // 自己写的回答框：没有选项的题在“不回答此题”上面，有选项的题在下面
        const answerBox: React.ReactNode = box ? (
              <textarea
                className="qa"
                rows={2}
                disabled={locked}
                value={c.typed}
                onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) => form.type(q, e.target.value)}
                placeholder={free(q) ? '这道题的回答' : '选项都不合适时，在这里写你的回答'}
                aria-label={`第 ${qi + 1} 题的回答`}
                style={{ marginTop: free(q) ? 0 : 6, ...(flag ? { borderColor: 'var(--wait)' } : {}) }}
              />
        ) : null;
        return (
          <div key={q.id} data-missing={flag ? '1' : undefined} style={{ marginBottom: 8 }}>
            {q.header ? <div className="mini-note">{q.header}</div> : null}
            <div className="qt" style={{ whiteSpace: 'pre-wrap' }}>
              {question.questions.length > 1 ? `${qi + 1}. ` : ''}
              {q.question}
              {q.multiple ? <span className="t3" style={{ fontWeight: 400, fontSize: 12 }}>（可多选）</span> : null}
              {flag ? <span style={{ color: 'var(--wait)', fontWeight: 400, fontSize: 12 }}> · 还没处理</span> : null}
            </div>
            {q.context ? <div className="t3" style={{ fontSize: 12, margin: '0 0 6px' }}>背景：{q.context}</div> : null}
            {free(q) ? null : (
            <div className="opts">
              {q.options.map((o: QuestionOption, i: number) => {
                const on: boolean = c.picked.includes(o.label);
                return (
                  <button
                    type="button"
                    key={o.label}
                    disabled={locked}
                    aria-pressed={on}
                    className={`opt${on ? ' sel' : ''}`}
                    style={{ height: 'auto', minHeight: 32, padding: '6px 10px' }}
                    onClick={() => {
                      form.pick(q, o);
                      if (form.single) onWrite();
                    }}
                  >
                    <span className="n">{i + 1}</span>
                    <span>
                      {cleanLabel(o)}
                      {o.description ? <span className="t3" style={{ display: 'block', fontSize: 12 }}>{o.description}</span> : null}
                    </span>
                    {/* 徽标在选项的第三列（tags.css），不占文字的位置，也不随文字长短被压窄 */}
                    {isRec(o) ? <span className="tag rec">推荐</span> : null}
                  </button>
                );
              })}
            </div>
            )}
            {free(q) ? answerBox : null}
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 6 }}>
              {free(q) ? null : (
                <Lesser
                  on={c.other}
                  label={OWN_LABEL}
                  disabled={locked}
                  onClick={() => {
                    form.writeOwn(q);
                    if (form.single) onWrite();
                  }}
                />
              )}
              <Lesser
                on={c.skip}
                label={SKIP_LABEL}
                disabled={locked}
                onClick={() => {
                  form.skipOne(q);
                  if (form.single) onWrite();
                }}
              />
            </div>
            {free(q) ? null : answerBox}
          </div>
        );
      })}
      <div className="t3" style={{ fontSize: 12, margin: '2px 0 0' }}>{guide}</div>
      <div className="qf" style={{ flexWrap: 'wrap' }}>
        <button type="button" className="btn pri" disabled={!can} onClick={() => form.submit(text)}>
          提交回答
        </button>
        {question.extras ? (
          <button type="button" className="btn" disabled={locked} onClick={() => form.aside()} title={ASIDE_TIP}>
            不处理
          </button>
        ) : null}
        <span style={{ flex: 1 }} />
        {confirmStop ? (
          <span role="alertdialog" aria-label="确认停止" style={{ display: 'inline-flex', gap: 6, alignItems: 'center', fontSize: 12 }}>
            停止这个话题？在等你定的任务会结束。
            <button type="button" className="btn" disabled={form.pending} style={{ color: 'var(--fail)' }} onClick={() => { setConfirmStop(false); form.stop(); }}>
              确定停止
            </button>
            <button type="button" className="btn" onClick={() => setConfirmStop(false)}>取消</button>
          </span>
        ) : (
          <button type="button" className="btn" disabled={locked} style={{ color: 'var(--fail)' }} onClick={() => setConfirmStop(true)}>
            停止这个话题
          </button>
        )}
      </div>
      <PhaseLine form={form} />
    </div>
  );
};

/** 动作发出后的一行：失败的原因、已提交、已执行 */
const PhaseLine: React.FC<{ form: QuestionForm }> = ({ form }) => {
  if (form.phase === 'failed') return <div role="alert" style={{ color: 'var(--fail)', fontSize: 12, marginTop: 6 }}>失败：{form.failedMsg}，可以再试一次</div>;
  if (form.phase === 'sent') return <div role="status" className="t3" style={{ fontSize: 12, marginTop: 6 }}>已提交，等 Covey 执行</div>;
  if (form.phase !== 'done') return null;
  const words: string = form.act === 'aside' ? '已先不管，等页面更新' : form.act === 'restore' ? '已撤销，等页面更新' : '已执行，等页面更新';
  return <div role="status" className="t3" style={{ fontSize: 12, marginTop: 6 }}>{words}</div>;
};

/** 点了“不处理”、话题下一轮还没带走的题：一行说明和“撤销”（同飞书卡上的撤销） */
const AsidePanel: React.FC<{ form: QuestionForm }> = ({ form }) => {
  const question: QuestionView | null = form.question;
  if (!question || !question.restorable) return null;
  const busy: boolean = form.pending || (form.act === 'restore' && (form.phase === 'sent' || form.phase === 'done'));
  return (
    <div className="qc" aria-label="先不管的题" style={{ borderColor: 'var(--line)', boxShadow: 'none' }}>
      <div className="qh" style={{ color: 'var(--t2)' }}>
        <CircleHelp />
        {hm(question.closed_at)}先不管了 · {question.questions.length} 道题
        <span style={{ flex: 1 }} />
        <button type="button" className="btn" disabled={busy} onClick={() => form.restore()}>
          撤销
        </button>
      </div>
      <div className="t3" style={{ fontSize: 12, marginTop: 4 }}>
        每题记为不回答（不表示同意），话题下一轮开始时告诉模型；在那之前可以撤销，重新回答。
        {question.questions[0] ? ` 第一题：${question.questions[0].question.length > 40 ? `${question.questions[0].question.slice(0, 40)}…` : question.questions[0].question}` : ''}
      </div>
      <PhaseLine form={form} />
    </div>
  );
};
