import React, { useEffect, useMemo, useRef, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { ChevronDown, ChevronUp } from 'lucide-react';
import { useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import type { LaunchData, LaunchModel, SnapshotTopic, SwitchPayload } from '@shared/api.interface';
import { newOpId, SNAPSHOT_KEY, turnsKey, useSettings } from '@client/src/hooks/use-workbench';
import { LaunchPanel, type PanelBox } from './LaunchPanel';
import { engineText } from './lib';
import { opWords } from './opWords';
import { sendOp, type OpResult } from './sendOp';
import { onOpenSwitch } from './switchOpen';
import { changedFields, fromConfig, switchBlock, type SwitchSel } from './switchConfig';
import './launch.css';
import './composer.css';

const FIELD_WORD: Record<string, string> = {
  model: '模型', effort: '思考预算', work_mode: '工作模式', workspace: '工作区', run_mode: '运行方式', redaction: '脱敏',
};
type Phase = 'idle' | 'sending' | 'failed';

/**
 * 话题页输入框下沿的配置栏（截图红框那行，T616）：“工作区 covey · Claude Code · Opus”。
 * 话题带 config（Covey v20）且设置里有开新话题的目录（launch）时，点开是和启动卡同样各行的面板，初值是话题现在的配置，
 * 「确认更换」发 switch，同飞书 🔁 换配置的确认；旧数据没有 config 时只是一行字。
 */
export const ConfigBar: React.FC<{ topic: SnapshotTopic | undefined; workspace: string; busy: boolean }> = ({ topic, workspace, busy }) => {
  const { data: settings } = useSettings();
  const data: LaunchData | undefined = settings?.data?.launch;
  const config = topic?.kind === 'topic' ? topic.config : undefined;
  const qc = useQueryClient();
  const [open, setOpen] = useState<boolean>(false);
  const [sel, setSel] = useState<SwitchSel | null>(null);
  const [phase, setPhase] = useState<Phase>('idle');
  const [message, setMessage] = useState<string>('');
  const alive = useRef<boolean>(true);
  const wrap = useRef<HTMLSpanElement | null>(null);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  const base: SwitchSel | null = useMemo(() => (data && config ? fromConfig(data, config) : null), [data, config]);
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

  const model: LaunchModel | undefined = data && config ? data.models.find((m: LaunchModel) => m.key === config.model) : undefined;
  const label: string = [
    (config?.workspace ?? workspace) ? `工作区 ${config?.workspace ?? workspace}` : '',
    model ? `${model.harness_title} · ${topic?.model_name || model.label}` : engineText(topic),
  ].filter(Boolean).join(' · ');
  if (!data || !config || !base) return <span className="t3 cfg-ro" style={{ fontSize: 12 }}>{label}</span>;

  const cur: SwitchSel = sel ?? base;
  const changed: string[] = changedFields(base, cur);
  const blocked: string = switchBlock(data, base, cur, busy);
  const box: PanelBox = {
    data,
    sel: cur,
    edit: (f) => setSel(f(data, cur)),
    setRedaction: (v: 'on' | 'off') => setSel({ ...cur, redaction: v }),
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
      const r: OpResult = await sendOp({ op_id: newOpId(), kind: 'switch', topic_key: topic.key, payload: { ...payload } }, undefined, () => !alive.current);
      if (r.phase !== 'done') {
        fail(opWords(r.phase, r.message));
        return;
      }
      void qc.invalidateQueries({ queryKey: SNAPSHOT_KEY });
      void qc.invalidateQueries({ queryKey: turnsKey(topic.key) });
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
          <span>改了{changed.map((k: string) => FIELD_WORD[k] ?? k).join('、')}：从下一句话起按新配置做（模型、工作区变了会开新会话，带上最近几轮）</span>
        ) : (
          <span>这是话题现在的配置，改哪项点哪项</span>
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
      <button type="button" className={`cfg-btn${open ? ' on' : ''}`} onClick={toggle} aria-expanded={open} title="换配置：Harness、模型、思考预算、工作区…" data-testid="config-bar">
        <span className="cfg-tx">{label}</span>
        {open ? <ChevronUp /> : <ChevronDown />}
      </button>
      {open ? (
        <div className="cfg-pop" role="dialog" aria-label="换配置">
          <div className="cfg-head">
            <b>换配置</b>
            <span className="t3">同飞书话题里的「换配置」</span>
          </div>
          <LaunchPanel box={box} className="flat" foot={foot} />
        </div>
      ) : null}
    </span>
  );
};
