import React from 'react';
import { Bot, Circle, FileText, Globe, Lightbulb, Pencil, Search, Terminal } from 'lucide-react';
import type { StepView } from '@shared/api.interface';
import { fmtShort, STEP_CLS } from './lib';
import { useTick } from './ui';

const ICON: Record<string, React.ReactNode> = {
  read: <FileText />, edit: <Pencil />, command: <Terminal />, search: <Search />, subagent: <Bot />, think: <Lightbulb />, web: <Globe />, other: <Circle />,
};
/** 图例：按条形的颜色分，只列这一轮出现过的 */
const LEGEND: [string, string, string][] = [
  ['读', 'read', '#4d7cff'], ['改', 'write', '#2fb88a'], ['命令', 'bash', '#e09b2d'], ['子任务', 'sub', '#a06bff'], ['网页', 'web', '#26b5c9'],
  ['思考', 'think', '#6b7186'], ['其他', '', 'var(--stop)'],
];
/** 图标已经说了是什么的标题：行里只写内容（“执行命令：ls” 只写 “ls”） */
const SAID_BY_ICON: Set<string> = new Set(['读取文件', '修改文件', '写入文件', '执行命令', '查找文件', '搜索文件', '读取网页', '搜索网页', '分配子任务', '子任务']);
/** 这些标题不写进名字，改成名字后的小标签（“后台命令：正式部署阶段 2（后台）” 写成 “正式部署阶段 2 [后台]”） */
const AS_TAG: Record<string, string> = { 后台命令: '后台', 启动后台命令: '后台', 更新检查点: '检查点', 浏览目录: '目录' };
const NICE: number[] = [1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200, 14400];
/** 超过这么多步，把短的合成一行 */
const ROWS = 15;

const axisLabel = (s: number): string => (s === 0 ? '0' : s % 3600 === 0 ? `${s / 3600} 小时` : s >= 60 ? `${Math.round(s / 60)} 分` : `${s} 秒`);
/** 旧版 Covey 推的是卡片用的转义文本（&amp;、COVEY\_CORE）；服务端已还原实体，这里再还原一次反斜杠和漏网的实体 */
const plain = (s: string): string =>
  s
    .replace(/\\([`*_[\]\\])/gu, '$1')
    .replace(/&lt;/gu, '<')
    .replace(/&gt;/gu, '>')
    .replace(/&quot;/gu, '"')
    .replace(/&#x27;|&#39;/gu, "'")
    .replace(/&amp;/gu, '&')
    .replace(/&[#a-z0-9]{2,6}$/iu, '…'); // 旧版截到 80 字时可能截在实体中间（“&amp”）
const clock = (sec: number | null): string =>
  sec ? new Date(sec * 1000).toLocaleTimeString('zh-CN', { hour12: false, timeZone: 'Asia/Shanghai' }) : '';

export interface StepParts {
  /** 行里写的名字 */
  name: string;
  /** 名字后的小标签：后台、检查点 */
  tag: string;
  /** 步骤标题：执行命令、读取文件 */
  verb: string;
  /** 点开才显示的：命令，或完整路径、完整名字 */
  more: string;
}

/** 一行写什么：标题变成图标或小标签，名字只写目的，命令和完整路径放到点开以后（Covey v18 推 detail；旧版从 label 的“目的 · 命令”拆） */
export function stepParts(s: StepView): StepParts {
  const label: string = plain(s.label);
  const m: RegExpMatchArray | null = s.kind === 'other' ? null : label.match(/^([^：·\s]{2,8})：(.*)$/su);
  const verb: string = m ? m[1] : '';
  let rest: string = m ? m[2] : label;
  let more: string = s.detail ? plain(s.detail) : '';
  const cut: number = rest.indexOf(' · ');
  if (cut > 0) {
    more = more || rest.slice(cut + 3);
    rest = rest.slice(0, cut);
  }
  const tag: string = AS_TAG[verb] ?? '';
  let name: string = (m && !SAID_BY_ICON.has(verb) && !tag ? `${verb}：${rest}` : rest).trim();
  if (tag === '后台') name = name.replace(/\s*[（(]后台[)）]$/u, '');
  if (/^\/\S+$/u.test(name)) {
    const parts: string[] = name.split('/').filter(Boolean);
    if (parts.length > 2) {
      more = more || name;
      name = `…/${parts.slice(-2).join('/')}`;
    }
  }
  return { name: name || label, tag, verb, more };
}

/** 一行的纯文字（合并行的悬停提示等） */
export function stepText(s: StepView): string {
  return stepParts(s).name;
}

interface Row {
  s: StepView;
  st: number;
  en: number;
  run: boolean;
}

/**
 * 过程瀑布：每步一行，在跑的条带扫光，“现在”线随时间走；步骤多时把短的合成一行。
 * 宽屏左列随宽度走、名字最多两行；窄屏（<768px）名字占一整行、下面一条细时间轴（covey.css .wfg-wrap）。
 * 点一行展开完整名字、命令、开始和结束时间、用时。
 */
export const Waterfall: React.FC<{ steps: StepView[]; live: boolean; rows?: number }> = ({ steps, live, rows = ROWS }) => {
  const now: number = useTick(live ? 1000 : 3600000);
  const [open, setOpen] = React.useState<string>('');
  const shown: StepView[] = steps.filter((s: StepView) => s.started_at);
  if (!shown.length) return null;
  const t0: number = Math.min(...shown.map((s: StepView) => s.started_at ?? now));
  const all: Row[] = shown.map((s: StepView) => {
    const run: boolean = s.status === 'running';
    const st: number = (s.started_at ?? t0) - t0;
    const en: number = Math.max(st, (s.ended_at ?? (run ? now : (s.started_at ?? t0))) - t0);
    return { s, st, en, run };
  });
  const tEnd: number = Math.max(...all.map((r: Row) => r.en), live ? now - t0 : 0);
  const span: number = Math.max(tEnd, 8);
  const step: number = NICE.find((n: number) => span / n <= 6) ?? 14400;
  const ticks: number[] = [];
  for (let v = 0; v <= span; v += step) ticks.push(v);
  const pct = (v: number): number => Math.min(100, Math.max(0, (v / span) * 100));

  // 在跑的、失败的、子任务一定单列；其余按时长从长到短补满 rows 行，剩下的合成一行
  let kept: Row[] = all;
  let folded: Row[] = [];
  if (all.length > rows) {
    const must = (r: Row): boolean => r.run || r.s.status === 'failed' || r.s.kind === 'subagent';
    const room: number = Math.max(0, rows - 1 - all.filter(must).length);
    const longest: Set<Row> = new Set(all.filter((r: Row) => !must(r)).sort((a: Row, b: Row) => b.en - b.st - (a.en - a.st)).slice(0, room));
    kept = all.filter((r: Row) => must(r) || longest.has(r));
    folded = all.filter((r: Row) => !must(r) && !longest.has(r));
  }
  const foldedSec: number = folded.reduce((n: number, r: Row) => n + (r.en - r.st), 0);
  const kinds: Set<string> = new Set(all.map((r: Row) => STEP_CLS[r.s.kind] ?? ''));
  const grid = (): React.ReactNode => ticks.map((v: number) => <i key={v} className="gl" style={{ left: `${pct(v)}%` }} />);
  const bar = (r: Row, extra = ''): React.ReactNode => (
    <i
      key={r.s.id ?? `${r.st}`}
      className={`bb ${STEP_CLS[r.s.kind] ?? ''}${r.run ? ' live' : ''}${r.s.status === 'failed' ? ' fail' : ''}${extra}`}
      title={extra ? `${stepText(r.s)} · ${fmtShort(r.en - r.st)}` : undefined}
      style={{ left: `${pct(r.st)}%`, width: `${Math.max(pct(r.en) - pct(r.st), 0.6)}%`, ...(r.s.status === 'failed' ? { background: 'var(--fail)' } : null) }}
    />
  );
  const detail = (r: Row, p: StepParts): React.ReactNode => (
    <div className="wfd">
      <div className="wfd-n">{p.name.startsWith('…/') && p.more ? p.more : p.name}</div>
      {p.more && !(p.name.startsWith('…/') && p.more) ? <code className="wfd-c">{p.more}</code> : null}
      <div className="wfd-m">
        {clock(r.s.started_at)} → {r.run ? '现在' : clock(r.s.ended_at)}
        <span className="sep">｜</span>
        {r.run ? `已跑 ${fmtShort(r.en - r.st)}` : `用时 ${fmtShort(r.en - r.st)}`}
        {p.verb ? (
          <>
            <span className="sep">｜</span>
            {p.verb}
          </>
        ) : null}
        {r.s.status === 'failed' ? (
          <>
            <span className="sep">｜</span>
            <span className="wfd-f">失败</span>
          </>
        ) : null}
      </div>
    </div>
  );
  return (
    <div className="wfg-wrap" style={{ position: 'relative' }}>
      <div className={`wfax${ticks.length > 4 ? ' dense' : ''}`}>
        <div />
        <div>
          {ticks.map((v: number, i: number) => (
            <span key={v} className={pct(v) > 94 ? 'end' : v === 0 ? 'zero' : i % 2 ? 'odd' : undefined} style={{ left: `${pct(v)}%` }}>{axisLabel(v)}</span>
          ))}
        </div>
      </div>
      <div className="wfrows">
        {kept.map((r: Row, i: number) => {
          const key: string = r.s.id ?? String(i);
          const on: boolean = open === key;
          const p: StepParts = stepParts(r.s);
          const toggle = (): void => setOpen(on ? '' : key);
          return (
            <React.Fragment key={key}>
              <div
                className={`wfg pick${on ? ' on' : ''}`}
                role="button"
                tabIndex={0}
                aria-expanded={on}
                onClick={toggle}
                onKeyDown={(e: React.KeyboardEvent) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    toggle();
                  }
                }}
              >
                <div className={`lb${r.run ? ' live' : ''}`}>
                  {ICON[r.s.kind] ?? ICON.other}
                  <span className="tx">{p.name}</span>
                  {p.tag ? <span className="wft">{p.tag}</span> : null}
                  <em>{r.run ? '在跑' : fmtShort(r.en - r.st)}</em>
                </div>
                <div className="wfa">
                  {grid()}
                  {bar(r)}
                </div>
              </div>
              {on ? detail(r, p) : null}
            </React.Fragment>
          );
        })}
        {folded.length ? (
          <div className="wfg wfmore">
            <div className="lb" title="时长较短的步骤合在这一行，条形是它们各自的位置">
              <span className="tx">另有 {folded.length} 个短步骤</span>
              <em>共 {fmtShort(foldedSec)}</em>
            </div>
            <div className="wfa">
              {grid()}
              {folded.map((r: Row) => bar(r, ' mini'))}
            </div>
          </div>
        ) : null}
        {live ? (
          <div className="wfnow">
            <i className="nowl" style={{ left: `${pct(now - t0)}%`, top: 0 }} />
          </div>
        ) : null}
      </div>
      <div className="lgd">
        {LEGEND.filter(([, c]: [string, string, string]) => kinds.has(c)).map(([n, c, col]: [string, string, string]) => (
          <span key={c || 'other'} style={{ ['--cc' as string]: col }}>
            <i />
            {n}
          </span>
        ))}
        <span className="lgd-tip">点一行看详情</span>
      </div>
    </div>
  );
};
