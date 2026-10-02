import {
  CurrentStateSchema,
  EventBatchResponseSchema,
  EventBatchRequestSchema,
  FocusSessionSchema,
  LoginRequestSchema,
  PlanSchema,
  TaskSchema,
  TokenSchema,
  UserSchema,
  type CurrentState,
  type EventBatchRequest,
  type EventBatchResponse,
  type FocusSession,
  type Plan,
  type Task,
  type Token,
  type User,
} from "@agenthu/contracts";
import { MemoryItemSchema, type MemoryItem } from "./memory";

export type FocusSessionUpdate = Partial<Pick<FocusSession, "status" | "actual_minutes" | "deviation_note">>;

export class BackendAuthError extends Error {
  constructor(message = "Backend 登录已失效，请重新登录") {
    super(message);
    this.name = "BackendAuthError";
  }
}

interface BackendErrorEnvelope {
  error?: { code?: string; message?: string };
}

export interface BackendClientOptions {
  baseUrl: string;
  fetcher?: typeof fetch;
  /** Returns the current bearer token, or null when the session is anonymous. */
  getToken?: () => string | null;
  /** Called once when the Backend rejects the token used by a request with 401. */
  onUnauthorized?: (token: string) => void;
}

export class BackendClient {
  private readonly fetcher: typeof fetch;

  constructor(private readonly options: BackendClientOptions) {
    // Keep the browser fetch call bound to its global context. Some WebView
    // implementations reject a detached `fetch` function with Illegal invocation.
    this.fetcher = options.fetcher ?? ((input, init) => fetch(input, init));
  }

  async register(payload: { email: string; password: string; display_name: string }): Promise<User> {
    return this.requestValidated("/v1/auth/register", UserSchema, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }, false);
  }

  async login(email: string, password: string): Promise<Token> {
    const body = LoginRequestSchema.parse({ email, password });
    return this.requestValidated("/v1/auth/login", TokenSchema, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }, false);
  }

  async me(): Promise<User> {
    return this.requestValidated("/v1/auth/me", UserSchema);
  }

  async pushEvents(request: EventBatchRequest): Promise<EventBatchResponse> {
    const body = EventBatchRequestSchema.parse(request);
    return this.requestValidated("/v1/events/batch", EventBatchResponseSchema, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  }

  async getCurrentState(): Promise<CurrentState> {
    return this.requestValidated("/v1/current-state", CurrentStateSchema);
  }

  async getTasks(): Promise<Task[]> {
    // limit=200 是 D-029 落地前的短期过渡（默认 50 会截断真实作业量）；
    // keyset 分页上线后改为 next_cursor 循环拉全量
    const data = await this.requestJson("/v1/tasks?limit=200");
    return TaskSchema.array().parse(data);
  }

  async getTodayPlan(): Promise<Plan> {
    return this.requestValidated("/v1/plans/today", PlanSchema);
  }

  async listPlans(status: Plan["status"]): Promise<Plan[]> {
    // Page 包装（items/total/limit/offset）暂非客户端契约（D-029 落地后
    // next_cursor 入契约）；此处本地解析只用 items。limit=200 为过渡口径。
    const data = await this.requestJson(`/v1/plans?status=${encodeURIComponent(status)}&limit=200`);
    const items = PlanSchema.array().parse((data as { items?: unknown }).items);
    return items;
  }

  async cancelPlan(planId: string): Promise<Plan> {
    return this.requestValidated(`/v1/plans/${encodeURIComponent(planId)}/cancel`, PlanSchema, {
      method: "POST",
    });
  }

  async listMemories(): Promise<MemoryItem[]> {
    // Page 包装本地解析（同 listPlans 口径）；Memory API backend-only
    const data = await this.requestJson("/v1/memory?limit=200");
    return MemoryItemSchema.array().parse((data as { items?: unknown }).items);
  }

  async confirmMemory(memoryId: string): Promise<MemoryItem> {
    return this.requestValidated(`/v1/memory/${encodeURIComponent(memoryId)}/confirm`, MemoryItemSchema, { method: "POST" });
  }

  async correctMemory(memoryId: string, payload: { content: string; confidence?: number }): Promise<MemoryItem> {
    return this.requestValidated(`/v1/memory/${encodeURIComponent(memoryId)}/correct`, MemoryItemSchema, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content: payload.content, confidence: payload.confidence ?? null }),
    });
  }

  async rejectMemory(memoryId: string): Promise<MemoryItem> {
    return this.requestValidated(`/v1/memory/${encodeURIComponent(memoryId)}/reject`, MemoryItemSchema, { method: "POST" });
  }

  /** D1 快速失败：无鉴权的 /health 探测，超时/非 2xx/异常一律 false（不抛）。
   *  Promise.race 计时——Tauri 代理路径的 invoke 无法中止，让它在后台自行
   *  结束即可；浏览器路径的 fetch 同样只需竞速。 */
  async probeHealth(timeoutMs = 2_000): Promise<boolean> {
    try {
      const response = await Promise.race([
        this.fetcher(`${this.options.baseUrl}/health`, { method: "GET", credentials: "omit" }),
        new Promise<null>((resolve) => setTimeout(() => resolve(null), timeoutMs)),
      ]);
      return response !== null && response.ok;
    } catch {
      return false;
    }
  }

  async confirmPlan(planId: string): Promise<Plan> {
    return this.requestValidated(`/v1/plans/${encodeURIComponent(planId)}/confirm`, PlanSchema, {
      method: "POST",
    });
  }

  async startFocus(taskId: string): Promise<FocusSession> {
    return this.requestValidated("/v1/focus-sessions", FocusSessionSchema, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ task_id: taskId }),
    });
  }

  async updateFocus(sessionId: string, patch: FocusSessionUpdate): Promise<FocusSession> {
    return this.requestValidated(`/v1/focus-sessions/${encodeURIComponent(sessionId)}`, FocusSessionSchema, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    });
  }

  private async requestJson(path: string, init: RequestInit = {}, authenticated = true): Promise<unknown> {
    const headers = new Headers(init.headers);
    let requestToken: string | null = null;
    if (authenticated) {
      requestToken = this.options.getToken?.() ?? null;
      if (!requestToken) throw new BackendAuthError();
      headers.set("Authorization", `Bearer ${requestToken}`);
    }
    const response = await this.fetcher(`${this.options.baseUrl}${path}`, { ...init, headers, credentials: "omit" });
    if (!response.ok) {
      const message = await this.errorMessage(response);
      if (response.status === 401 && authenticated) {
        this.options.onUnauthorized?.(requestToken!);
        throw new BackendAuthError(message);
      }
      throw new Error(message);
    }
    if (response.status === 204) return null;
    return response.json();
  }

  private async errorMessage(response: Response): Promise<string> {
    try {
      const body = (await response.json()) as BackendErrorEnvelope;
      if (body?.error?.message) return body.error.message;
    } catch {
      // Fall through to the generic status message.
    }
    return `Backend 请求失败（HTTP ${response.status}）`;
  }

  private async requestValidated<T>(
    path: string,
    schema: { parse: (value: unknown) => T },
    init?: RequestInit,
    authenticated = true,
  ): Promise<T> {
    return schema.parse(await this.requestJson(path, init, authenticated));
  }
}
