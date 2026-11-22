import { toast } from 'sonner';
import type { OutboxRequest, OutboxStatus } from '@shared/api.interface';
import { fetchOutboxStatus, postOutbox } from '@client/src/api/workbench';
import { errorText } from '@client/src/lib/workbench-format';

const sleep = (ms: number): Promise<void> => new Promise<void>((r: () => void) => window.setTimeout(r, ms));

/**
 * 发一条不属于对话的操作（纠正记忆、停一次协作），等 Covey 的回执：done 写它回的那句，failed 写原因（旧版 Covey 不认这个操作也是这里说）。
 * 最多等一分多钟；没等到就说一声，操作还在发件箱里，Covey 回来会照做。
 */
export async function sendAndWait(body: OutboxRequest, sent: string): Promise<'done' | 'failed' | 'new'> {
  try {
    await postOutbox(body);
  } catch (e) {
    toast.error(`没发出去：${errorText(e)}`);
    return 'failed';
  }
  toast.message(sent);
  for (let i = 0; i < 50; i += 1) {
    await sleep(i < 3 ? 700 : 1500);
    let r: OutboxStatus;
    try {
      r = await fetchOutboxStatus(body.op_id);
    } catch {
      continue;
    }
    if (r.state === 'done') {
      toast.success(r.message || '已执行');
      return 'done';
    }
    if (r.state === 'failed') {
      toast.error(r.message || '没有成功');
      return 'failed';
    }
  }
  toast.message('Covey 还没处理，过一会再看');
  return 'new';
}
