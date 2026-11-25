import React, { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { ChevronDown, ChevronUp } from 'lucide-react';
import { useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import type { LaunchData, LaunchModel, SnapshotTopic, SwitchPayload } from '@shared/api.interface';
import { newOpId, useSettings } from '@client/src/hooks/use-workbench';
import { LaunchPanel, type PanelBox } from './LaunchPanel';
import { engineText } from './lib';
import { opWords } from './opWords';
import { sendOp, type OpResult } from './sendOp';
import { onOpenSwitch } from './switchOpen';
import { popPlace, POP_GAP, type PopPlace } from './popPlace';
import { changedFields, fromConfig, leadData, popRoom, switchBlock, type SwitchSel } from './switchConfig';
import './launch.css';
import './composer.css';

const FIELD_WORD: Record<string, string> = {
  model: '模型', effort: '思考预算', work_mode: '工作模式', workspace: '工作区', run_mode: '运行方式', redaction: '脱敏',
};
type Phase = 'idle' | 'sending' | 'failed';

/** 负责人改了配置以后怎样（Covey 只改脱敏时会话不变，别的都开新会话、重读专项的状态） */
const leadNext = (changed: string[]): string =>
  changed.every((k: string) => k === 'redaction') ? '从负责人下一轮起生效，会话不变' : '从负责人下一轮起按新配置做（开新会话，重新读一遍专项的状态）';

/**
 * 话题页输入框下沿的配置栏（截图红框那行，T616）：“工作区 covey · Claude Code · Opus”。
 * 话题带 config（Covey v20）且设置里有开新话题的目录（launch）时，点开是和启动卡同样各行的面板，初值是话题现在的配置，
 * 「确认更换」发 switch，同飞书 🔁 换配置的确认；旧数据没有 config 时只是一行字。
 * 专项负责人（kind=lead，Covey v36 起带 config）也用它，同飞书专项卡上的「换配置」：只列能当负责人的模型（bridge_tools），
 * 不画工作区、运行方式（payload 照带现在的值），从负责人下一轮起生效。管家不用它（管家的配置在设置的「配置」里）。
 */
export const ConfigBar: React.FC<{ topic: SnapshotTopic | undefined; workspace: string; busy: boolean }> = ({ topic, workspace, busy }) => {
  const { data: settings } = useSettings();
  const all: LaunchData | undefined = settings?.data?.launch;
  const lead: boolean = topic?.kind === 'lead';
  const config = topic?.kind === 'topic' || lead ? topic?.config : undefined;
  // 面板的目录：负责人只列能当负责人的模型（Harness、供应商、模型几行和联动都从它出）；普通话题原样
  const data: LaunchData | undefined = useMemo(() => (all && lead ? leadData(all) : all), [all, lead]);
  const qc = useQueryClient();
  const [open, setOpen] = useState<boolean>(false);
  const [sel, setSel] = useState<SwitchSel | null>(null);
  const [phase, setPhase] = useState<Phase>('idle');
  const [message, setMessage] = useState<string>('');
  const alive = useRef<boolean>(true);
  const wrap = useRef<HTMLSpanElement | null>(null);
  const pop = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  // 初值按整个目录补（负责人现在的模型不在负责人能用的里面时也认得出它，下面说清为什么不能确认）
  const base: SwitchSel | null = useMemo(() => (all && config ? fromConfig(all, config) : null), [all, config]);
  // 没成功的一轮上的「换个模型」（v33 how=switch）直接展开这里，不再让你去飞书点「换配置」；
  // 从看板点过来的带 ?switch=1，面板能用了就展开一次
  const live: boolean = !!base && !!topic;
  const loc = useLocation();
  const asked: boolean = new URLSearchParams(loc.search).get('switch') === '1';
  const [opened, setOpened] = useState<string>('');
  const show = (): void => {
    setSel(null);
    setPhase('idle');
    setMessage('');
    setOpen(true);
    window.requestAnimationFrame(() => wrap.current?.scrollIntoView({ block: 'nearest' }));
  };
  useEffect(() => {
    if (!live || !topic) return undefined;
    return onOpenSwitch(topic.key, show);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [live, topic?.key]);
  useEffect(() => {
    if (live && asked && topic && opened !== `${loc.key}:${topic.key}`) {
      setOpened(`${loc.key}:${topic.key}`);
      show();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [live, asked, topic?.key, loc.key]);
  // 面板放在哪（T789）：按输入框（手机是配置栏那一行 .mcfg）的框固定定位，不受对话区 overflow 裁切；输入框长高、窗口变、滚动时重算
  const [place, setPlace] = useState<PopPlace | null>(null);
  useLayoutEffect(() => {
    if (!open) {
      setPlace(null);
      return undefined;
    }
    const host: HTMLElement | null = wrap.current?.closest<HTMLElement>('.composer, .mcfg') ?? null;
    if (!host) return undefined;
    const gap: number = host.classList.contains('mcfg') ? 6 : POP_GAP;
    const fit = (): void => {
      const next: PopPlace = popPlace(host.getBoundingClientRect(), window.innerHeight, gap);
      setPlace((cur: PopPlace | null) => (cur && cur.left === next.left && cur.width === next.width && cur.bottom === next.bottom && cur.room === next.room ? cur : next));
    };
    fit();
    const ro: ResizeObserver | null = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(fit);
    ro?.observe(host);
    window.addEventListener('resize', fit);
    window.addEventListener('scroll', fit, true);
    return () => {
      ro?.disconnect();
      window.removeEventListener('resize', fit);
      window.removeEventListener('scroll', fit, true);
    };
  }, [open]);
  // 点面板外面、按 Esc 收起（发送中不收，免得回执没人看）
  useEffect(() => {
    if (!open) return undefined;
    const away = (e: MouseEvent): void => {
      if (phase !== 'sending' && wrap.current && !wrap.current.contains(e.target as Node)) setOpen(false);
    };
    const esc = (e: KeyboardEvent): void => {
      if (e.key === 'Escape' && phase !== 'sending') setOpen(false);
    };
    document.addEventListener('mousedown', away);
    document.addEventListener('keydown', esc);
    return () => {
      document.removeEventListener('mousedown', away);
      document.removeEventListener('keydown', esc);
    };
  }, [open, phase]);
  // 面板往上长，最高只到对话区上沿（再往上被裁掉、被话题头盖住，T97）：开着时量一次，窗口、输入框、对话区变了再量
  useLayoutEffect(() => {
    if (!open) return undefined;
    const area: Element | null | undefined = wrap.current?.closest('.conv');
    const fit = (): void => {
      if (pop.current && area) pop.current.style.setProperty('--cfg-room', `${popRoom(pop.current.getBoundingClientRect().bottom, area.getBoundingClientRect().top)}px`);
    };
    fit();
    window.addEventListener('resize', fit);
    const ro: ResizeObserver | null = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(fit);
    const anchor: Element | null | undefined = pop.current?.offsetParent;
    if (ro && area) ro.observe(area);
    if (ro && anchor) ro.observe(anchor);
    return () => {
      window.removeEventListener('resize', fit);
      ro?.disconnect();
    };
  }, [open]);

  const model: LaunchModel | undefined = all && config ? all.models.find((m: LaunchModel) => m.key === config.model) : undefined;
  const label: string = [
    (config?.workspace ?? workspace) ? `工作区 ${config?.workspace ?? workspace}` : '',
    model ? `${model.harness_title} · ${topic?.model_name || model.label}` : engineText(topic),
  ].filter(Boolean).join(' · ');
  if (!all || !data || !config || !base) return <span className="t3 cfg-ro" style={{ fontSize: 12 }}>{label}</span>;

  const cur: SwitchSel = sel ?? base;
  const changed: string[] = changedFields(base, cur);
  const blocked: string = switchBlock(all, base, cur, busy, lead);
  const box: PanelBox = {
    data,
    sel: cur,
    edit: (f) => setSel(f(data, cur)),
    setRedaction: (v: 'on' | 'off') => setSel({ ...cur, redaction: v }),
    ...(lead ? { fixedPlace: true } : {}),
  };
  const toggle = (): void => {
    if (!open) {
      setSel(null);
      setPhase('idle');
      setMessage('');
    }
    setOpen(!open);
  };
  const confirm = (): void => {
    if (!topic || blocked || !changed.length || phase === 'sending') return;
    const payload: SwitchPayload = { ...cur };
    setPhase('sending');
    setMessage('');
    void (async (): Promise<void> => {
      const fail = (m: string): void => {
        if (!alive.current) return;
        setPhase('failed');
        setMessage(m);
      };
      const r: OpResult = await sendOp({ op_id: newOpId(), kind: 'switch', topic_key: topic.key, payload: { ...payload } }, qc, undefined, () => !alive.current);
      if (r.phase !== 'done') {
        fail(opWords(r.phase, r.message));
        return;
      }
      // 回执后跟踪器已经取了这个话题的轮次和快照（opTrack.pullPlan）
      toast.success(opWords('done', r.message || '已换配置'));
      if (alive.current) {
        setPhase('idle');
        setSel(null);
        setOpen(false);
      }
    })();
  };
  const foot = (
    <div className="cfg-foot">
      <div className="cfg-note">
        {phase === 'failed' ? (
          <span className="bad" role="alert">{message}</span>
        ) : phase === 'sending' ? (
          <span>正在换…</span>
        ) : blocked ? (
          <span className={busy ? 'warn' : 'bad'}>{blocked}</span>
        ) : changed.length ? (
          <span>改了{changed.map((k: string) => FIELD_WORD[k] ?? k).join('、')}：{lead ? leadNext(changed) : '从下一句话起按新配置做（模型、工作区变了会开新会话，带上最近几轮）'}</span>
        ) : (
          <span>{lead ? '这是负责人现在的配置，改哪项点哪项' : '这是话题现在的配置，改哪项点哪项'}</span>
        )}
      </div>
      <button type="button" className="btn sm" onClick={() => setOpen(false)} disabled={phase === 'sending'}>取消</button>
      <button
        type="button"
        className="btn sm pri"
        onClick={confirm}
        disabled={!!blocked || !changed.length || phase === 'sending'}
        data-testid="switch-confirm"
      >
        确认更换
      </button>
    </div>
  );
  return (
    <span className="cfg" ref={wrap}>
      <button type="button" className={`cfg-btn${open ? ' on' : ''}`} onClick={toggle} aria-expanded={open} title={lead ? '换负责人的配置：Harness、模型、思考预算' : '换配置：Harness、模型、思考预算、工作区…'} data-testid="config-bar">
        <span className="cfg-tx">{label}</span>
        {open ? <ChevronUp /> : <ChevronDown />}
      </button>
      {open ? (
        <div
          ref={pop}
          className={`cfg-pop${place ? ' fixed' : ''}`}
          role="dialog"
          aria-label={lead ? '换负责人的配置' : '换配置'}
          style={place ? ({ left: place.left, width: place.width, bottom: place.bottom, '--room': `${place.room}px` } as React.CSSProperties) : undefined}
        >
          <div className="cfg-head">
            <b>{lead ? '换负责人的配置' : '换配置'}</b>
            <span className="t3">{lead ? '同飞书专项卡上的「换配置」' : '同飞书话题里的「换配置」'}</span>
          </div>
          <LaunchPanel box={box} className="flat" foot={foot} />
        </div>
      ) : null}
    </span>
  );
};
