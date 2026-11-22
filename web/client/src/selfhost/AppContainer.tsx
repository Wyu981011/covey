/**
 * 替代 @lark-apaas/client-toolkit/components/AppContainer：只留页面用到的 Provider（请求缓存），
 * 外加自托管的登录门：先问 /api/me，401 就画登录页，登录后刷新。没有任何平台监控、埋点或水印脚本。
 */
import React, { useEffect, useState } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { axiosForBackend, UNAUTHORIZED_EVENT } from './getAxiosForBackend';
import LoginPage from './LoginPage';
import './selfhost.css';

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false }, mutations: { retry: 1 } },
});

type Gate = 'checking' | 'in' | 'out' | 'error';

const Gated: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [gate, setGate] = useState<Gate>('checking');
  useEffect(() => {
    let live = true;
    axiosForBackend
      .get('/api/me')
      .then(() => live && setGate('in'))
      .catch((e: unknown) => live && setGate((e as { response?: { status?: number } })?.response?.status === 401 ? 'out' : 'error'));
    const onOut = (): void => setGate('out');
    window.addEventListener(UNAUTHORIZED_EVENT, onOut);
    return () => {
      live = false;
      window.removeEventListener(UNAUTHORIZED_EVENT, onOut);
    };
  }, []);
  if (gate === 'checking') return <div className="sh-page"><div className="sh-box"><p className="sh-faint">读取中…</p></div></div>;
  if (gate === 'error') {
    return (
      <div className="sh-page">
        <div className="sh-box">
          <h2>连不上服务</h2>
          <button type="button" className="sh-btn" onClick={() => window.location.reload()}>重试</button>
        </div>
      </div>
    );
  }
  if (gate === 'out') return <div className="sh-page"><LoginPage onDone={() => window.location.reload()} /></div>;
  return <>{children}</>;
};

export const AppContainer: React.FC<{ children?: React.ReactNode; defaultTheme?: string }> = ({ children }) => (
  <QueryClientProvider client={queryClient}>
    <Gated>{children}</Gated>
  </QueryClientProvider>
);
export default AppContainer;
