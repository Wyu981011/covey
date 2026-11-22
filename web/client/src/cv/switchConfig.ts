/**
 * 话题页换配置（Covey 数据约定 v20，T616）的纯函数：面板的初值、和话题现在的配置比有没有变化、什么情况网页上换不了。
 * 不碰 DOM、不引别的模块（只有类型）：防回归 scripts/switch-config.test.mjs。
 */
import type { LaunchData, LaunchModel, LaunchPreselect, TopicConfig } from '@shared/api.interface';

export type SwitchSel = LaunchPreselect;

export const SWITCH_FIELDS = ['model', 'effort', 'work_mode', 'workspace', 'run_mode', 'redaction'] as const;

/** 面板的初值：话题的配置，补成这个模型能选的（预算不在列表里取 start_budget，工作模式不在取第一个，不能脱敏的模型脱敏视为 off）。
 *  模型不在目录里（目录变了）原样留着：面板上那一行显示原值，要重选模型才能确认 */
export function fromConfig(d: LaunchData, c: TopicConfig): SwitchSel {
  const m: LaunchModel | undefined = d.models.find((x: LaunchModel) => x.key === c.model);
  if (!m) return { ...c };
  const effort: string = m.budgets.some((b) => b.value === c.effort) ? c.effort : m.start_budget;
  const work_mode: string = m.work_modes.includes(c.work_mode) ? c.work_mode : (m.work_modes[0] ?? '');
  return { ...c, effort, work_mode, redaction: m.redaction ? c.redaction : 'off' };
}

/** 和话题现在的配置比，哪几项变了（比的是补过的初值，所以只是补齐不算变化） */
export function changedFields(base: SwitchSel, sel: SwitchSel): string[] {
  return SWITCH_FIELDS.filter((k) => (base[k] ?? '') !== (sel[k] ?? ''));
}

/** 网页上不能确认的原因；能确认返回 ''。running：话题在做或排队 */
export function switchBlock(d: LaunchData, base: SwitchSel, sel: SwitchSel, running: boolean): string {
  if (running) return '在做时不能换，先停止';
  if (!d.models.some((m: LaunchModel) => m.key === sel.model)) return '这个模型已不在可选目录里，请重选模型';
  if (!changedFields(base, sel).length) return '';
  // 原地回到话题现在的 worktree 不用新建；换工作区或从原目录换过去都要新建，只有飞书的换配置卡能建
  if (sel.run_mode === 'worktree' && !(base.run_mode === 'worktree' && base.workspace === sel.workspace)) {
    return '新建独立 worktree 要在飞书的换配置卡上做';
  }
  return '';
}
