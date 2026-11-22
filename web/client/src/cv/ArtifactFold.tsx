import React, { useState } from 'react';
import { ChevronDown, ChevronRight, ExternalLink, FileText, Paperclip } from 'lucide-react';
import type { ArtifactItem } from '@shared/api.interface';
import { artifactFold, fileSize, type ArtifactFold as Fold } from './artifactList';

/** 一轮的产物（Covey v32）：回答正文下面一颗“产物 N 个 · 第一个 等”，点开一行一个文件，传到云空间的点了打开；
 *  和飞书答案卡一样默认收着，有传不上的才开（covey docs/ui.md 5.2：回答正文 → 产物（折叠）→ 输入/输出） */
export const ArtifactFold: React.FC<{ items: ArtifactItem[] | undefined }> = ({ items }) => {
  const fold: Fold | null = artifactFold(items);
  const [open, setOpen] = useState<boolean | null>(null);
  if (!fold || !items) return null;
  const shown: boolean = open ?? fold.open;
  return (
    <div className={`afiles${shown ? ' open' : ''}`} data-testid="artifacts">
      <button type="button" className="fold afiles-h" onClick={() => setOpen(!shown)} aria-expanded={shown}>
        {shown ? <ChevronDown /> : <ChevronRight />}
        <Paperclip className="afiles-ic" />
        <span className="afiles-t">{fold.title}</span>
        {fold.bad ? <span className="afiles-bad">· {fold.bad}</span> : null}
      </button>
      {shown ? (
        <ul className="afiles-list">
          {items.filter((a: ArtifactItem) => !!a?.name).map((a: ArtifactItem, i: number) => (
            <li key={i}>
              <FileText className="afiles-fi" />
              {a.link ? (
                <a href={a.link} target="_blank" rel="noreferrer" title={`在云空间打开 ${a.name}`}>
                  <span className="afiles-n">{a.name}</span>
                  <ExternalLink className="afiles-go" />
                </a>
              ) : (
                <span className="afiles-n">{a.name}</span>
              )}
              {a.link && a.size !== undefined ? <span className="afiles-sz">{fileSize(a.size)}</span> : null}
              {!a.link && a.error ? <span className="afiles-err">{a.error}</span> : null}
              {!a.link && !a.error ? <span className="afiles-sz">{a.uploading ? '上传中' : '未上传'}</span> : null}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
};
