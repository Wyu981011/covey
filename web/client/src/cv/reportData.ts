import type { ReportQuestion, ReportResponse, ReportTurn, SnapshotTopic } from '@shared/api.interface';

/** 专项报告要画的东西，全部从 /api/projects/:key/report 和快照里的话题算出来（纯函数，不碰页面） */

export interface Round {
  n: number;
  s: number;
  e: number;
  live: boolean;
  hold: boolean;
  failed: boolean;
  /** 前一轮没做成，这一轮是重来 */
  rework: boolean;
  seconds: number;
  turn: ReportTurn;
}
export interface Mark {
  at: number;
  text: string;
}
export interface Lane {
  key: string;
  label: string;
  title: string;
  lead: boolean;
  state: string;
  rounds: Round[];
  /** 你交代或拍板：你说的话、你答问题的时刻 */
  said: number[];
  /** 负责人替你答了题的时刻 */
  leadSaid: number[];
  /** 交付：有产物的一轮结束时 */
  delivered: Mark[];
  /** 问题等你的那段：问到答（或关掉）；还在等的到现在 */
  waits: { s: number; e: number; open: boolean }[];
  /** 在跑的一轮按预计什么时候做完 */
  due: number | null;
  /** 专项开始前就结束的轮次（话题是后来挂进专项的）：不画、不算，只在行首说一句 */
  earlier: number;
}
export interface Plan {
  key: string;
  label: string;
  /** 有预计的那几轮：预计合计、实际合计（秒） */
  plan: number;
  act: number;
  /** 这个话题全部轮次的实际用时 */
  total: number;
  live: boolean;
  failed: boolean;
}
export interface ReportModel {
  lanes: Lane[];
  t0: number;
  t1: number;
  rounds: Round[];
  plans: Plan[];
  /** 专项里问过的题（含负责人代答、关掉的） */
  questions: ReportQuestion[];
  /** 现在还在等你的题（state open，和看板的“等你”同一个来源） */
  waiting: ReportQuestion[];
  /** 你答过的题各等了多久（秒）：平均等你多久用它 */
  answeredWaits: number[];
  /** 负责人替你答的题数 */
  leadAnswered: number;
  /** 同一时刻最多几个话题在跑 */
  parallel: number;
  reworks: Round[];
  work: number;
  tokens: number;
  input: number;
  output: number;
  cachePct: number | null;
  /** 按时间切 12 段的累计曲线，给磁贴底部 */
  series: { work: number[]; tokens: number[]; wait: number[]; rework: number[]; questions: number[]; span: number[] };
}

const BUCKETS = 12;
/** 你自己答的（答了、只发补充说明、每题都选了不回答）：画成“你交代或拍板” */
const BY_OWNER = new Set(['owner', 'feedback', 'skipped']);

/** 题目现在还等不等你：Covey 推的 state 为准（open 才算）；没有 state 的旧数据按有没有答题时间算 */
export const isWaiting = (q: ReportQuestion): boolean => (q.state ? q.state === 'open' : !q.answered_at);
/** 题目不再等的时刻：Covey 推的 closed_at，旧推送退回 answered_at；不知道为 null */
export const closedAt = (q: ReportQuestion): number | null => q.closed_at ?? q.answered_at ?? null;
/** 谁关的：旧推送没有 closed_by，有答题时间的当作你答的 */
const closedBy = (q: ReportQuestion): string => q.closed_by || (q.state === 'answered' || (!q.state && q.answered_at) ? 'owner' : '');

/** 缓存命中：缓存读 ÷ 输入。Covey 推的 input 已经含缓存读，和任务卡的“缓存命中”、看板的本周用量同一个公式 */
export function cacheShare(cache: number, input: number): number | null {
  return input > 0 ? Math.min(100, Math.round((cache / input) * 100)) : null;
}
const ENDED = new Set(['done', 'failed', 'stopped', 'interrupted', 'cancelled']);

function endOf(t: ReportTurn, now: number): number {
  if (t.status === 'running' || t.status === 'waiting') return now;
  if (t.ended_at && t.ended_at >= (t.started_at ?? 0)) return t.ended_at;
  return (t.started_at ?? now) + (t.seconds || 5);
}

/** 累计曲线：events 是 (时刻, 量)，在 [t0, t1] 上切 BUCKETS 段，每段末尾的累计值 */
function cumulative(events: [number, number][], t0: number, t1: number): number[] {
  const span: number = Math.max(t1 - t0, 1);
  const out: number[] = [];
  for (let i = 1; i <= BUCKETS; i++) {
    const edge: number = t0 + (span * i) / BUCKETS;
    out.push(events.reduce((sum: number, [at, v]: [number, number]) => sum + (at <= edge ? v : 0), 0));
  }
  return out;
}

/** 一个话题从什么时候算进专项：专项开始和它加入（Covey v13 joined_at）里晚的那个，和专项卡的 token 同一个口径 */
export function sinceOf(since: number | null, topic: Pick<SnapshotTopic, 'joined_at'> | undefined): number | null {
  const joined: number | null = topic?.joined_at && topic.joined_at > 0 ? topic.joined_at : null;
  if (since === null) return joined;
  return joined === null ? since : Math.max(since, joined);
}

/** since：专项开始的时刻。挂进专项的已有话题带着它以前的轮次，那些不是这个专项的活，不画也不算；
 * 后来加入的话题（joined_at）从它加入时算起 */
export function buildReport(rep: ReportResponse | undefined, topics: SnapshotTopic[], lead: SnapshotTopic | undefined, now: number, since: number | null = null): ReportModel {
  const turns: ReportTurn[] = [...(rep?.turns ?? [])].sort((a, b) => (a.started_at ?? 0) - (b.started_at ?? 0) || a.seq - b.seq);
  const topicSince = new Map<string, number | null>(topics.map((t: SnapshotTopic) => [t.key, sinceOf(since, t)]));
  const laneSince = (key: string): number | null => (topicSince.has(key) ? (topicSince.get(key) ?? null) : since);
  // 话题算进专项以前就不等了的题不算（挂进来的话题带着以前的题）
  const questions: ReportQuestion[] = (rep?.questions ?? []).filter((q: ReportQuestion) => {
    const from: number | null = laneSince(q.topic_key);
    if (!from || isWaiting(q)) return true;
    const end: number | null = closedAt(q) ?? q.asked_at;
    return end === null || end >= from;
  });
  const byKey = new Map<string, Lane>();
  const laneFor = (key: string, label: string, title: string, isLead: boolean, state: string): Lane => {
    let lane: Lane | undefined = byKey.get(key);
    if (!lane) {
      lane = { key, label, title, lead: isLead, state, rounds: [], said: [], leadSaid: [], delivered: [], waits: [], due: null, earlier: 0 };
      byKey.set(key, lane);
    }
    return lane;
  };
  // 先放负责人，再放话题（按 T 号），这样没有轮次的话题也有一行
  if (lead) laneFor(lead.key, '负责人', '', true, lead.state);
  [...topics].sort((a, b) => a.number - b.number).forEach((t: SnapshotTopic) => laneFor(t.key, `T${t.number}`, t.title, false, t.state));
  for (const t of turns) {
    const isLead: boolean = t.kind === 'lead';
    const lane: Lane = laneFor(t.topic_key, isLead ? '负责人' : `T${t.number ?? ''}`, t.title, isLead, '');
    if (t.role === 'owner') {
      if (t.started_at) lane.said.push(t.started_at);
      continue;
    }
    if (!t.started_at) continue;
    const prev: Round | undefined = lane.rounds[lane.rounds.length - 1];
    const failed: boolean = t.status === 'failed' || t.status === 'interrupted';
    const live: boolean = t.status === 'running';
    const hold: boolean = t.status === 'waiting';
    const e: number = endOf(t, now);
    // 从历史里来的轮次 Covey 推的开始和结束是同一刻（只知道结束）：用这一轮的用时往回推，不然每轮都缩成一个点
    const s: number = !live && !hold && t.seconds > 0 && t.started_at >= e - 1 ? e - t.seconds : t.started_at;
    const r: Round = {
      n: lane.rounds.length + 1,
      s,
      e,
      live,
      hold,
      failed,
      rework: !!prev && (prev.failed || prev.turn.status === 'stopped'),
      seconds: t.seconds || (ENDED.has(t.status) || live || hold ? Math.max(0, e - t.started_at) : 0),
      turn: t,
    };
    lane.rounds.push(r);
    if (t.artifacts > 0 && !live && !hold) lane.delivered.push({ at: e, text: t.artifact ? `交付 ${t.artifact}` : `交付 ${t.artifacts} 个产物` });
    if (live && t.estimate_seconds) lane.due = t.started_at + t.estimate_seconds;
  }
  // 等你：只有还开着的题等到现在；关掉的题等到关掉那一刻。负责人先接手（held）、替你答（lead）的题没等过你
  const answeredWaits: number[] = [];
  let leadAnswered = 0;
  for (const q of questions) {
    const lane: Lane | undefined = byKey.get(q.topic_key);
    const by: string = closedBy(q);
    const end: number | null = closedAt(q);
    if (by === 'lead') {
      leadAnswered += 1;
      if (lane && end) lane.leadSaid.push(end);
      continue;
    }
    if (!lane || !q.asked_at || q.state === 'held') continue;
    if (isWaiting(q)) {
      lane.waits.push({ s: q.asked_at, e: now, open: true });
      continue;
    }
    if (end === null || end < q.asked_at) continue;
    lane.waits.push({ s: q.asked_at, e: end, open: false });
    if (BY_OWNER.has(by)) {
      lane.said.push(end);
      answeredWaits.push(end - q.asked_at);
    }
  }
  const lanes: Lane[] = [...byKey.values()];
  // 网页库里偶尔留着一条早就不在跑的“在跑”轮次（后面已经有新的一轮）：后面有轮次的，按下一轮开始时结束
  for (const l of lanes) {
    l.rounds.forEach((r: Round, i: number) => {
      const next: Round | undefined = l.rounds[i + 1];
      if (next && (r.live || r.hold)) {
        r.live = false;
        r.hold = false;
        r.e = Math.max(r.s, Math.min(r.e, next.s));
        r.seconds = r.turn.seconds || r.e - r.s;
      }
    });
    if (!l.rounds.some((r: Round) => r.live)) l.due = null;
  }
  for (const l of lanes) {
    const from: number | null = laneSince(l.key);
    if (!from) continue;
    const kept: Round[] = l.rounds.filter((r: Round) => r.e >= from);
    l.earlier = l.rounds.length - kept.length;
    l.rounds = kept;
    l.said = l.said.filter((at: number) => at >= from);
    l.leadSaid = l.leadSaid.filter((at: number) => at >= from);
    l.delivered = l.delivered.filter((d: Mark) => d.at >= from);
    l.waits = l.waits.filter((w) => w.e >= from);
  }
  const rounds: Round[] = lanes.flatMap((l: Lane) => l.rounds);
  const stamps: number[] = [
    ...rounds.flatMap((r: Round) => [r.s, r.e]),
    ...lanes.flatMap((l: Lane) => [...l.said, ...l.waits.map((w) => w.s)]),
  ];
  const first: number = stamps.length ? Math.min(...stamps) : now - 3600;
  const t0: number = since ? Math.max(first, since) : first;
  const dues: number[] = lanes.map((l: Lane) => l.due ?? 0);
  const t1: number = Math.max(now, ...stamps, ...dues);
  // 同时在跑的话题数：只算话题，不算负责人
  const edges: [number, number][] = rounds.filter((r: Round) => r.turn.kind !== 'lead').flatMap((r: Round): [number, number][] => [[r.s, 1], [r.e, -1]]);
  edges.sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  let cur = 0;
  let parallel = 0;
  for (const [, d] of edges) {
    cur += d;
    parallel = Math.max(parallel, cur);
  }
  const topicRounds: Round[] = rounds.filter((r: Round) => r.turn.kind !== 'lead');
  const work: number = topicRounds.reduce((s: number, r: Round) => s + r.seconds, 0);
  let tokens = 0;
  let output = 0;
  let cache = 0;
  let fed = 0;
  for (const r of rounds) {
    const u = r.turn.usage;
    tokens += u?.total ?? 0;
    output += u?.output ?? 0;
    cache += u?.cache_read ?? 0;
    fed += u?.input ?? 0;
  }
  const plans: Plan[] = lanes
    .filter((l: Lane) => !l.lead && l.rounds.length)
    .map((l: Lane): Plan => {
      const est: Round[] = l.rounds.filter((r: Round) => (r.turn.estimate_seconds ?? 0) > 0);
      return {
        key: l.key,
        label: l.label,
        plan: est.reduce((s: number, r: Round) => s + (r.turn.estimate_seconds ?? 0), 0),
        act: est.reduce((s: number, r: Round) => s + r.seconds, 0),
        total: l.rounds.reduce((s: number, r: Round) => s + r.seconds, 0),
        live: l.rounds.some((r: Round) => r.live),
        failed: l.rounds.some((r: Round) => r.failed),
      };
    });
  const reworks: Round[] = rounds.filter((r: Round) => r.rework);
  return {
    lanes,
    t0,
    t1,
    rounds,
    plans,
    questions,
    waiting: questions.filter(isWaiting),
    answeredWaits,
    leadAnswered,
    parallel,
    reworks,
    work,
    tokens,
    input: tokens - output,
    output,
    cachePct: cacheShare(cache, fed),
    series: {
      span: cumulative(rounds.map((r: Round): [number, number] => [r.e, 1]), t0, t1),
      work: cumulative(topicRounds.map((r: Round): [number, number] => [r.e, r.seconds]), t0, t1),
      tokens: cumulative(rounds.map((r: Round): [number, number] => [r.e, r.turn.usage?.total ?? 0]), t0, t1),
      wait: cumulative(lanes.flatMap((l: Lane) => l.waits.map((w): [number, number] => [w.e, w.e - w.s])), t0, t1),
      rework: cumulative(reworks.map((r: Round): [number, number] => [r.s, 1]), t0, t1),
      questions: cumulative(questions.filter((q) => q.asked_at).map((q): [number, number] => [q.asked_at ?? now, 1]), t0, t1),
    },
  };
}

/** 时间轴的刻度：按跨度挑 5/10/15/30/60/120… 分钟一格，对齐整点 */
export function ticks(t0: number, t1: number): number[] {
  const span: number = Math.max(t1 - t0, 60);
  const steps: number[] = [300, 600, 900, 1800, 3600, 7200, 10800, 21600, 43200, 86400];
  const step: number = steps.find((s: number) => span / s <= 6) ?? 86400;
  const out: number[] = [];
  for (let v = Math.ceil(t0 / step) * step; v <= t1; v += step) out.push(v);
  return out;
}
