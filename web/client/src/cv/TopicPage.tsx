import React, { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Share2 } from 'lucide-react';
import type { SnapshotTopic, TurnView } from '@shared/api.interface';
import { useIsDesktop } from '@client/src/hooks/use-breakpoint';
import { useSnapshot, useTurns } from '@client/src/hooks/use-workbench';
import { shortTime } from '@client/src/lib/workbench-format';
import { ConfigBar } from './ConfigBar';
import { Conversation } from './Conversation';
import { Head } from './Shell';
import { Pill } from './ui';
import { engineText, harnessName, isRunning, isWaiting, toneOf, toneWord, type ToneKey } from './lib';
import { MobileProgress, ProgressRail, TopicOverview } from './TopicOverview';
import { TopicBadge } from './RoleAvatar';
import { lastAgent, listTone, stopPressing } from './topicText';

/** 页头：T 号、标题、状态和轮次；右边一行小字（Harness · 模型 · 工作区 · 几号起）。token 总数这类挪进每轮的“过程” */
export const TopicHead: React.FC<{ t: SnapshotTopic | undefined; workspace: string; failed: boolean }> = ({ t, workspace, failed }) => {
  const nav = useNavigate();
  const desktop: boolean = useIsDesktop();
  if (!t) return <Head title="话题" back="/" />;
  // 停住的跟看板走：看板不列了（看过、点了不管了）就是灰的“已停止”，不再是红的“停住了”（T550 P1-4）
  const tn: ToneKey = failed && !isRunning(t) && !isWaiting(t) ? (stopPressing(t) ? 'stopped' : 'cancelled') : listTone(t);
  const word: string = toneWord(tn);
  const stateText: string = t.round ? `${word} · 第 ${t.round} 轮` : word;
  const started: string = t.started_at ? `${shortTime(t.started_at).split(' ')[0]} 起` : '';
  const meta: string = [engineText(t), workspace, started].filter(Boolean).join(' · ');
  return (
    <Head
      title={desktop || !t.number ? t.title : <><TopicBadge number={t.number} />{t.title}</>}
      sub={desktop ? undefined : stateText}
      back={desktop ? undefined : t.project_key ? `/projects/${encodeURIComponent(t.project_key)}` : '/'}
      tags={t.number && desktop ? <TopicBadge number={t.number} /> : undefined}
      badge={<Pill tone={tn} text={desktop ? stateText : word} />}
      right={
        desktop ? (
          <span className="a-hmeta">
            <span>{meta}</span>
            {t.project_key ? (
              <a className="btn sm" role="button" onClick={() => nav(`/projects/${encodeURIComponent(t.project_key ?? '')}/graph?sel=${encodeURIComponent(t.key)}`)}>
                <Share2 /> 在全图里看
              </a>
            ) : null}
          </span>
        ) : undefined
      }
    />
  );
};

const TopicPage: React.FC = () => {
  const { key = '' } = useParams();
  const desktop: boolean = useIsDesktop();
  const { data: snap } = useSnapshot();
  const { data } = useTurns(key);
  const t: SnapshotTopic | undefined = snap?.topics.find((x: SnapshotTopic) => x.key === key);
  const turns: TurnView[] = data?.turns ?? [];
  const last: TurnView | undefined = lastAgent(turns);
  const running: boolean = (!!t && isRunning(t)) || turns.some((x: TurnView) => x.status === 'running');
  const failed: boolean = !running && last?.status === 'failed';
  const workspace: string = data?.topic.workspace ?? '';
  const hn: string = harnessName(t?.harness ?? '') || '它';
  const placeholder: string = running
    ? desktop ? `补充一句，${hn}${/[A-Za-z0-9]$/u.test(hn) ? ' ' : ''}会在这一轮里看到` : '补充一句…'
    : desktop ? `说点什么，会作为新一轮发给 ${hn}` : '说点什么…';
  // 往下滚时总览收成一行；点开、或滚回顶上时展开
  const [compact, setCompact] = useState<boolean>(false);
  useEffect(() => setCompact(false), [key]);
  // 输入框下沿的配置栏：有 config（v20）时点开能换配置；在做或排队时面板里不能确认
  const busy: boolean = running || (!!t && toneOf(t) === 'queued');
  const config = <ConfigBar topic={t} workspace={workspace} busy={busy} />;
  return (
    <div className="a-topic">
      <div className="a-center">
        <TopicHead t={t} workspace={workspace} failed={failed} />
        {desktop ? (
          <div className="a-ovwrap">
            <TopicOverview key={key} topicKey={key} compact={compact} onExpand={() => setCompact(false)} />
          </div>
        ) : null}
        <Conversation
          key={key}
          topicKey={key}
          mode="topic"
          placeholder={placeholder}
          config={config}
          onUserScroll={desktop ? setCompact : undefined}
          lead={
            desktop ? undefined : (
              <>
                <TopicOverview topicKey={key} mobile />
                <MobileProgress topicKey={key} />
              </>
            )
          }
        />
      </div>
      {desktop ? <ProgressRail topicKey={key} /> : null}
    </div>
  );
};
export default TopicPage;
