import { invoke } from "@tauri-apps/api/core";
import { z } from "zod";
import { isTauriRuntime } from "../adapters/campus/tauriTransport";

/** 回执槽位载荷（P0-4，B 稿 §2/§3）：capability 一次性交付后存入按
 *  owner 命名的 Stronghold 槽；recover 三件套留存 = 完整确认请求体
 *  （全非敏感：preview_id/preview_digest/client_request_id），10 分钟
 *  recover 窗口内以同体重发参与摘要匹配。capability 不进
 *  URL/日志/剪贴板/遥测；本结构只落 Stronghold（Web fallback 仅内存）。 */
export const StoredReceiptSchema = z.object({
  capability: z.string().min(16),
  receipt_id: z.string().uuid(),
  client_request_id: z.string().min(8).max(128),
  confirm_body: z.object({
    preview_id: z.string().uuid(),
    preview_digest: z.string().length(64),
    client_request_id: z.string().min(8).max(128),
    confirmed: z.literal(true),
  }),
  issued_at: z.string().datetime({ offset: true }),
  expires_at: z.string().datetime({ offset: true }),
});

export type StoredReceipt = z.infer<typeof StoredReceiptSchema>;

export interface ReceiptStore {
  read(ownerKey: string): Promise<StoredReceipt | null>;
  write(ownerKey: string, receipt: StoredReceipt): Promise<void>;
  clear(ownerKey: string): Promise<void>;
}

/** Tauri：per-owner Stronghold 槽（receipt-{owner}.hold，独立快照与
 *  凭据；owner 先经 Rust 侧字符校验）。损坏载荷按无回执处理（删除式
 *  读取，recover 窗口本就 10 分钟）。 */
export class StrongholdReceiptStore implements ReceiptStore {
  async read(ownerKey: string): Promise<StoredReceipt | null> {
    const raw = await invoke<string | null>("receipt_get", { owner: ownerKey });
    if (raw === null) return null;
    try {
      return StoredReceiptSchema.parse(JSON.parse(raw));
    } catch {
      await this.clear(ownerKey);
      return null;
    }
  }

  async write(ownerKey: string, receipt: StoredReceipt): Promise<void> {
    const payload = JSON.stringify(StoredReceiptSchema.parse(receipt));
    await invoke<void>("receipt_set", { owner: ownerKey, payload });
  }

  async clear(ownerKey: string): Promise<void> {
    await invoke<void>("receipt_clear", { owner: ownerKey });
  }
}

/** Web 开发 fallback：仅内存（B 稿 §3——不写 localStorage；刷新即失，
 *  与「回执可能无法找回，清理继续」的冻结文案一致）。 */
export class MemoryReceiptStore implements ReceiptStore {
  private slots = new Map<string, StoredReceipt>();

  async read(ownerKey: string): Promise<StoredReceipt | null> {
    return this.slots.get(ownerKey) ?? null;
  }

  async write(ownerKey: string, receipt: StoredReceipt): Promise<void> {
    this.slots.set(ownerKey, StoredReceiptSchema.parse(receipt));
  }

  async clear(ownerKey: string): Promise<void> {
    this.slots.delete(ownerKey);
  }
}

export function createReceiptStore(): ReceiptStore {
  return isTauriRuntime() ? new StrongholdReceiptStore() : new MemoryReceiptStore();
}
