import React, { useCallback, useEffect, useState } from 'react';
import { axiosForBackend } from './getAxiosForBackend';

interface Row {
  id: string;
  browser: string;
  os: string;
  ip: string;
  created_at: string;
  last_used_at: string;
  current: boolean;
}

const when = (iso: string): string => new Date(iso).toLocaleString('zh-CN', { hour12: false });

/** 设置页的“已登录的浏览器”：只在自托管构建里出现（Settings.tsx 用 SELFHOST 判断） */
const SessionsPanel: React.FC = () => {
  const [rows, setRows] = useState<Row[] | null>(null);
  const [busy, setBusy] = useState<boolean>(false);
  const [asking, setAsking] = useState<boolean>(false);
  const [err, setErr] = useState<string>('');

  const load = useCallback(async (): Promise<void> => {
    try {
      const res = await axiosForBackend.get<{ sessions: Row[] }>('/api/auth/sessions');
      setRows(res.data.sessions);
      setErr('');
    } catch {
      setErr('读取失败');
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  const logoutAll = async (): Promise<void> => {
    setBusy(true);
    try {
      await axiosForBackend.post('/api/auth/logout-all');
      window.location.reload();
    } catch {
      setErr('登出失败');
      setBusy(false);
    }
  };

  return (
    <>
      <h3 className="st-h">已登录的浏览器</h3>
      <div className="st-list">
        {rows === null ? <p className="st-faint">{err || '读取中…'}</p> : rows.map((r) => (
          <div className="st-r st-cell" key={r.id}>
            <div className="st-l">{r.browser} · {r.os}{r.current ? '（当前）' : ''}</div>
            <div className="st-faint">来源 {r.ip || '未知'}，登录于 {when(r.created_at)}，最近使用 {when(r.last_used_at)}</div>
          </div>
        ))}
      </div>
      {err && rows !== null ? <p className="st-note">{err}</p> : null}
      <p className="st-note">登录 30 天有效。换了设备或怀疑别人登录过，就全部登出，再重新用飞书登录。</p>
      {asking ? (
        <div className="st-r">
          <span className="st-l">登出所有浏览器（包括当前这个）？</span>
          <button type="button" className="st-opt" disabled={busy} onClick={() => void logoutAll()}>确定登出</button>
          <button type="button" className="st-opt" disabled={busy} onClick={() => setAsking(false)}>取消</button>
        </div>
      ) : (
        <button type="button" className="st-opt" disabled={busy} onClick={() => setAsking(true)}>全部登出</button>
      )}
    </>
  );
};
export default SessionsPanel;
