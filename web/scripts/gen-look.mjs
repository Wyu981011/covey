#!/usr/bin/env node
/**
 * 夜航（Covey docs/ui.md）的词和颜色：从 look.json 生成网页用的 look.gen.ts 和 look.gen.css，不手抄。
 *
 * look.json 来自 covey 仓库：python3 -B scripts/export_look.py --out <本工程>/client/src/cv/look.json
 * 然后：node scripts/gen-look.mjs          重新生成
 *       node scripts/gen-look.mjs --check  只核对生成结果和 look.json 一致（不一致退出 1）
 */
import { readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const dir = join(dirname(fileURLToPath(import.meta.url)), '..', 'client', 'src', 'cv');
const look = JSON.parse(readFileSync(join(dir, 'look.json'), 'utf8'));
const HEAD = '由 scripts/gen-look.mjs 从 look.json（covey scripts/export_look.py）生成，不要手改';

const rgba = (rgb, a) => `rgba(${rgb[0]},${rgb[1]},${rgb[2]},${Math.min(a, 1).toFixed(3)})`;
const keys = Object.keys(look.states);
const b = look.band;

const ts = `/* ${HEAD} */
/** 状态词表的 key（core/look.py STATES，网页数据约定 v5 topic.tone） */
export type ToneKey = ${keys.map((k) => `'${k}'`).join(' | ')};
/** act 要你处理，tell 告诉你一声，back 背景 */
export type ToneGroup = 'act' | 'tell' | 'back';
export interface StateLook {
  word: string;
  heading: string;
  group: ToneGroup;
  web: string;
}
export const STATES: Record<ToneKey, StateLook> = {
${keys.map((k) => {
  const s = look.states[k];
  return `  ${k}: { word: ${JSON.stringify(s.word)}, heading: ${JSON.stringify(s.heading)}, group: '${s.group}', web: '${s.web}' },`;
}).join('\n')}
};
export const TONE_KEYS: readonly ToneKey[] = [${keys.map((k) => `'${k}'`).join(', ')}];
/** 最急的那件在前：结论带先说它 */
export const PRESSING: readonly ToneKey[] = [${look.pressing.map((k) => `'${k}'`).join(', ')}];
export const PROJECT: StateLook = { word: ${JSON.stringify(look.project.word)}, heading: ${JSON.stringify(look.project.word)}, group: '${look.project.group}', web: '${look.project.web}' };
export const BRAND: string = '${look.brand.web}';
/** 话题的身份色（core/look.py TOPIC_COLORS）：T 号头像的底色，深浅模式同一个，上面是白字；只分清是哪个话题，不说状态 */
export const TOPIC_COLORS: readonly string[] = [${look.topics.colors.map((c) => `'${c}'`).join(', ')}];
/** 号码 × TOPIC_STEP 模颜色数取色：相邻的号码颜色一定不同（core/look.py topic_color） */
export const TOPIC_STEP: number = ${look.topics.step};
/** 话题头像（T 号）的底色，同 core/look.py topic_color：号码 × TOPIC_STEP 模 TOPIC_COLORS 的个数，相邻号码颜色一定不同、连着 12 个不重样；
 *  没有号码（null、0）是 null */
export function topicColor(number: number | null | undefined): string | null {
  if (typeof number !== 'number' || !Number.isFinite(number) || number < 1) return null;
  return TOPIC_COLORS[(Math.trunc(number) * TOPIC_STEP) % TOPIC_COLORS.length] ?? null;
}
`;

const stateVars = keys.map((k) => `--st-${k}:${look.states[k].web};`).join('');
const css = `/* ${HEAD} */
:root{--lk-brand:${look.brand.web};${Object.entries(look.web).map(([k, v]) => `--lk-${k}:${v};`).join('')}${stateVars}--st-project:${look.project.web};--band-top:${rgba(b.dark_rgb, b.top * b.dark)};--band-bottom:${rgba(b.dark_rgb, b.floor * b.dark)};--band-line:${rgba(b.dark_rgb, b.line[0])}}
.cv.light{--band-top:${rgba(b.rgb, b.top)};--band-bottom:${rgba(b.rgb, b.floor)};--band-line:${rgba(b.rgb, b.line[0])}}
${[...keys, 'project'].map((k) => `.tone-${k},.cv .dot.tone-${k}{--c:var(--st-${k})}`).join('\n')}
`;

const outs = [['look.gen.ts', ts], ['look.gen.css', css]];
if (process.argv.includes('--check')) {
  const bad = outs.filter(([name, text]) => {
    try {
      return readFileSync(join(dir, name), 'utf8') !== text;
    } catch {
      return true;
    }
  });
  if (bad.length) {
    console.error(`和 look.json 不一致：${bad.map(([n]) => n).join('、')}；跑 node scripts/gen-look.mjs`);
    process.exit(1);
  }
  console.log('look.gen.* 和 look.json 一致');
} else {
  for (const [name, text] of outs) writeFileSync(join(dir, name), text);
  console.log(`写了 ${outs.map(([n]) => n).join('、')}`);
}
