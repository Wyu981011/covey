/// <reference types="vite/client" />
import React from 'react';
import { UserRound } from 'lucide-react';
import { topicColor } from './look.gen';
import './badge.css';

const pictures: Record<string, string> = import.meta.glob<string>('./avatars/*.png', { eager: true, query: '?url', import: 'default' });

/** 这个头像名有没有图（管家 butler，专项的固定头像名） */
export const hasPicture = (name: string | undefined): boolean => !!name && !!pictures[`./avatars/${name}.png`];

/** 复用飞书卡片的头像；专项名由 Bridge 同步，未知或尚未分配时显示中性图标。 */
export const RoleAvatar: React.FC<{ name?: string; size?: number }> = ({ name, size = 22 }) => {
  const src: string | undefined = pictures[`./avatars/${name ?? ''}.png`];
  return src
    ? <img className="a-avatar" src={src} alt="" aria-hidden="true" width={size} height={size} />
    : <UserRound className="a-avatar a-avatar-empty" aria-hidden="true" width={size} height={size} />;
};

/** 话题头像（和飞书私聊区一样，covey docs/ui.md“话题头像”）：自己的 T 号，白色粗体放在话题自己的颜色上；没有号码时是一个灰的“T” */
export const TopicBadge: React.FC<{ number: number | null | undefined }> = ({ number }) => {
  const color: string | null = topicColor(number);
  return color
    ? <span className="a-tbadge" style={{ background: color }} aria-hidden="true">T{number}</span>
    : <span className="a-tbadge none" aria-hidden="true">T</span>;
};
