import { type EventEnvelope } from "@agenthu/contracts";
import { BackendAuthError, BackendClient } from "../backend/client";
import type { EventQueue } from "./queue";

export interface SyncResult {
  sent: number;
  duplicates: number;
  rejected: number;
  rejections: Array<{ client_event_id: string; reason: string }>;
  pending: number;
}

export interface CoordinatorOptions {
  /** 上传分批大小（生产 500；测试用小值驱动多批路径）。 */
  batchSize?: number;
  /** 单批失败重试的退避基数（毫秒），按 2^n 指数递增。 */
  retryBaseDelayMs?: number;
  /** 单批最大尝试次数，超限后停发并把原因抛给 UI。 */
  maxBatchAttempts?: number;
  /** 批失败后 /health 探测的预算（毫秒）；探测失败 = 不可达，跳过重试梯
   *  （round-5 D1：断网 flush 从 ~13s 压到 ≤5s——首攻快速失败 + 探测 ≤2s）。 */
  healthProbeTimeoutMs?: number;
}

const DEFAULT_BATCH_SIZE = 500;
const DEFAULT_MAX_BATCH_ATTEMPTS = 3;
const DEFAULT_RETRY_BASE_DELAY_MS = 1_000;
const DEFAULT_HEALTH_PROBE_TIMEOUT_MS = 2_000;

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export class EventSyncCoordinator {
  private inFlight: Promise<SyncResult> | undefined;
  private readonly batchSize: number;
  private readonly maxBatchAttempts: number;
  private readonly retryBaseDelayMs: number;
  private readonly healthProbeTimeoutMs: number;

  constructor(
    private readonly backend: BackendClient,
    private readonly queue: EventQueue,
    options: CoordinatorOptions = {},
  ) {
    this.batchSize = Math.max(1, options.batchSize ?? DEFAULT_BATCH_SIZE);
    this.maxBatchAttempts = Math.max(1, options.maxBatchAttempts ?? DEFAULT_MAX_BATCH_ATTEMPTS);
    this.retryBaseDelayMs = options.retryBaseDelayMs ?? DEFAULT_RETRY_BASE_DELAY_MS;
    this.healthProbeTimeoutMs = options.healthProbeTimeoutMs ?? DEFAULT_HEALTH_PROBE_TIMEOUT_MS;
  }

  async enqueue(events: EventEnvelope[]): Promise<void> {
    // 敏感字段防线在队列边界无条件执行（queue.add 内），此处不再重复。
    await this.queue.add(events);
  }

  /** single-flight：采集完成、online 监听与手动重试并发触发时共享同一次在途
   *  上传——双份请求靠服务端幂等兜底、cursor 被旧响应交错覆盖的问题从此
   *  不可能出现（B-1）。 */
  flush(): Promise<SyncResult> {
    this.inFlight ??= this.flushOnce().finally(() => {
      this.inFlight = undefined;
    });
    return this.inFlight;
  }

  private async flushOnce(): Promise<SyncResult> {
    const pending = await this.queue.list();
    let sent = 0;
    let duplicates = 0;
    let rejected = 0;
    const rejections: SyncResult["rejections"] = [];
    for (let index = 0; index < pending.length; index += this.batchSize) {
      const batch = pending.slice(index, index + this.batchSize);
      const response = await this.pushBatchWithRetry(batch);
      await this.queue.remove([
        ...response.accepted_event_ids,
        ...response.duplicate_event_ids,
        ...response.rejected.map((item) => item.client_event_id),
      ]);
      await this.queue.setCursor(response.next_cursor);
      sent += response.accepted_event_ids.length;
      duplicates += response.duplicate_event_ids.length;
      rejected += response.rejected.length;
      rejections.push(...response.rejected);
    }
    return {
      sent,
      duplicates,
      rejected,
      rejections,
      pending: (await this.queue.list()).length,
    };
  }

  /** 单批指数退避重试；认证失败立即上抛（重发同一 Token 无意义，交上层引导
   *  重新登录），超限停发——事件留在待同步队列，等下一次触发续传。 */
  private async pushBatchWithRetry(batch: EventEnvelope[]): Promise<Awaited<ReturnType<BackendClient["pushEvents"]>>> {
    let lastError: unknown;
    for (let attempt = 1; attempt <= this.maxBatchAttempts; attempt += 1) {
      try {
        return await this.backend.pushEvents({
          events: batch,
          client_cursor: await this.queue.getCursor(),
        });
      } catch (error) {
        lastError = error;
        if (error instanceof BackendAuthError) throw error;
        if (attempt < this.maxBatchAttempts) {
          // D1 快速失败（惰性探测，快乐路径零开销）：首攻失败先问 /health，
          // 不可达（含探测超时）立即放弃重试梯——断网语义从「重试梯+退避
          // ~13s」变为「首攻快速失败 + ≤2s 探测」；可达则按原退避重试
          // （瞬时故障路径不变）。
          if (!(await this.backend.probeHealth(this.healthProbeTimeoutMs))) {
            throw new Error("Backend 不可达（健康探测失败）；事件保留在待同步队列，恢复连接后可重试");
          }
          await delay(this.retryBaseDelayMs * 2 ** (attempt - 1));
        }
      }
    }
    const reason = lastError instanceof Error ? lastError.message : String(lastError);
    throw new Error(`同步失败：已重试 ${this.maxBatchAttempts} 次仍不可达（${reason}）；事件保留在待同步队列，可稍后重试`);
  }
}
