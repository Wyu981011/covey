import React, { useEffect, useRef, useState } from 'react';
import { axiosForBackend } from './getAxiosForBackend';

type Phase = 'idle' | 'waiting' | 'denied' | 'expired' | 'error';

/** 飞书里点“允许”登录：点按钮 → 页面显示 4 位对照码 → 去飞书私聊核对并点允许 → 轮询到批准就刷新 */
const LoginPage: React.FC<{ onDone: () => void }> = ({ onDone }) => {
  const [phase, setPhase] = useState<Phase>('idle');
  const [code, setCode] = useState<string>('');
  const [msg, setMsg] = useState<string>('');
  const timer = useRef<number | null>(null);

  const stop = (): void => {
    if (timer.current !== null) window.clearInterval(timer.current);
    timer.current = null;
  };
  useEffect(() => stop, []);

  const start = async (): Promise<void> => {
    stop();
    setMsg('');
    try {
      const res = await axiosForBackend.post<{ id: string; code: string; expires_at: string }>('/api/auth/login-requests');
      setCode(res.data.code);
      setPhase('waiting');
      const id: string = res.data.id;
      // 过了有效期还没结果（比如绑定 cookie 已过期，轮询一直 404）就停下来让人重新点，不无限地问
      const giveUpAt: number = (Date.parse(res.data.expires_at) || Date.now() + 5 * 60 * 1000) + 10 * 1000;
      const poll = async (): Promise<void> => {
        if (Date.now() > giveUpAt) {
          stop();
          setPhase('expired');
          return;
        }
        try {
          const r = await axiosForBackend.get<{ state: string }>(`/api/auth/login-requests/${id}`);
          if (r.data.state === 'approved') {
            stop();
            onDone();
          } else if (r.data.state === 'denied' || r.data.state === 'expired' || r.data.state === 'used') {
            stop();
            setPhase(r.data.state === 'denied' ? 'denied' : 'expired');
          }
        } catch {
          /* 网络抖动，下一轮再问 */
        }
      };
      timer.current = window.setInterval(() => void poll(), 2000);
    } catch (e) {
      const status: number | undefined = (e as { response?: { status?: number; headers?: Record<string, string> } })?.response?.status;
      const wait: string | undefined = (e as { response?: { headers?: Record<string, string> } })?.response?.headers?.['retry-after'];
      setPhase('error');
      setMsg(status === 429 ? `发得太频繁了，请 ${wait ?? '30'} 秒后再试` : '发起登录失败，请稍后再试');
    }
  };

  return (
    <div className="sh-box sh-login">
      <h1>Covey</h1>
      {phase === 'idle' || phase === 'error' ? (
        <>
          <p className="sh-faint">用飞书确认登录：Covey 会在私聊里给你发一张确认卡。</p>
          {msg ? <p className="sh-warn">{msg}</p> : null}
          <button type="button" className="sh-btn sh-primary" onClick={() => void start()}>用飞书登录</button>
        </>
      ) : null}
      {phase === 'waiting' ? (
        <>
          <p className="sh-faint">对照码</p>
          <div className="sh-code" aria-label="对照码">{code}</div>
          <p>去飞书私聊，核对卡片上的对照码一致后点“允许”。</p>
          <p className="sh-faint">等待确认中，5 分钟内有效…</p>
        </>
      ) : null}
      {phase === 'denied' ? (
        <>
          <p className="sh-warn">这次登录被拒绝了。</p>
          <button type="button" className="sh-btn" onClick={() => void start()}>重新登录</button>
        </>
      ) : null}
      {phase === 'expired' ? (
        <>
          <p className="sh-warn">这次登录已过期。</p>
          <button type="button" className="sh-btn" onClick={() => void start()}>重新登录</button>
        </>
      ) : null}
    </div>
  );
};
export default LoginPage;
