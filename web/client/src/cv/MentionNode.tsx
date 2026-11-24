import React, { useEffect, useRef, useState, useSyncExternalStore } from 'react';
import { createPortal } from 'react-dom';
import { Node } from '@tiptap/core';
import { NodeViewWrapper, ReactNodeViewRenderer, type ReactNodeViewProps } from '@tiptap/react';
import { Check, Crown, X } from 'lucide-react';
import type { MentionInfo } from './collab';
import { mentionToken, pillText, tokenAtStart, type MentionAttrs } from './mention';
import { Who } from './RoomBits';
import './collab.css';

/* 正文里的 @ 胶囊：TipTap 的行内原子节点（整块选中、整块删除），Markdown 里存成 [@T586](covey-mention:<key>)（cv/mention.ts） */

/** 输入框外面告诉胶囊的：每位现在是什么样、谁是汇总方、点胶囊菜单能做什么 */
interface Env {
  info: ReadonlyMap<string, MentionInfo>;
  /** 多人协作时当前的汇总方（带“汇总”角标）；没有就是 null */
  summarizer: string | null;
  /** 胶囊菜单里能不能“设为汇总方”（多人协作或管家归口时才有意义） */
  canSet: boolean;
  setIntegrator: (key: string) => void;
  remove: (key: string) => void;
}

const NONE: Env = { info: new Map(), summarizer: null, canSet: false, setIntegrator: () => undefined, remove: () => undefined };
let env: Env = NONE;
const subs = new Set<() => void>();
const subscribe = (fn: () => void): (() => void) => {
  subs.add(fn);
  return () => subs.delete(fn);
};

/** 换一份环境（只在有变化时通知，免得每次重画都重画所有胶囊） */
export function setMentionEnv(next: Env): void {
  if (env.info === next.info && env.summarizer === next.summarizer && env.canSet === next.canSet
    && env.setIntegrator === next.setIntegrator && env.remove === next.remove) return;
  env = next;
  subs.forEach((f: () => void) => f());
}
export const clearMentionEnv = (): void => setMentionEnv(NONE);
const useEnv = (): Env => useSyncExternalStore(subscribe, () => env, () => NONE);

/** 顶栏「成员」和别处要往输入框插胶囊时，用这个递过去（输入框是唯一的接收方） */
type Request = (attrs: MentionAttrs) => void;
const requests = new Set<Request>();
export const onMentionRequest = (fn: Request): (() => void) => {
  requests.add(fn);
  return () => requests.delete(fn);
};
export const requestMention = (attrs: MentionAttrs): void => requests.forEach((f: Request) => f(attrs));

/** 点正文里的胶囊弹出的小菜单：设为汇总方、移出这次（删掉正文里它的所有 @） */
const MentionMenu: React.FC<{ at: DOMRect; info: MentionInfo; summarizer: boolean; canSet: boolean; onClose: () => void }> = ({ at, info, summarizer, canSet, onClose }) => {
  const e: Env = useEnv();
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const away = (ev: MouseEvent): void => {
      if (!box.current?.contains(ev.target as globalThis.Node)) onClose();
    };
    const esc = (ev: KeyboardEvent): void => {
      if (ev.key === 'Escape') onClose();
    };
    document.addEventListener('mousedown', away);
    document.addEventListener('keydown', esc);
    return () => {
      document.removeEventListener('mousedown', away);
      document.removeEventListener('keydown', esc);
    };
  }, [onClose]);
  const width = 220;
  const left: number = Math.max(8, Math.min(at.left, window.innerWidth - width - 8));
  const below: boolean = at.top < 150;
  const style: React.CSSProperties = below ? { left, top: at.bottom + 4 } : { left, bottom: window.innerHeight - at.top + 4 };
  return createPortal(
    <div ref={box} className="mn-menu" role="menu" aria-label={`${info.label} 的菜单`} style={style} data-testid="mention-menu">
      {canSet ? (
        <button
          type="button"
          role="menuitem"
          disabled={summarizer}
          onClick={() => { e.setIntegrator(info.key); onClose(); }}
          data-testid="mention-set"
        >
          {summarizer ? <Check /> : <Crown />}{summarizer ? '已是汇总方' : '设为汇总方'}
        </button>
      ) : null}
      <button type="button" role="menuitem" onClick={() => { e.remove(info.key); onClose(); }} data-testid="mention-remove" title="删掉正文里它的所有 @">
        <X />移出这次
      </button>
    </div>,
    // 放在 .cv 里面：颜色变量和样式都挂在它下面
    document.querySelector('.cv') ?? document.body,
  );
};

const MentionView: React.FC<ReactNodeViewProps> = ({ node, selected }) => {
  const e: Env = useEnv();
  const a = node.attrs as MentionAttrs;
  const known: MentionInfo | undefined = e.info.get(a.key);
  const info: MentionInfo = known ?? { key: a.key, kind: a.kind, label: a.label, ...(a.avatar ? { avatar: a.avatar } : {}), number: a.number ?? null };
  const sum: boolean = e.summarizer === a.key;
  // 话题的 T 号已经在头像上，名字写标题；负责人是专项名加“负责人”（太长只截专项名）；管家写名字。悬停看全名
  const { name, role, full } = pillText(info);
  const [at, setAt] = useState<DOMRect | null>(null);
  const close = React.useCallback(() => setAt(null), []);
  return (
    <NodeViewWrapper
      as="span"
      className={`mn ${info.kind}${selected ? ' sel' : ''}${sum ? ' sum' : ''}`}
      // TipTap 给这层写了行内 white-space:normal，样式表里的 nowrap 盖不过它，长名字就折成几行（T720）
      style={{ whiteSpace: 'nowrap' }}
      title={sum ? `${full} · 汇总方` : full}
      data-mention={a.key}
      data-testid="mention-pill"
      contentEditable={false}
      role="button"
      aria-haspopup="menu"
      aria-label={`@${info.label}${sum ? '，汇总方' : ''}`}
      onClick={(ev: React.MouseEvent<HTMLElement>) => setAt(at ? null : ev.currentTarget.getBoundingClientRect())}
    >
      <Who info={info} bare />
      {name ? <span className="mn-n">{name}</span> : null}
      {role ? <span className="mn-r">{role}</span> : null}
      {sum ? <span className="mn-sum">汇总</span> : null}
      {at ? <MentionMenu at={at} info={info} summarizer={sum} canSet={e.canSet} onClose={close} /> : null}
    </NodeViewWrapper>
  );
};

/** 行内原子节点：整块选中、整块删除；Markdown 读写走 TipTap 3 的 markdownTokenizer / parseMarkdown / renderMarkdown */
export const Mention = Node.create({
  name: 'mention',
  group: 'inline',
  inline: true,
  atom: true,
  selectable: true,
  draggable: false,
  addAttributes() {
    return { key: { default: '' }, kind: { default: 'topic' }, label: { default: '' }, avatar: { default: '' }, number: { default: null } };
  },
  parseHTML() {
    return [{
      tag: 'span[data-mention]',
      getAttrs: (el: HTMLElement | string) => (typeof el === 'string' ? false : { key: el.getAttribute('data-mention') ?? '', label: el.getAttribute('data-label') ?? '', kind: el.getAttribute('data-kind') ?? 'topic' }),
    }];
  },
  renderHTML({ node }) {
    return ['span', { 'data-mention': node.attrs.key, 'data-label': node.attrs.label, 'data-kind': node.attrs.kind, class: 'mn' }, `@${node.attrs.label}`];
  },
  renderText({ node }) {
    return `@${node.attrs.label}`;
  },
  markdownTokenizer: {
    name: 'mention',
    level: 'inline',
    start: (src: string): number => src.indexOf('[@'),
    tokenize: (src: string) => {
      const t = tokenAtStart(src);
      return t ? { type: 'mention', raw: t.raw, key: t.key, label: t.label } : undefined;
    },
  },
  parseMarkdown: (token) => ({ type: 'mention', attrs: { key: String(token.key ?? ''), label: String(token.label ?? '') } }),
  renderMarkdown: (node) => mentionToken(String(node.attrs?.key ?? ''), String(node.attrs?.label ?? '')),
  addNodeView() {
    return ReactNodeViewRenderer(MentionView, { as: 'span' });
  },
});
