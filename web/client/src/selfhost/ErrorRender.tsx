import React from 'react';

/** 替代 @lark-apaas/client-toolkit/components/ErrorRender：出错时的简单说明和重试 */
export const ErrorRender: React.FC<{ error?: Error; resetErrorBoundary?: () => void }> = ({ error, resetErrorBoundary }) => (
  <div className="sh-box" role="alert">
    <h2>页面出错了</h2>
    <p className="sh-faint">{error?.message || '未知错误'}</p>
    <button type="button" className="sh-btn" onClick={() => (resetErrorBoundary ? resetErrorBoundary() : window.location.reload())}>重试</button>
  </div>
);
export default ErrorRender;
