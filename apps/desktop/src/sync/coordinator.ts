import { type EventEnvelope } from "@agenthu/contracts";
import { BackendAuthError, BackendClient, BackendHttpError } from "../backend/client";
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
  /** P0-2（D-036）：当前 owner 解析器。提供时——未登录（null）不推无主
   *  队列；flush 期间账号切换立即中止（队列按调用现解 owner，换号后
   *  remove/setCursor 会写进新命名空间，必须先停）。不提供 = 旧行为
   *  （单命名空间，测试用）。 */
  resolveOwner?: () => string | null;
  /** P0-4（D-036 §8-3）：X-Data-Generation 持久面。提供时批推走
   *  pushEventsTracked——响应捕获 live 代际回写、下批发送；409
   *  generation_stale 置 null（兼容窗重对齐）并以 GenerationStaleError
   *  中止本次 flush（重试同一代际无意义，再基后自然续传）。 */
  dataGeneration?: { get(): number | null; set(value: number | null): void };
}

/** 远端已执行破坏性确认（删除/导出）导致本地代际过期。事件保留在队列；
 *  下次 flush 以无头兼容窗重对齐，被抑事件由服务端 rejected 原因出队。 */
export class GenerationStaleError extends Error {
  constructor() {
    super("数据代际已变更（远端有删除/导出确认）；队列保留，稍后自动重对齐");
    this.name = "GenerationStaleError";
  }
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
  private readonly resolveOwner?: () => string | null;
  private readonly dataGeneration?: { get(): number | null; set(value: number | null): void };

  constructor(
    private readonly backend: BackendClient,
    private readonly queue: EventQueue,
    options: CoordinatorOptions = {},
  ) {
    this.batchSize = Math.max(1, options.batchSize ?? DEFAULT_BATCH_SIZE);
    this.maxBatchAttempts = Math.max(1, options.maxBatchAttempts ?? DEFAULT_MAX_BATCH_ATTEMPTS);
    this.retryBaseDelayMs = options.retryBaseDelayMs ?? DEFAULT_RETRY_BASE_DELAY_MS;
    this.healthProbeTimeoutMs = options.healthProbeTimeoutMs ?? DEFAULT_HEALTH_PROBE_TIMEOUT_MS;
    this.resolveOwner = options.resolveOwner;
    this.dataGeneration = options.dataGeneration;
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
    // 未登录不推无主队列：无主事件的处置是用户的显式决定（adopt/discard），
    // 不是「下一个登录的人替他同步」。
    if (this.resolveOwner && this.resolveOwner() === null) {
      return { sent: 0, duplicates: 0, rejected: 0, rejections: [], pending: (await this.queue.list()).length };
    }
    const ownerAtStart = this.resolveOwner?.() ?? null;
    const assertOwnerUnchanged = () => {
      if (this.resolveOwner && this.resolveOwner() !== ownerAtStart) {
        throw new Error("同步期间 Backend 账号已切换，本次中止；事件保留在原账号队列中");
      }
    };

    const pending = await this.queue.list();
    let sent = 0;
    let duplicates = 0;
    let rejected = 0;
    const rejections: SyncResult["rejections"] = [];
    for (let index = 0; index < pending.length; index += this.batchSize) {
      const batch = pending.slice(index, index + this.batchSize);
      // push 前先核：上一批结算的 await 间隙可能已换号，此时 getToken
      // 解出的是新账号 token，会把原账号队列的事件推给新账号的后端身份。
      assertOwnerUnchanged();
      const response = await this.pushBatchWithRetry(batch);
      // remove/setCursor 都按调用时刻的 owner 落键：换号后继续跑会把结算
      // 写进新账号的命名空间，必须先停（已结算批次的 remove 在守卫之后、
      // 服务端幂等兜底重发）。
      assertOwnerUnchanged();
      await this.queue.remove([
        ...response.accepted_event_ids,
        ...response.duplicate_event_ids,
        ...response.rejected.map((item) => item.client_event_id),
      ]);
      assertOwnerUnchanged();
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
        if (this.dataGeneration) {
          const { body, generation } = await this.backend.pushEventsTracked(
            { events: batch, client_cursor: await this.queue.getCursor() },
            this.dataGeneration.get(),
          );
          if (generation !== null) this.dataGeneration.set(generation);
          return body;
        }
        return await this.backend.pushEvents({
          events: batch,
          client_cursor: await this.queue.getCursor(),
        });
      } catch (error) {
        lastError = error;
        if (error instanceof BackendAuthError) throw error;
        if (error instanceof BackendHttpError && error.code === "generation_stale") {
          // 代际过期不进重试梯：同代际重发必然再 409。清空进入兼容窗，
          // 事件保留原 owner 队列，再基后被抑条目由服务端按原因出队。
          this.dataGeneration?.set(null);
          throw new GenerationStaleError();
        }
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
