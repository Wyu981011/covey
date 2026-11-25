import React from 'react';
import { Head } from './Shell';
import { summaryTags, useLaunchBox } from './launch';
import { Composer } from './Composer';
import { LaunchNote, LaunchPanel } from './LaunchPanel';
import { BREAK_KEY, SEND_KEY } from './composerText';
import './launch.css';

/** 新话题页：和飞书私聊里点「开始任务」一样，选好就直接开工。输入框和对话里的同一个（边写边渲染、放大、附件、草稿按本页存） */
const DRAFT_KEY = '__new_topic__';
const NewTopicPage: React.FC = () => {
  const box = useLaunchBox();
  if (!box) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0 }}>
        <Head title="新话题" />
        <p className="t3" style={{ padding: 24 }}>Covey 还没推开新话题的选项，更新 Covey 后这里就能用。</p>
      </div>
    );
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0 }}>
      <Head title="新话题" />
      <div className="lx-page">
        <div className="lx-page-in">
          <p className="lx-sub">和飞书私聊里点「开始任务」一样：选好就直接开工</p>
          <div className="lx-newbox">
            <Composer
              topicKey={DRAFT_KEY}
              maxSeq={0}
              placeholder="写下要开的新话题：要做什么"
              launch={box}
              launchOnly
              extra={summaryTags(box.data, box.sel).join(' · ')}
              hint={`${SEND_KEY} 开始任务 · ${BREAK_KEY} 换行 · 可以粘贴截图、拖文件进来`}
            />
          </div>
          <div style={{ marginTop: 8 }}>
            <LaunchNote box={box} />
          </div>
          <LaunchPanel box={box} className="flat lx-cfg" />
        </div>
      </div>
    </div>
  );
};
export default NewTopicPage;
