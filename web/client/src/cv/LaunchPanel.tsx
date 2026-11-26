import React from 'react';
import { ChevronDown, ChevronUp } from 'lucide-react';
import type { LaunchDevice, LaunchModel, SettingsOption } from '@shared/api.interface';
import { useSettings } from '@client/src/hooks/use-workbench';
import {
  harnessOptions,
  pickKind,
  modelOptions,
  onDevice,
  pickHarness,
  pickModel,
  pickDevice,
  pickProvider,
  pickWorkspace,
  providerOptions,
  summaryTags,
  type LaunchBox,
} from './launch';
import { cycleRepo, deviceText, isRepoMode, MAX_REPOS, repoChoices, repoModeOf, showDevice, type RepoMode } from './launchRepos';
import './settings.css';
import './launch.css';

/** 一个选项是只读文字，其余一律下拉（和设置页「配置」同一套，规则在 launch.ts 的 pickKind） */
const Pick: React.FC<{
  label: string;
  options: SettingsOption[];
  value: string;
  onPick: (v: string) => void;
  disabled?: (v: string) => string;
}> = ({ label, options, value, onPick, disabled }) => {
  const kind = pickKind(options);
  if (kind === 'one') return <span className="st-one" title={options[0]?.text ?? value}>{options[0]?.text ?? value}</span>;
  return (
    <select className="st-sel" title={options.find((o: SettingsOption) => o.value === value)?.text} value={value} aria-label={label} onChange={(e: React.ChangeEvent<HTMLSelectElement>) => onPick(e.target.value)}>
      {options.some((o: SettingsOption) => o.value === value) ? null : <option value={value}>{value}</option>}
      {options.map((o: SettingsOption) => (
        <option key={o.value} value={o.value} title={disabled?.(o.value) || o.text} disabled={!!disabled?.(o.value)}>{o.text}</option>
      ))}
    </select>
  );
};

/** 面板只用到的那几样：开新话题的 LaunchBox 是，话题页换配置（v20）也拼得出。
 *  fixedPlace（v36，负责人的换配置）：不画工作区、运行方式两行，选择里照带原值（负责人留在它读的地方） */
export type PanelBox = Pick<LaunchBox, 'data' | 'sel' | 'edit' | 'setRedaction'> & { fixedPlace?: boolean };

/** 配置面板：飞书启动卡的各行，A 版展开时、B 版一直在；话题页换配置也用它（v20） */
export const LaunchPanel: React.FC<{ box: PanelBox; className?: string; foot?: React.ReactNode }> = ({ box, className, foot }) => {
  const { data, sel } = box;
  const m: LaunchModel | undefined = data.models.find((x: LaunchModel) => x.key === sel.model);
  const modes: SettingsOption[] = (m?.work_modes ?? []).map((v: string) => ({ value: v, text: m?.work_mode_texts?.[v] ?? v }));
  const device: boolean = onDevice(data, sel);
  const place: boolean = !box.fixedPlace;
  const repoMode: boolean = isRepoMode(data);
  // 新 Covey：仓库名单来自设置的 repos（出错或没有就不画仓库行）
  const { data: settings } = useSettings();
  const reposPage = settings?.data?.repos;
  const items = reposPage && 'items' in reposPage ? reposPage.items : [];
  const choices = repoMode && place ? repoChoices(items, sel.repos) : [];
  const devices: LaunchDevice[] = data.devices ?? [];
  const row = (label: string, body: React.ReactNode, note?: string): React.ReactNode => (
    <div className={`lx-r st-cell${['模型', '工作区', '仓库'].includes(label) ? ' wd' : ''}${label === '仓库' ? ' x2' : ''}`}>
      <div className="lx-l st-l">{label}</div>
      <div className="lx-c">
        {body}
        {note ? <div className="lx-n">{note}</div> : null}
      </div>
    </div>
  );
  return (
    <div className={`lx-panel${className ? ` ${className}` : ''}`}>
      <div className="st-gr cfg">
      {row('Harness', <Pick label="Harness" options={harnessOptions(data)} value={m?.harness ?? ''} onPick={(v: string) => box.edit((d, s) => pickHarness(d, s, v))} />)}
      {row('供应商', <Pick label="供应商" options={providerOptions(data, m?.harness ?? '')} value={m?.provider ?? ''} onPick={(v: string) => box.edit((d, s) => pickProvider(d, s, v))} />)}
      {row('模型', <Pick label="模型" options={modelOptions(data, m?.harness ?? '', m?.provider ?? '')} value={sel.model} onPick={(v: string) => box.edit((d, s) => pickModel(d, s, v))} />)}
      {row('思考预算', <Pick label="思考预算" options={m?.budgets ?? []} value={sel.effort} onPick={(v: string) => box.edit((_d, s) => ({ ...s, effort: v }))} />)}
      </div>
      {modes.length || place || m?.redaction ? (
      <div className="st-gr cfg">
      {modes.length ? row('工作模式', <Pick label="工作模式" options={modes} value={sel.work_mode} onPick={(v: string) => box.edit((_d, s) => ({ ...s, work_mode: v }))} />) : null}
      {place && !repoMode ? row(
        '工作区',
        <Pick
          label="工作区"
          options={(data.workspaces ?? []).map((w) => ({ value: w.name, text: w.device ? `${w.name}（${w.device}）` : w.name }))}
          value={sel.workspace ?? ''}
          onPick={(v: string) => box.edit((d, s) => pickWorkspace(d, s, v))}
        />,
      ) : null}
      {place && !repoMode ? row(
        '运行方式',
        <Pick label="运行方式" options={data.run_modes ?? []} value={device ? 'direct' : (sel.run_mode ?? '')} onPick={(v: string) => box.edit((_d, s) => ({ ...s, run_mode: v }))} disabled={(v: string) => (device && v === 'worktree' ? '设备上只能原目录' : '')} />,
        device ? '设备上只能原目录' : undefined,
      ) : null}
      {place && showDevice(data) ? row(
        '执行设备',
        <Pick label="执行设备" options={devices.map((dv: LaunchDevice) => ({ value: dv.name, text: deviceText(dv) }))} value={sel.device ?? devices[0]?.name ?? ''} onPick={(v: string) => box.edit((d, s) => pickDevice(d, s, v))} />,
      ) : null}
      {choices.length ? row(
        '仓库',
        <div className="lx-repos" role="group" aria-label="仓库">
          {choices.map((c) => {
            const mode: RepoMode = repoModeOf(sel.repos, c.name);
            const word: string = mode === 'write' ? '可写' : mode === 'read' ? '只读' : '不用';
            return (
              <button
                key={c.name}
                type="button"
                className={`lx-rp ${mode}`}
                aria-label={`${c.name}：${word}，点一下切换`}
                title={c.note || (c.readonly ? '只读仓库' : '点一下：不用 → 只读 → 可写')}
                onClick={() => box.edit((_d, s) => ({ ...s, repos: cycleRepo(s.repos, c.name, c.readonly) }))}
              >
                {c.name}
                {mode === 'none' ? null : <span className="lx-rm">{word}</span>}
              </button>
            );
          })}
        </div>,
        `默认不带仓库（从主目录起），最多 ${MAX_REPOS} 个`,
      ) : null}
      {m?.redaction
        ? row(
            '脱敏',
            <Pick label="敏感词脱敏" options={[{ value: 'off', text: '不脱敏' }, { value: 'on', text: '脱敏' }]} value={sel.redaction} onPick={(v: string) => box.setRedaction(v as 'on' | 'off')} />,
          )
        : null}
      </div>
      ) : null}
      {foot}
    </div>
  );
};

/** 输入框上沿一行：左边“交给管家 / 开新话题”，开新话题时是当前选择的小标签和“调整” */
export const LaunchLine: React.FC<{ box: LaunchBox }> = ({ box }) => {
  const fresh: boolean = box.mode === 'new';
  return (
    <div className="lx-line">
      <div className="lx-switch" role="radiogroup" aria-label="这句话交给谁">
        <button type="button" role="radio" aria-checked={!fresh} className={fresh ? '' : 'on'} onClick={() => box.setMode('butler')}>交给管家</button>
        <button type="button" role="radio" aria-checked={fresh} className={fresh ? 'on' : ''} onClick={() => box.setMode('new')}>开新话题</button>
      </div>
      {fresh ? (
        <>
          <div className="lx-tags">
            {summaryTags(box.data, box.sel).map((t: string, i: number) => (
              <span className="lx-tag" key={`${i}-${t}`}>{t}</span>
            ))}
          </div>
          <button type="button" className="lx-edit" aria-expanded={box.open} onClick={() => box.setOpen(!box.open)}>
            {box.open ? '收起' : '调整'}
            {box.open ? <ChevronUp /> : <ChevronDown />}
          </button>
        </>
      ) : null}
    </div>
  );
};

/** 发出后的一行：独立 worktree 的提示、回执、失败原因 */
export const LaunchNote: React.FC<{ box: LaunchBox }> = ({ box }) => {
  const worktree: boolean = !isRepoMode(box.data) && box.sel.run_mode === 'worktree' && !onDevice(box.data, box.sel);
  return (
    <>
      {worktree ? <div className="lx-hint">独立 worktree 要在飞书启动卡上点开始（建 worktree 只有启动卡能做）</div> : null}
      {box.phase === 'sending' ? <div className="lx-hint">正在开话题…</div> : null}
      {box.phase === 'failed' ? <div className="lx-hint bad" role="alert">{box.message}</div> : null}
      {box.phase === 'late' ? <div className="lx-hint" role="status">{box.message}</div> : null}
      {box.phase === 'done' && box.message ? <div className="lx-hint" role="status">{box.message}</div> : null}
    </>
  );
};
