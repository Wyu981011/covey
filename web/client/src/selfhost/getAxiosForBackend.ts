/**
 * 替代 @lark-apaas/client-toolkit/utils/getAxiosForBackend（只在自托管构建里生效，见 vite.selfhost.config.ts）。
 * 带 cookie；非 GET 带 x-covey-csrf: 1（服务端拿它挡跨站请求）；401 时通知登录门重新登录。
 */
import axios from 'axios';

export const UNAUTHORIZED_EVENT = 'covey:unauthorized';

export const axiosForBackend = axios.create({
  baseURL: '/',
  withCredentials: true,
  headers: { 'x-covey-csrf': '1' },
  timeout: 60000,
});

axiosForBackend.interceptors.response.use(
  (res) => res,
  (err: unknown) => {
    const status: number | undefined = (err as { response?: { status?: number } } | null)?.response?.status;
    const url: string = String((err as { config?: { url?: string } } | null)?.config?.url ?? '');
    if (status === 401 && !url.startsWith('/api/auth/login-requests')) window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
    return Promise.reject(err);
  },
);
