import React, { useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import type { UsageDay, UsageHarness, UsageResponse } from '@shared/api.interface';
import { useIsDesktop } from '@client/src/hooks/use-breakpoint';
import { useUsage } from '@client/src/hooks/use-workbench';
import { Head } from './Shell';
import { fmtTok, hhmm, pref, setPref } from './lib';
import { UsageBars } from './UsageBars';
import { RANGES, cachePct, dayWords, mmdd, perDay, shownDays, spanOf, tokText, weekWord, weekdayOf, xTicks } from './usageData';

const RANGE_KEY = 'usage.days';

/** 选的是最近几天：地址里的 ?days= 先，没有就用上次选的，再没有是 7 */
function rangeOf(asked: string | null): number {
  for (const v of [asked, pref(RANGE_KEY, '')]) {
    const n = Number(v);
    if (RANGES.includes(n)) return n;
  }
  return 7;
}

/** 占比：不到 1% 但不是 0 的写“<1%”，不写成 0% */
const share = (part: number, total: number): string => {
  const pct: number = (part / total) * 100;
  return pct > 0 && pct < 0.5 ? '<1%' : `${Math.round(pct)}%`;
};

/** 各 Harness：名字、一根同色的横条（占这段 token 的多少）、token、占比、任务数 */
const Harnesses: React.FC<{ rows: UsageHarness[]; total: number }> = ({ rows, total }) => {
  const shown: UsageHarness[] = rows.filter((h: UsageHarness) => h.tasks > 0);
  if (!shown.length) return null;
  const max: number = Math.max(1, ...shown.map((h: UsageHarness) => h.tokens));
  return (
    <>
      <h2 className="us-sec">各 Harness</h2>
      <div className="us-hs">
        {shown.map((h: UsageHarness) => (
          <React.Fragment key={h.title}>
            <span className="nm" title={h.title}>{h.title}</span>
            <span className="tr" aria-hidden><i style={{ width: `${(h.tokens / max) * 100}%` }} /></span>
            <span className="v"><b>{tokText(h.tokens)}</b>{total > 0 ? ` · ${share(h.tokens, total)}` : ''} · {h.tasks} 个任务</span>
          </React.Fragment>
        ))}
      </div>
    </>
  );
};

/** 每天一行，新的在上；点一行，图上那根亮 */
const DayTable: React.FC<{ days: UsageDay[]; today: string; picked: string | null; onPick: (date: string) => void }> = ({ days, today, picked, onPick }) => (
  <table className="us-table">
    <thead>
      <tr><th>日期</th><th>token</th><th>任务</th><th>话题</th><th>缓存命中</th></tr>
    </thead>
    <tbody>
      {[...days].reverse().map((d: UsageDay, i: number, all: UsageDay[]) => {
        const pct: number | null = cachePct(d);
        // 新的在上：周日这一行往下是上一周，画一条分隔
        const wk: boolean = all.length > 7 && i > 0 && weekdayOf(d.date) === 0;
        return (
          <tr key={d.date} id={`usage-${d.date}`} className={`${d.date === picked ? 'on' : ''}${wk ? ' wk' : ''}`} onClick={() => onPick(d.date)}>
            <td>{dayWords(d.date)}{d.date === today ? <span className="today">今天</span> : null}</td>
            <td className={d.tokens ? 'tok' : 'zero'}>{tokText(d.tokens)}</td>
            <td className={d.tasks ? '' : 'zero'}>{d.tasks}</td>
            <td className={d.topics ? '' : 'zero'}>{d.topics}</td>
            <td className={pct === null ? 'zero' : ''}>{pct === null ? '—' : `${pct}%`}</td>
          </tr>
        );
      })}
    </tbody>
  </table>
);

const Body: React.FC<{ u: UsageResponse; n: number; desktop: boolean }> = ({ u, n, desktop }) => {
  const [picked, setPicked] = useState<string | null>(null);
  const days: UsageDay[] = shownDays(u, n);
  const span = spanOf(u, n);
  const today: string = u.days[u.days.length - 1]?.date ?? '';
  const pct: number | null = cachePct(span);
  const ticks = new Set<number>(xTicks(days, desktop ? 12 : 5));
  const short: boolean = days.length < n;
  const pick = (date: string): void => {
    setPicked(date);
    document.getElementById(`usage-${date}`)?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  };
  return (
    <>
      <div className="us-sum">
        <span className="us-big">{fmtTok(span.tokens)}<small>token</small></span>
        {days.length > 1 ? <span className="us-avg">日均 {tokText(perDay(span.tokens, days.length))}</span> : null}
      </div>
      <div className="us-meta">
        {span.tasks} 个任务{span.exact ? ` · ${span.topics} 个话题` : ''}{pct === null ? '' : ` · 缓存命中 ${pct}%`}
      </div>
      <div className="us-chart">
        <UsageBars
          days={days}
          today={today}
          height={desktop ? 180 : 140}
          axis
          peak
          label={(d: UsageDay, i: number) => (n <= 7 ? (d.date === today ? '今天' : weekWord(d.date)) : ticks.has(i) ? mmdd(d.date) : null)}
          picked={picked}
          onPick={pick}
          asOf={hhmm(u.at)}
          name={`最近 ${n} 天每天的 token，左右键看每一天，回车在下面的表里找到那天`}
        />
      </div>
      {short && days[0] ? <p className="us-note">记录从 {mmdd(days[0].date)} 开始，之前的天没有数。</p> : null}
      <Harnesses rows={span.harnesses} total={span.tokens} />
      <h2 className="us-sec">每天</h2>
      <DayTable days={days} today={today} picked={picked} onPick={setPicked} />
      <p className="us-note">
        按任务开始的那天算，和飞书「用量」卡同一个算法：token 含缓存命中和子任务。
        {span.untracked ? `另有 ${span.untracked} 个任务没有 token 记录（如还没收到回复就停了），算在任务数里，不在 token 里。` : ''}
        {u.at ? `更新于 ${hhmm(u.at)}。` : ''}
      </p>
    </>
  );
};

/** 用量页：最近 7、30、90 天每天的 token、任务、话题、缓存命中，和各 Harness 的占比（docs/ui.md 5.4「专门去查」） */
const UsagePage: React.FC = () => {
  const desktop: boolean = useIsDesktop();
  const { data: u, isLoading } = useUsage();
  const [params, setParams] = useSearchParams();
  const n: number = rangeOf(params.get('days'));
  const choose = (days: number): void => {
    setPref(RANGE_KEY, String(days));
    setParams({ days: String(days) }, { replace: true });
  };
  const span = u ? spanOf(u, n) : null;
  const days: UsageDay[] = u ? shownDays(u, n) : [];
  return (
    <div className="us-page">
      <Head title="用量" sub={desktop ? '每天用了多少 token、做了多少任务' : undefined} back="/" />
      <div className="scroll">
        <div className="us-col">
          <div className="us-ranges">
            <div className="us-seg" role="group" aria-label="看最近几天">
              {RANGES.map((r: number) => (
                <button key={r} type="button" aria-pressed={r === n} onClick={() => choose(r)}>{r} 天</button>
              ))}
            </div>
            {span && days.length ? <span className="us-when">{mmdd(days[0].date)} – {mmdd(days[days.length - 1].date)}</span> : null}
          </div>
          {u ? <Body u={u} n={n} desktop={desktop} /> : (
            <p className="us-empty">
              {isLoading ? '正在读用量…' : <>Covey 还没推按天的用量：Covey 更新后一分钟内就有。<br /><Link to="/">回看板</Link></>}
            </p>
          )}
        </div>
      </div>
    </div>
  );
};
export default UsagePage;
