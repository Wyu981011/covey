/**
 * 一轮的产物（Covey 数据约定 v32 的 artifacts）怎么收成一个折叠：和飞书答案卡的「产物」同一套说法
 * （covey cards/artifact_panels.py drive_artifact_panel）：标题“产物 2 个 · REPORT.md 等”，在传时“上传中”，
 * 有没传上的写几个；点开是一行一个文件，传好的点开云空间。纯函数，npm run test:badge。
 */
import type { ArtifactItem } from '@shared/api.interface';

export interface ArtifactFold {
  /** 折叠的标题 */
  title: string;
  /** 有没传上的（标题后半句标红） */
  bad: string;
  /** 默认展开：有传不上的才开（飞书答案卡也是这样），其余收着 */
  open: boolean;
}

/** 文件大小：飞书卡片的写法（≥1 MB 写 MB，一位小数；其余 KB，至少 1） */
export function fileSize(bytes: number | undefined): string {
  if (typeof bytes !== 'number' || !Number.isFinite(bytes) || bytes < 0) return '';
  return bytes >= 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

/** 产物折叠的标题和开合；没有产物是 null */
export function artifactFold(items: ArtifactItem[] | undefined): ArtifactFold | null {
  const list: ArtifactItem[] = (items ?? []).filter((a: ArtifactItem) => !!a?.name);
  if (!list.length) return null;
  const n: number = list.length;
  if (list.some((a: ArtifactItem) => a.uploading && !a.link)) return { title: `产物 ${n} 个 · 上传中`, bad: '', open: false };
  const first: string = list[0].name.length > 40 ? `${list[0].name.slice(0, 39)}…` : list[0].name;
  const left: number = list.filter((a: ArtifactItem) => !a.link).length;
  const failed: boolean = list.some((a: ArtifactItem) => !a.link && !!a.error);
  return {
    title: `产物 ${n} 个 · ${first}${n > 1 ? ' 等' : ''}`,
    bad: left ? `${left} 个未上传` : '',
    open: failed,
  };
}
