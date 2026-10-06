import { createContext, useContext } from "react";
import { isTauriRuntime } from "../adapters/campus/tauriTransport";
import { type BackendSession, createBackendSession } from "../backend/session";
import type { BackendClient } from "../backend/client";
import { backendFetch } from "../backend/transport";
import type { FocusDraftStore } from "../focus/draft";
import { createFocusDraftStore } from "../focus/draft";
import type { EventQueue, UnownedQueueApi } from "../sync/queue";
import { createEventQueue } from "../sync/queue";
import { deriveOwnerKey } from "../sync/owner";
import { EventSyncCoordinator } from "../sync/coordinator";
import { readDataGeneration, writeDataGeneration } from "../sync/generation";
import { createReceiptStore } from "../backend/receiptStore";

const BUILD_TIME_BACKEND_URL = import.meta.env.VITE_BACKEND_URL?.replace(/\/$/, "") ?? "";
export const BACKEND_URL_PREFERENCE_KEY = "agenthu.backend-url";

/** 运行时 Backend 源偏好（B-4）：用户在设置里保存过就覆盖构建期值；Tauri 下
 *  全部流量经 backend_request 受控转发，Rust allowlist 是唯一事实源。 */
function readBackendUrlPreference(): string {
  try {
    const saved = localStorage.getItem(BACKEND_URL_PREFERENCE_KEY);
    return saved?.trim() ? saved.trim().replace(/\/$/, "") : BUILD_TIME_BACKEND_URL;
  } catch {
    return BUILD_TIME_BACKEND_URL;
  }
}

/** 应用级单例集合（M2 拆分）：此前是 App.tsx 的模块级常量，视图直接引用
 *  无法替换、无法单测。经 Context 注入后，视图测试可注入 mock 服务；
 *  App 启动时创建一次。 */
export interface AppServices {
  buildTimeBackendUrl: string;
  backendUrl: string;
  backendSession: BackendSession | null;
  backend: BackendClient | null;
  queue: EventQueue & UnownedQueueApi;
  focusDraft: FocusDraftStore;
  sync: EventSyncCoordinator | null;
  receipts: ReturnType<typeof createReceiptStore>;
}

export function createAppServices(): AppServices {
  const backendUrl = readBackendUrlPreference();
  // P0-2（D-036）：owner 命名空间的单一事实点。队列/草稿每次操作现解
  // 当前 owner——切账号（登录/登出）后同实例自动落新命名空间，旧账号
  // 数据原地保留；未登录（null）= unowned 命名空间（含 legacy 隔离件）。
  const ownerScope: { key: string | null } = { key: null };
  const resolveOwner = (): string | null => ownerScope.key;
  const queue = createEventQueue({ resolveOwner });
  const focusDraft = createFocusDraftStore({ resolveOwner });
  const backendSession = backendUrl ? createBackendSession({
    baseUrl: backendUrl,
    fetcher: isTauriRuntime() ? backendFetch : undefined,
    onOwnerChange: (owner) => {
      ownerScope.key = owner ? deriveOwnerKey(owner.origin, owner.userId) : null;
    },
  }) : null;
  const backend = backendSession?.client ?? null;
  // P0-4（D-036 §8-3）：X-Data-Generation 按 owner 持久（localStorage 键
  // 命名空间）；未登录读 null——兼容窗不自动补值。
  const generationStorage = typeof localStorage === "undefined" ? null : localStorage;
  const sync = backend ? new EventSyncCoordinator(backend, queue, {
    resolveOwner,
    dataGeneration: {
      get: () => readDataGeneration(generationStorage, ownerScope.key),
      set: (value) => writeDataGeneration(generationStorage, ownerScope.key, value),
    },
  }) : null;
  const receipts = createReceiptStore();
  return { buildTimeBackendUrl: BUILD_TIME_BACKEND_URL, backendUrl, backendSession, backend, queue, focusDraft, sync, receipts };
}

export const AppServicesContext = createContext<AppServices | null>(null);

/** 视图取用服务的唯一入口；缺失 Provider 即失败（测试须显式注入）。 */
export function useServices(): AppServices {
  const services = useContext(AppServicesContext);
  if (!services) throw new Error("AppServicesContext 未提供：视图必须渲染在 <AppServicesContext.Provider> 内");
  return services;
}
