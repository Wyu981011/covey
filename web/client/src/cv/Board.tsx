import React, { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { RotateCcw, Sparkles } from 'lucide-react';
import type {
  ActivityItem, FeedItem, OutboxStatus, QuestionView, SnapshotProject, SnapshotResponse, SnapshotTopic, StatsResponse, UsageDay,
} from '@shared/api.interface';
import { useIsDesktop } from '@client/src/hooks/use-breakpoint';
import { newOpId, postOutboxQuiet, prefetchTurns, useSendOutbox, useSnapshot, useStats, useUsage } from '@client/src/hooks/use-workbench';
import { fetchOutboxStatus, postOutbox } from '@client/src/api/workbench';
import { ageMs, errorText, oneLineText } from '@client/src/lib/workbench-format';
import { cleanLabel, isRec, quickAnswerable, useAnswer } from './Question';
import { Head, SyncDot } from './Shell';
import { useSay } from './Composer';
import { ConclusionBand, Dot, Pill, RollNum, Spark, StateBar, StepCells, TodoBar, useTick } from './ui';
import { byAsked, byNumberDesc, byRecent, fmtTok, hhmm, isWaiting, pref, setPref, toneOf, waitText, type ToneKey } from './lib';
import { BRAND, STATES } from './look.gen';
import { putLater, useLater } from './store';
import { TidyPanel } from './Tidy';
import { etaText, isStopped, listTone } from './topicText';
import { UsageBars } from './UsageBars';
import { cachePct, shownDays, spanOf, weekWord } from './usageData';

const topicPath = (t: SnapshotTopic): string => `/topics/${encodeURIComponent(t.key)}`;
const tno = (t: SnapshotTopic): string => (t.number ? `T${t.number}` : '');

/** 话题的“要你处理”卡：等你、停住了、可能卡住。一张卡最多一个主按钮 */
const ActCard: React.FC<{ t: SnapshotTopic; tone: ToneKey; snap: SnapshotResponse; q?: QuestionView }> = ({ t, tone, snap, q }) => {
  const nav = useNavigate();
  const qc = useQueryClient();
  const now: number = useTick(30000);
  const ans = useAnswer(t.key);
  const say = useSay(t.key);
  const [sent, setSent] = useState<boolean>(false);
  const [dis, setDis] = useState<string>('');
  const p: SnapshotProject | undefined = snap.projects.find((x: SnapshotProject) => x.key === t.project_key);
  const item = q?.questions[0];
  const quick: boolean = tone === 'waiting' && !!q && quickAnswerable(q) && (item?.options.length ?? 0) <= 3;
  const f = t.latest_failure;
  const canContinue: boolean = !f || !f.actions.length || f.actions.includes('continue');
  const since: string = waitText(Math.max(60, now - t.updated_at));
  let line: React.ReactNode;
  let meta: string;
  if (tone === 'waiting') {
    line = <>要你定：{item ? item.question : oneLineText(t.latest, 120) || '在等你的回复'}</>;
    meta = `等了 ${since}`;
  } else if (tone === 'stopped') {
    line = <>原因：{f ? f.title : '上一轮没做完'}</>;
    meta = `${hhmm(t.updated_at)} 停住`;
  } else {
    line = <>{t.progress?.last_activity ? `${t.progress.last_activity}，` : ''}{waitText(Math.max(60, now - (t.progress?.last_activity_at ?? t.updated_at)))}没有新动静</>;
    meta = t.progress?.plan_total ? `${t.progress.plan_done ?? 0}/${t.progress.plan_total} 步` : '';
  }
  const open = (): void => { void nav(topicPath(t)); };
  /** 不管了：发 dismiss 让 Covey 真的放下这个话题；没开看板（failed）就退回只记在这台设备上，并说一句 */
  const dismiss = async (): Promise<void> => {
    const key: string = t.latest_key ?? '';
    const opId: string = newOpId();
    setDis('正在告诉 Covey…');
    let state = 'failed';
    try {
      await postOutbox({ op_id: opId, kind: 'dismiss', topic_key: t.key, payload: {} });
      for (let i = 0; i < 12; i += 1) {
        await new Promise<void>((r) => window.setTimeout(r, i < 3 ? 600 : 1200));
        const r: OutboxStatus = await fetchOutboxStatus(opId).catch(() => ({ state: 'new' }) as unknown as OutboxStatus);
        if (r.state === 'done' || r.state === 'failed') {
          state = r.state;
          break;
        }
      }
    } catch {
      state = 'failed';
    }
    if (state === 'done') {
      putLater(key);
      void qc.invalidateQueries({ queryKey: ['snapshot'] });
      return;
    }
    setDis('Covey 那边没有处理（没开看板），先只记在这台设备上');
    window.setTimeout(() => putLater(key), 2500);
  };
  return (
    <article className={`nb-act tone-${tone}`} onMouseEnter={() => prefetchTurns(qc, t.key)} onTouchStart={() => prefetchTurns(qc, t.key)}>
      <div className="nb-acth">
        <Pill tone={tone} />
        <span className="nb-meta">{meta}</span>
      </div>
      <Link to={topicPath(t)} className="nb-actt"><span className="nb-tno">{tno(t)}</span>{t.number ? ' · ' : ''}{t.title}</Link>
      <p className="nb-clamp2">{line}</p>
      {quick && q && item ? (
        <div className="nb-opts">
          {item.options.map((o) => (
            <button type="button" key={o.label} className={`btn sm${isRec(o) ? ' pri' : ''}`} disabled={ans.pending} onClick={() => ans.send(q, { [item.id]: o.label })} title="点一下就写入回答">
              {cleanLabel(o)}
            </button>
          ))}
        </div>
      ) : null}
      <div className="nb-btns">
        {tone === 'waiting' ? (
          <>
            {quick ? null : <button type="button" className="btn sm pri" onClick={open}>去回答</button>}
            <button type="button" className="btn sm" onClick={open}>打开话题</button>
          </>
        ) : tone === 'stopped' ? (
          sent ? (
            <span className="nb-meta">已发出，等 Covey 接着做</span>
          ) : (
            <>
              {canContinue ? (
                <button type="button" className="btn sm pri" onClick={() => { say('继续', Number.MAX_SAFE_INTEGER); setSent(true); }}>
                  <RotateCcw /> 检查并继续
                </button>
              ) : null}
              <button type="button" className={`btn sm${canContinue ? '' : ' pri'}`} onClick={open}>看原因</button>
              {t.latest_key ? <button type="button" className="btn sm txt" disabled={!!dis} onClick={() => void dismiss()} title="这一轮不再出现在要你处理里">不管了</button> : null}
            </>
          )
        ) : (
          <button type="button" className="btn sm pri" onClick={open}>打开话题</button>
        )}
        <span className="nb-meta nb-proj">{p ? p.title : ''}</span>
      </div>
      {dis ? <div className="nb-meta">{dis}</div> : null}
      {ans.error ? <div role="alert" className="a-errt">发送失败：{ans.error}</div> : null}
    </article>
  );
};

/** 话题行 topic_row（在做，夜航 v2 的表格行）：状态点、T 号、标题和一行“现在”，右边预计、步骤格和步数；只有一条发丝线 */
const RunRow: React.FC<{ t: SnapshotTopic }> = ({ t }) => {
  const nav = useNavigate();
  const qc = useQueryClient();
  const r = t.running;
  const p = t.progress;
  const total: number = p?.plan_total ?? r?.plan_total ?? 0;
  const done: number = p?.plan_total ? (p.plan_done ?? 0) : (r?.plan_done ?? 0);
  const phase: string = p?.phase || r?.plan_doing || (t.latest_role !== 'owner' ? oneLineText(t.latest, 80) : '') || '在做';
  const eta: string = etaText(p?.eta_seconds);
  return (
    <div
      className="nb-trow tone-running"
      role="link"
      tabIndex={0}
      onClick={() => nav(topicPath(t))}
      onKeyDown={(e: React.KeyboardEvent) => { if (e.key === 'Enter') nav(topicPath(t)); }}
      onMouseEnter={() => prefetchTurns(qc, t.key)}
      onTouchStart={() => prefetchTurns(qc, t.key)}
    >
      <Dot tone="running" />
      <span className="nb-tno">{tno(t)}</span>
      <span className="nb-tt">
        <b>{t.title}</b>
        <small>{phase}</small>
      </span>
      <span className="nb-eta">{eta}</span>
      {total ? <StepCells done={done} total={total} /> : <span />}
      <span className="nb-frac">{total ? `${done}/${total}` : ''}</span>
    </div>
  );
};

/** 有结果没看：一行，右边「记为看过」 */
const ResultRow: React.FC<{ t: SnapshotTopic }> = ({ t }) => {
  const nav = useNavigate();
  const [seen, setSeen] = useState<boolean>(false);
  const line: string = t.latest_role !== 'owner' ? oneLineText(t.latest, 90) : '';
  return (
    <div className="nb-row nb-res" role="link" tabIndex={0} onClick={() => nav(topicPath(t))} onKeyDown={(e: React.KeyboardEvent) => { if (e.key === 'Enter') nav(topicPath(t)); }}>
      <div className="nb-rowh">
        <Pill tone="result" />
        <b className="nb-rowt"><span className="nb-tno">{tno(t)}</span>{t.number ? ' · ' : ''}{t.title}</b>
        <span className="nb-rowl nb-inl">{line}</span>
        {seen ? (
          <span className="nb-meta nb-right">已记为看过</span>
        ) : (
          <button
            type="button"
            className="btn sm nb-right"
            onClick={(e: React.MouseEvent) => { e.stopPropagation(); postOutboxQuiet({ op_id: newOpId(), kind: 'seen', topic_key: t.key, payload: {} }); setSeen(true); }}
          >
            记为看过
          </button>
        )}
      </div>
    </div>
  );
};

interface ProjectView {
  p: SnapshotProject;
  tones: ToneKey[];
  last: number;
}

/** 专项（右栏是索引）：名字和一行计数；描述和进度条在专项页，不在这里重复 */
const ProjectCard: React.FC<{ x: ProjectView }> = ({ x }) => {
  const { p } = x;
  const parts: [ToneKey, number][] = (['waiting', 'stopped', 'stuck', 'result', 'running', 'done'] as ToneKey[]).map((k: ToneKey): [ToneKey, number] => [k, x.tones.filter((v: ToneKey) => v === k).length]);
  return (
    <Link to={`/projects/${encodeURIComponent(p.key)}`} className="nb-proj-card">
      <b className="nb-clamp1" title={p.goal || p.title}>{p.title}</b>
      <span className="nb-meta">
        {p.counts.topics} 个话题
        {parts.filter(([, n]) => n > 0).map(([k, n]) => <span key={k} className={`nb-pc tone-${k}`}> · {n} {STATES[k].word}</span>)}
      </span>
    </Link>
  );
};

const WEEKDAYS = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'];

/** 本周用量：近 7 天（含今天）的 token，下面一行任务、话题和缓存命中，底部每天一根柱子，停上去看那天的数；「明细」去用量页。
 *  Covey 推了按天的用量（v26）才这样画，旧 Covey 照原来的趋势线 */
const WeekUsage: React.FC<{ st: StatsResponse | undefined }> = ({ st }) => {
  const { data: u } = useUsage();
  if (u) {
    const span = spanOf(u, 7);
    const pct: number | null = cachePct(span);
    const today: string = u.days[u.days.length - 1]?.date ?? '';
    return (
      <section className="nb-panel nb-usage">
        <h3 className="nb-ph">本周用量<em>近 7 天</em><Link className="nb-more" to="/usage">明细 ›</Link></h3>
        <div className="nb-big">{fmtTok(span.tokens)} <small>token</small></div>
        <div className="nb-meta">{span.tasks} 个任务{span.exact ? ` · ${span.topics} 个话题` : ''}{pct === null ? '' : ` · 缓存命中 ${pct}%`}</div>
        <UsageBars
          days={shownDays(u, 7)}
          today={today}
          height={44}
          label={(d: UsageDay) => (d.date === today ? '今天' : weekWord(d.date))}
          asOf={hhmm(u.at)}
          name="近 7 天每天的 token，左右键看每一天"
        />
      </section>
    );
  }
  if (!st || st.week_tokens === undefined) return null;
  const days: string[] = Array.from({ length: 7 }, (_, i: number) => WEEKDAYS[new Date(Date.now() - (6 - i) * 86400000).getDay()]);
  return (
    <section className="nb-panel">
      <h3 className="nb-ph">本周用量<em>近 7 天</em></h3>
      <div className="nb-big">{fmtTok(st.week_tokens)} <small>token</small></div>
      <div className="nb-meta">{st.week_turns ?? 0} 个任务{typeof st.week_topics === 'number' ? ` · ${st.week_topics} 个话题` : ''}{typeof st.week_cache_pct === 'number' ? ` · 缓存命中 ${st.week_cache_pct}%` : ''}</div>
      {st.week_series ? <Spark series={st.week_series} color={BRAND} className="nb-spark" h={40} /> : null}
      <div className="nb-days">{days.map((d: string, i: number) => <span key={i}>{d}</span>)}</div>
    </section>
  );
};

const TIDY_KEY = 'tidy.op';
const TIDY_SHOW_MS = 30 * 60 * 1000;

/** 「整理」：发件箱写一条 tidy，按钮旁边原地显示 Covey 回的结果 */
const TidyButton: React.FC = () => {
  const send = useSendOutbox();
  const [op, setOp] = useState<{ id: string; at: number } | null>(() => {
    try {
      const v = JSON.parse(pref(TIDY_KEY, 'null')) as { id: string; at: number } | null;
      return v && Date.now() - v.at < TIDY_SHOW_MS ? v : null;
    } catch {
      return null;
    }
  });
  const [err, setErr] = useState<string>('');
  const st = useQuery<OutboxStatus>({
    queryKey: ['outbox', op?.id],
    queryFn: () => fetchOutboxStatus(op?.id ?? ''),
    enabled: !!op && !send.isPending,
    refetchInterval: (q) => (q.state.data && q.state.data.state !== 'new' ? false : 2000),
    retry: 2,
  });
  const go = (): void => {
    const id: string = newOpId();
    setErr('');
    send.mutate(
      { op_id: id, kind: 'tidy', payload: { scope: '' } },
      {
        onSuccess: () => {
          const v = { id, at: Date.now() };
          setPref(TIDY_KEY, JSON.stringify(v));
          setOp(v);
        },
        onError: (e: Error) => setErr(errorText(e)),
      },
    );
  };
  const s: OutboxStatus | undefined = st.data;
  const busy: boolean = send.isPending || (!!op && (!s || s.state === 'new'));
  let note: React.ReactNode = null;
  if (err) note = <span className="a-errt">没发出去：{err}</span>;
  else if (send.isPending) note = <span className="a-faint">发送中…</span>;
  else if (op && (!s || s.state === 'new')) note = <span className="a-faint">已发出，等 Covey 回…</span>;
  else if (s?.state === 'done') note = <span className="a-okt">{s.message || '已开始整理，结果发到私聊'}</span>;
  else if (s?.state === 'failed') note = <span className="a-errt">没成：{s.message || '没有成功'}</span>;
  return (
    <span className="a-tidy">
      {note}
      <button type="button" className="btn sm" onClick={go} disabled={busy} title="把现有专项和最近 7 天的话题重新看一遍，给出归进、新建、合并等建议">
        <Sparkles /> 整理
      </button>
    </span>
  );
};

/** 最近动态按话题合并：“T518 · 做完 5 轮 · 问过 2 次”。服务端没给 feed（旧版）时从 activity 凑 */
function mergedFeed(st: StatsResponse | undefined): FeedItem[] {
  if (!st) return [];
  if (st.feed) return st.feed;
  const m = new Map<string, FeedItem>();
  for (const a of st.activity as ActivityItem[]) {
    const f: FeedItem = m.get(a.topic_key) ?? { topic_key: a.topic_key, number: a.number, title: a.title, done: 0, failed: 0, asked: 0, at: 0 };
    if (a.kind === 'done') f.done += 1;
    if (a.kind === 'failed') f.failed += 1;
    if (a.kind === 'asked') f.asked += 1;
    f.at = Math.max(f.at, a.at);
    m.set(a.topic_key, f);
  }
  return [...m.values()].filter((f: FeedItem) => f.done || f.failed || f.asked).sort((a: FeedItem, b: FeedItem) => b.at - a.at);
}

const feedText = (f: FeedItem): string =>
  [f.done ? `做完 ${f.done} 轮` : '', f.failed ? `没做完 ${f.failed} 轮` : '', f.asked ? `问过 ${f.asked} 次` : ''].filter(Boolean).join(' · ');

/** 最后同步超过 3 分钟，时间变橙 */
const Updated: React.FC<{ at: string | null | undefined }> = ({ at }) => {
  useTick(15000);
  const age: number | null = ageMs(at);
  const t: string = at ? hhmm(Date.parse(at) / 1000) : '';
  return <p className={`nb-updated${age !== null && age > 180000 ? ' stale' : ''}`}>{t ? `更新于 ${t}` : '还没同步'}</p>;
};

const Board: React.FC = () => {
  const desktop: boolean = useIsDesktop();
  const { data: snap } = useSnapshot();
  const { data: st } = useStats();
  const later = useLater();
  const now: number = useTick(30000);
  if (!snap) return null;
  const topics: SnapshotTopic[] = snap.topics.filter((t: SnapshotTopic) => t.kind === 'topic');
  const qBy = new Map<string, QuestionView>(snap.questions.map((q: QuestionView) => [q.topic_key, q]));
  const waiting: SnapshotTopic[] = topics.filter((t: SnapshotTopic) => isWaiting(t) || qBy.has(t.key)).sort(byAsked);
  const stopped: SnapshotTopic[] = topics.filter((t: SnapshotTopic) => !qBy.has(t.key) && isStopped(t, now, later)).sort(byRecent);
  const stuck: SnapshotTopic[] = topics.filter((t: SnapshotTopic) => !qBy.has(t.key) && toneOf(t) === 'stuck').sort(byNumberDesc);
  const running: SnapshotTopic[] = topics.filter((t: SnapshotTopic) => toneOf(t) === 'running' && !qBy.has(t.key)).sort(byNumberDesc);
  const unseen: SnapshotTopic[] = topics.filter((t: SnapshotTopic) => toneOf(t) === 'result').sort(byRecent);
  const act: number = waiting.length + stopped.length + stuck.length;
  const views: ProjectView[] = snap.projects.map((p: SnapshotProject): ProjectView => {
    const own: SnapshotTopic[] = topics.filter((t: SnapshotTopic) => t.project_key === p.key);
    return { p, tones: own.map(listTone), last: Math.max(p.updated_at, ...own.map((t: SnapshotTopic) => t.updated_at)) };
  });
  const rank = (x: ProjectView): number => {
    const hot: number = ['waiting', 'stopped', 'stuck', 'running', 'result'].findIndex((k: string) => x.tones.includes(k as ToneKey));
    return hot < 0 ? (['做完', '收起', '已取消'].includes(x.p.status) ? 9 : 8) : hot;
  };
  views.sort((a: ProjectView, b: ProjectView) => rank(a) - rank(b) || b.last - a.last || a.p.key.localeCompare(b.p.key));
  const feed: FeedItem[] = mergedFeed(st);
  // 结论带：按 look 的 PRESSING 说最急的；等你、停住了时数字旁的点慢慢呼吸
  const breathe: ToneKey | null = waiting.length ? 'waiting' : stopped.length ? 'stopped' : null;
  const sub: string[] = [];
  let n: number | null = null;
  let words = '都在掌握中';
  if (act) {
    n = act;
    words = '件事要你处理';
  } else if (unseen.length) {
    n = unseen.length;
    words = '个结果没看';
  } else if (running.length) {
    n = running.length;
    words = '件在做';
  }
  if (running.length && words !== '件在做') sub.push(`${running.length} 件在做`);
  if (unseen.length && words !== '个结果没看') sub.push(`${unseen.length} 个结果没看`);
  if (!n) sub.push('现在没有在等你的事');
  if (!act && n) sub.unshift('没有事等你，都在掌握中');
  const first: SnapshotTopic | undefined = waiting[0] ?? stopped[0] ?? stuck[0];
  const firstLine: string = first
    ? `${tno(first) || first.title}：${waiting[0] === first ? (qBy.get(first.key)?.questions[0]?.question ?? first.title) : stopped[0] === first ? (first.latest_failure?.title ?? '上一轮没做完') : '可能卡住了'}`
    : '';
  const band = (
    <ConclusionBand
      label={<span className="nb-l1t">现在</span>}
      n={n}
      words={words}
      breathe={breathe}
      sub={sub.join('，')}
      counts={[['waiting', waiting.length], ['stopped', stopped.length], ...(stuck.length ? [['stuck', stuck.length] as [ToneKey, number]] : []), ['result', unseen.length], ['running', running.length]]}
    >
      {/* 只有 1 件时下面的卡就是它，结论带不再重复 */}
      {act > 1 && firstLine ? <TodoBar>{oneLineText(firstLine, 60)}</TodoBar> : null}
      <StateBar legend={false} parts={[['waiting', waiting.length], ['stopped', stopped.length], ['stuck', stuck.length], ['result', unseen.length], ['running', running.length]]} />
    </ConclusionBand>
  );
  const projects = views.length ? (
    <section className="nb-panel">
      <h3 className="nb-ph">专项<em>{views.length}</em><TidyButton /></h3>
      <div className="nb-plist">{views.slice(0, 8).map((x: ProjectView) => <ProjectCard key={x.p.key} x={x} />)}</div>
    </section>
  ) : (
    <section className="nb-panel">
      <h3 className="nb-ph">专项<TidyButton /></h3>
      <p className="nb-note">还没有专项。点「整理」让 Covey 看看哪些话题该归成专项。</p>
    </section>
  );
  const rail = (
    <>
      {projects}
      <WeekUsage st={st} />
      {feed.length ? (
        <section className="nb-panel">
          <h3 className="nb-ph">最近动态<em>同一话题合并</em></h3>
          <ul className="a-feed">
            {feed.slice(0, 8).map((f: FeedItem) => (
              <li key={f.topic_key}>
                <span className="a-tmc">{hhmm(f.at)}</span>
                <Link to={`/topics/${encodeURIComponent(f.topic_key)}`} title={f.title}>
                  <span className="a-fl1"><b>{f.number ? `T${f.number}` : '话题'}</b> · {feedText(f)}</span>
                  <span className="a-ft2">{f.title}</span>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </>
  );
  return (
    <div className="a-board nb-board">
      <div className="a-center">
        <Head title="看板" right={<span className="nb-synced"><SyncDot at={snap.synced_at} />{desktop ? '已同步' : ''}</span>} />
        <div className="a-scroll nb-scroll">
          {band}
          {act ? (
            <div className="nb-actgrid">
              {waiting.map((t: SnapshotTopic) => <ActCard key={t.key} t={t} tone="waiting" q={qBy.get(t.key)} snap={snap} />)}
              {stopped.map((t: SnapshotTopic) => <ActCard key={t.key} t={t} tone="stopped" snap={snap} />)}
              {stuck.map((t: SnapshotTopic) => <ActCard key={t.key} t={t} tone="stuck" snap={snap} />)}
            </div>
          ) : null}
          <TidyPanel />
          {running.length ? (
            <>
              <h2 className="nb-sh">{STATES.running.heading}<em><RollNum value={running.length} /></em></h2>
              <div className="nb-rows">{running.map((t: SnapshotTopic) => <RunRow key={t.key} t={t} />)}</div>
            </>
          ) : null}
          {unseen.length ? (
            <>
              <h2 className="nb-sh">{STATES.result.heading}<em>{unseen.length}</em></h2>
              <div className="nb-rows">{unseen.slice(0, 12).map((t: SnapshotTopic) => <ResultRow key={t.key} t={t} />)}</div>
            </>
          ) : null}
          {!desktop ? <div className="nb-mrail">{rail}</div> : null}
          {!topics.length ? <p className="nb-note">还没有话题。Covey 一推数据这里就有了。</p> : null}
          <Updated at={snap.synced_at} />
        </div>
      </div>
      {desktop ? <aside className="nb-rail">{rail}</aside> : null}
    </div>
  );
};
export default Board;
