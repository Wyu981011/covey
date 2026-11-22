import React from 'react';
import { useSnapshot } from '@client/src/hooks/use-workbench';
import { useLaunchBox } from './launch';
import { Conversation } from './Conversation';
import { Head } from './Shell';
import { MemberMenu } from './MemberMenu';
import { Pill } from './ui';
import { engineText, isRunning, isWaiting, toneOf } from './lib';

/** 大厅：整条时间线，不按负责人筛 */
const ROOM = {};

const ButlerPage: React.FC = () => {
  const { data } = useSnapshot();
  const key: string | null = data?.butler_key ?? null;
  const t = data?.topics.find((x) => x.key === key);
  const launch = useLaunchBox();
  const busy: boolean = !!t && (isRunning(t) || isWaiting(t));
  return (
    <div style={{ display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0 }}>
      <Head title="大厅" sub={`你、管家和各专项的负责人${t && engineText(t) ? ` · 管家 ${engineText(t)}` : ''}`} badge={t && busy ? <Pill tone={toneOf(t)} big /> : undefined} right={key ? <MemberMenu /> : undefined} />
      {key ? (
        <Conversation key={key} topicKey={key} mode="chat" who="管家" butler room={ROOM} placeholder="对管家说一句；打 @ 点名负责人或话题" launch={launch} />
      ) : (
        <p className="t3" style={{ padding: 24 }}>Covey 还没推管家对话。</p>
      )}
    </div>
  );
};
export default ButlerPage;
