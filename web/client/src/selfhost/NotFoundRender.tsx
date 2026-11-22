import React from 'react';
import { NavLink } from 'react-router-dom';

/** 替代 @lark-apaas/client-toolkit/components/NotFoundRender */
export const NotFoundRender: React.FC = () => (
  <div className="sh-page">
    <div className="sh-box">
      <h2>没有这个页面</h2>
      <NavLink className="sh-btn" to="/">回到看板</NavLink>
    </div>
  </div>
);
export default NotFoundRender;
