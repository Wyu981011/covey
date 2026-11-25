import React from 'react';
import { Link, Navigate, useLocation, useParams } from 'react-router-dom';
import { Play } from 'lucide-react';
import type { SnapshotProject, SnapshotTopic } from '@shared/api.interface';
import { useIsDesktop } from '@client/src/hooks/use-breakpoint';
import { newOpId, useReport, useSnapshot } from '@client/src/hooks/use-workbench';
import { shortTime } from '@client/src/lib/workbench-format';
import { Conversation } from './Conversation';
import ProjectGraph from './ProjectGraph';
import ProjectBrief from './ProjectBrief';
import ProjectRail from './ProjectRail';
import { PaneHandle } from './PaneHandle';
import { PROJECT_RAIL } from './panes';
import ProjectReport from './ProjectReport';
import { ToneBar } from './ProjectsPage';
import { Head } from './Shell';
import { DurValue, Pill, Tile, useTick } from './ui';
import { haltWords, isHalted, leadOf, metrics, ownTopics, projectNote, projectPill, toneCounts, type ProjectMetrics } from './projectData';
import { TopicBadge } from './RoleAvatar';
import { ProjectOps } from './V34Bits';
import { useOutboxOp } from './sendOp';
import './recover.css';
import './mproj.css';
import { STATES } from './look.gen';
import { byUpdated, fmtTok, hhmm, isRunning, isWaiting, toneOf, type ToneKey } from './lib';
import { listTone } from './topicText';
import './projects.css';

/** rail：手机和窄屏没有右栏，此刻、记忆、文件放进“记忆与文件”标签；brief：项目简报（v40，背景、动作、任务图；负责人还没写时退回第一期的目标检查表三栏）。
 * 第一期的 /progress 还能打开，跳到 /brief */
type View = 'chat' | 'graph' | 'brief' | 'report' | 'rail';

const ProjectTabs: React.FC<{ base: string; view: View; mobile?: boolean; rail?: boolean }> = ({ base, view, mobile, rail }) => {
  const items: [View, string, string][] = [['chat', '', '对话'], ['graph', '/graph', '全图'], ['brief', '/brief', '简报'], ['report', '/report', '报告']];
  if (mobile) {
    return (
      <div className="mseg">
        {[...items, ...(rail ? [['rail', '/rail', '记忆与文件'] as [View, string, string]] : [])].map(([v, path, label]) => (
          <Link key={v} to={`${base}${path}`} className={view === v ? 'on' : ''}>{label}</Link>
        ))}
      </div>
    );
  }
  return (
    <div className="tabs">
      {items.map(([v, path, label]) => (
        <Link key={v} to={`${base}${path}`} className={view === v ? 'on' : ''}>{label}</Link>
      ))}
    </div>
  );
};

/** 电脑：专项头部的五块磁贴（手机是 MetricLine 一行） */
export const MetricStrip: React.FC<{ m: ProjectMetrics; topics: SnapshotTopic[] }> = ({ m, topics }) => {
  const now: number = useTick(30000);
  const waiting: number = topics.filter(isWaiting).length;
  const run: number = topics.filter(isRunning).length;
  return (
    <div className="strip">
      <div className="tiles" style={{ gridTemplateColumns: 'repeat(5,1fr)' }}>
        <div className="tile">
          <div className="k">话题</div>
          <div className="v">{topics.length}</div>
          <div className="seg">
            {topics.map((t: SnapshotTopic) => (
              <i key={t.key} className={`tone-${listTone(t)}`} style={{ flex: 1, background: 'var(--c)' }} />
            ))}
          </div>
        </div>
        <div className="tile" title="专项开张到现在过了多久（日历时间，不管有没有话题在干活）">
          <div className="k">开张至今</div>
          <div className="v">{m.startedAt ? <DurValue sec={Math.max(60, now - m.startedAt)} /> : '—'}</div>
        </div>
        <div className="tile" title="专项里每个话题实际在跑的时间加起来；几个话题同时跑会各算各的，所以可能比“开张至今”还长">
          <div className="k">各话题干活合计</div>
          <div className="v">{m.work ? <DurValue sec={m.work} /> : '—'}</div>
        </div>
        <div className={`tile${waiting ? ' c-wait' : ''}`}>
          <div className="k">等你</div>
          {/* 有话题在等你时先说几个（和看板一致）；没有时说你平时多久回 */}
          <div className="v">{!waiting && m.avgWait !== null ? <DurValue sec={m.avgWait} /> : waiting}</div>
          <div className="sub">{!waiting && m.avgWait !== null ? '现在没有 · 平均' : '个话题'}</div>
        </div>
        <div className="tile">
          <div className="k">token</div>
          <div className="v">{m.tokens ? fmtTok(m.tokens) : '—'}</div>
          <div className="sub">{m.cachePct !== null ? `缓存命中 ${m.cachePct}%` : run ? `${run} 在做` : ''}</div>
        </div>
      </div>
    </div>
  );
};

/** 手机：标签下面一行——一条按状态排的色条、按状态的话题数（要紧的上色）、token。电脑上的五块磁贴在手机上占一屏的一成、还会折行，开张至今和等你的平均在报告里 */
const MetricLine: React.FC<{ m: ProjectMetrics; topics: SnapshotTopic[] }> = ({ m, topics }) => {
  const tones: ToneKey[] = topics.map(listTone);
  return (
    <div className="pm-line">
      <ToneBar tones={tones} />
      <span className="pl-counts">
        {topics.length ? `${topics.length} 个话题` : '还没有话题'}
        {toneCounts(tones).map(([k, n]) => <span key={k} className={`pl-n tone-${k}`}> · {n} {STATES[k].word}</span>)}
      </span>
      {m.tokens ? <span className="pm-tok short">{fmtTok(m.tokens)} token</span> : null}
    </div>
  );
};

/** 护栏停住的专项（T647 P0-3，docs/ui.md 2.2）：头部下面一条红色“停住了 · 原因”和「继续」。继续发 reopen，
 * 同飞书停住卡上的继续（Covey 把专项改回在做、唤醒次数重新数，token 用完的从现在重新算），回执原地写 */
const HaltBar: React.FC<{ p: SnapshotProject }> = ({ p }) => {
  const op = useOutboxOp();
  return (
    <div className="pj-halt" role="status">
      <span className="pj-hw">{haltWords(p)}</span>
      <span className="pj-hn">{op.line || `停住时负责人不会被叫醒；点「继续」让专项接着做${/token/iu.test(p.status_reason) ? '，token 从现在重新算' : ''}`}</span>
      {op.phase === 'done' ? null : (
        <button type="button" className="btn sm pri" disabled={op.busy} onClick={() => void op.run({ op_id: newOpId(), kind: 'reopen', project_key: p.key, payload: {} })}>
          <Play /> 继续
        </button>
      )}
      {/* v34：同停住卡上的收尾（Covey 认 project_finish 时才有） */}
      {op.phase === 'done' ? null : <ProjectOps p={p} finishOnly />}
    </div>
  );
};

/** 还没有负责人那一路时，退回 v1：话题列表 + 选中话题的对话 */
const Fallback: React.FC<{ topics: SnapshotTopic[]; sel: string | undefined; desktop: boolean }> = ({ topics, sel, desktop }) => {
  const list: SnapshotTopic[] = [...topics].sort(byUpdated);
  const cur: SnapshotTopic | undefined = list.find((t: SnapshotTopic) => t.key === sel) ?? list.find(isWaiting) ?? list.find(isRunning) ?? list[0];
  const listEl = (
    <div className={desktop ? 'rp' : 'scroll'} style={desktop ? { order: -1, borderLeft: 0, borderRight: '1px solid var(--line)', width: 280 } : { padding: 12 }}>
      <div className="rps">
        {list.map((t: SnapshotTopic) => (
          <Link key={t.key} to={`/topics/${encodeURIComponent(t.key)}`} className={`row${cur?.key === t.key && desktop ? ' on' : ''}`}>
            <i className={`dot tone-${toneOf(t)}`} /><TopicBadge number={t.number} /><span className="t">{t.title}</span>
          </Link>
        ))}
        {!list.length ? <p className="t3 a-pempty">这个专项还没有话题。</p> : null}
      </div>
    </div>
  );
  if (!desktop) return listEl;
  return (
    <div style={{ display: 'flex', flex: 1, minHeight: 0 }}>
      {listEl}
      {cur ? <Conversation key={cur.key} topicKey={cur.key} mode="topic" placeholder="对这个话题说一句" /> : <div style={{ flex: 1 }} />}
    </div>
  );
};

const ProjectPage: React.FC = () => {
  const { key = '' } = useParams();
  const loc = useLocation();
  const desktop: boolean = useIsDesktop();
  const { data: snap } = useSnapshot();
  const { data: rep } = useReport(key);
  const p: SnapshotProject | undefined = snap?.projects.find((x: SnapshotProject) => x.key === key);
  if (!snap) return null;
  if (!p) return <Navigate to="/" replace />;
  const rest: string = loc.pathname.slice(`/projects/${encodeURIComponent(key)}`.length);
  const asked: View = rest.startsWith('/graph')
    ? 'graph'
    : rest.startsWith('/brief')
      ? 'brief'
      : rest.startsWith('/report')
        ? 'report'
        : rest.startsWith('/rail')
          ? 'rail'
          : 'chat';
  const base: string = `/projects/${encodeURIComponent(key)}`;
  if (rest.startsWith('/progress')) return <Navigate to={`${base}/brief${loc.search}`} replace />;
  const topics: SnapshotTopic[] = ownTopics(snap, p);
  const lead: SnapshotTopic | undefined = leadOf(snap, p);
  // 电脑上右栏常驻，“记忆与文件”只是对话；没有负责人那一路时也没有右栏
  const view: View = asked === 'rail' && (desktop || !lead) ? 'chat' : asked;
  // 报告、记忆与文件、简报有自己的头部，不画磁贴
  const bare: boolean = view === 'report' || view === 'rail' || view === 'brief';
  const m: ProjectMetrics = metrics(rep, p, topics);
  // 专项的胶囊：话题里最急的那件（话题按列表的颜色读，和专项一览、侧栏一致）；都不急时是专项自己的状态，灰色
  const { tone: pillTone, text: pillText } = projectPill(p, topics.map(listTone), lead);
  const started: string = m.startedAt ? `${new Date(m.startedAt * 1000).toDateString() === new Date().toDateString() ? '今天' : shortTime(m.startedAt).split(' ')[0]} ${hhmm(m.startedAt)} 起` : '';
  const selTopic: string | undefined = rest.startsWith('/t/') ? decodeURIComponent(rest.slice(3)) : undefined;
  return (
    <>
      <Head
        title={p.title}
        sub={<>{p.goal ? `目标：${projectNote(p)}` : projectNote(p)}</>}
        badge={<Pill tone={pillTone} text={pillText} big />}
        tags={undefined}
        back={desktop ? undefined : '/projects'}
        expand
        right={
          desktop ? (
            <>
              {p.counts.running ? <span className="t2" style={{ fontSize: 12 }}>{p.counts.running} 在做</span> : null}
              {started ? <span className="tag t">{started}</span> : null}
              <span style={{ width: 12 }} />
              <ProjectTabs base={base} view={view} />
            </>
          ) : undefined
        }
      />
      {isHalted(p) ? <HaltBar key={p.key} p={p} /> : <ProjectOps key={p.key} p={p} wrap />}
      {desktop ? null : <ProjectTabs base={base} view={view} mobile rail={!!lead} />}
      {view === 'chat' && !lead && !desktop ? null : bare ? null : desktop ? <MetricStrip m={m} topics={topics} /> : <MetricLine m={m} topics={topics} />}
      <div style={{ display: 'flex', flex: 1, minHeight: 0, marginTop: bare ? (view === 'brief' ? 8 : 0) : desktop ? 10 : 4 }}>
        {view === 'graph' ? (
          <ProjectGraph p={p} topics={topics} lead={lead} m={m} />
        ) : view === 'brief' ? (
          <ProjectBrief p={p} snap={snap} lead={lead} base={base} />
        ) : view === 'report' ? (
          <ProjectReport p={p} topics={topics} lead={lead} m={m} rep={rep} />
        ) : view === 'rail' ? (
          <ProjectRail p={p} topics={topics} mobile />
        ) : lead ? (
          <>
            {/* 手机上输入框旁还有加号、停止和发送，长占位折成两行把输入框撑高：只留前半句 */}
            <Conversation
              key={lead.key}
              topicKey={lead.key}
              mode="chat"
              who="负责人"
              room={{ lead: { key: lead.key, project: p.key } }}
              head={
                desktop ? (
                  <p className="t3 rm-lead-note">大厅里和这位负责人有关的部分；在这里说的话交给它，和在 <Link to="/butler">大厅</Link> 里 @ 它一样。</p>
                ) : (
                  // 手机上这句常驻在对话上面，两行太占地方：只留一行
                  <p className="t3 rm-lead-note">这里说的话交给负责人，和在 <Link to="/butler">大厅</Link> 里 @ 它一样</p>
                )
              }
              placeholder={desktop ? '对负责人说一句，它会协调这个专项' : '对负责人说一句'}
            />
            {desktop ? <PaneHandle spec={PROJECT_RAIL} /> : null}
            {desktop ? <ProjectRail p={p} topics={topics} /> : null}
          </>
        ) : (
          <Fallback topics={topics} sel={selTopic} desktop={desktop} />
        )}
      </div>
    </>
  );
};
export default ProjectPage;
