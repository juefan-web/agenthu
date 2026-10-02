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
import {
  FileInfoSchema,
  GroundingConsentSchema,
  MaterialAnswerSchema,
  type FileInfo,
  type GroundingConsent,
  type MaterialAnswer,
} from "./grounding";

export type FocusSessionUpdate = Partial<Pick<FocusSession, "status" | "actual_minutes" | "deviation_note">>;

/** D-029 拉全量口径：每页条数取服务端上限（PaginationDep le=200）；
 *  MAX_PAGES 是防失控护栏（服务端持续铸游标/短页判停失效时中止并报错，
 *  不静默截断）。 */
const PAGE_SIZE = 200;
const MAX_PAGES = 50;

export class BackendAuthError extends Error {
  constructor(message = "Backend 登录已失效，请重新登录") {
    super(message);
    this.name = "BackendAuthError";
  }
}

/** 非 2xx（且非会话失效）的 HTTP 错误，携带状态码——讲解页等需要
 *  区分 403（同意门 fail-closed）与 503（provider 不可用，不降级）。 */
export class BackendHttpError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
    this.name = "BackendHttpError";
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
    // D-029：tasks 端点是裸数组 + X-Next-Cursor 响应头（头缺省 = 末页），
    // 逐页跟随游标拉全量——`limit=200` 单页过渡口径就此退役。
    const tasks: Task[] = [];
    let cursor: string | null = null;
    for (let page = 0; page < MAX_PAGES; page += 1) {
      const query = cursor === null
        ? `limit=${PAGE_SIZE}`
        : `limit=${PAGE_SIZE}&cursor=${encodeURIComponent(cursor)}`;
      const response = await this.requestRaw(`/v1/tasks?${query}`);
      tasks.push(...TaskSchema.array().parse(await response.json()));
      cursor = response.headers.get("x-next-cursor") || null;
      if (cursor === null) return tasks;
    }
    throw new Error(`任务分页异常：连续 ${MAX_PAGES} 页未到末页，中止拉取`);
  }

  async getTodayPlan(): Promise<Plan> {
    return this.requestValidated("/v1/plans/today", PlanSchema);
  }

  async listPlans(status: Plan["status"]): Promise<Plan[]> {
    // Page 包装本地解析（D-032 §8：Page 不入客户端契约）。plans 端点仍是
    // offset 版分页（不铸 next_cursor）——短页即末页，逐页 offset 拉全量。
    const plans: Plan[] = [];
    for (let page = 0; page < MAX_PAGES; page += 1) {
      const query = `status=${encodeURIComponent(status)}&limit=${PAGE_SIZE}&offset=${page * PAGE_SIZE}`;
      const data = await this.requestJson(`/v1/plans?${query}`);
      const items = PlanSchema.array().parse((data as { items?: unknown }).items);
      plans.push(...items);
      if (items.length < PAGE_SIZE) return plans;
    }
    throw new Error(`计划分页异常：连续 ${MAX_PAGES} 页未到末页，中止拉取`);
  }

  async cancelPlan(planId: string): Promise<Plan> {
    return this.requestValidated(`/v1/plans/${encodeURIComponent(planId)}/cancel`, PlanSchema, {
      method: "POST",
    });
  }

  async listMemories(): Promise<MemoryItem[]> {
    // 同 listPlans 口径：offset 版 Page + 短页判停（Memory API backend-only）
    const memories: MemoryItem[] = [];
    for (let page = 0; page < MAX_PAGES; page += 1) {
      const data = await this.requestJson(`/v1/memory?limit=${PAGE_SIZE}&offset=${page * PAGE_SIZE}`);
      const items = MemoryItemSchema.array().parse((data as { items?: unknown }).items);
      memories.push(...items);
      if (items.length < PAGE_SIZE) return memories;
    }
    throw new Error(`记忆分页异常：连续 ${MAX_PAGES} 页未到末页，中止拉取`);
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

  // ---- 讲解页（grounding / material-answers，§6 冻结形状；backend-only）----

  async getGroundingConsent(courseName: string): Promise<GroundingConsent> {
    const query = `course_name=${encodeURIComponent(courseName)}`;
    return this.requestValidated(`/v1/grounding-consent?${query}`, GroundingConsentSchema);
  }

  /** 开启/关闭都用当前 consent_text_version——「开启」必须基于用户实际
   *  读到的措辞（stale-version 422 的另一半语义在 UI 层）。 */
  async setGroundingConsent(courseName: string, enabled: boolean, textVersion: string): Promise<GroundingConsent> {
    return this.requestValidated("/v1/grounding-consent", GroundingConsentSchema, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ course_name: courseName, enabled, consent_text_version: textVersion }),
    });
  }

  /** 403（同意门 fail-closed）与 503（provider 故障，绝不降级）都以
   *  BackendHttpError 携带状态码抛出，由视图分流。 */
  async askGroundedQuestion(courseName: string, question: string): Promise<MaterialAnswer> {
    return this.requestValidated("/v1/material/answers", MaterialAnswerSchema, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ course_name: courseName, question }),
    });
  }

  async listGroundedAnswers(courseName: string): Promise<MaterialAnswer[]> {
    // 同 listPlans 口径：offset 版 Page + 短页判停（量级 = 回答数）
    const answers: MaterialAnswer[] = [];
    for (let page = 0; page < MAX_PAGES; page += 1) {
      const query = `course_name=${encodeURIComponent(courseName)}&limit=${PAGE_SIZE}&offset=${page * PAGE_SIZE}`;
      const data = await this.requestJson(`/v1/material/answers?${query}`);
      const items = MaterialAnswerSchema.array().parse((data as { items?: unknown }).items);
      answers.push(...items);
      if (items.length < PAGE_SIZE) return answers;
    }
    throw new Error(`回答分页异常：连续 ${MAX_PAGES} 页未到末页，中止拉取`);
  }

  async deleteGroundedAnswer(answerId: string): Promise<void> {
    await this.requestJson(`/v1/material/answers/${encodeURIComponent(answerId)}`, { method: "DELETE" });
  }

  async listFiles(): Promise<FileInfo[]> {
    // 讲解页数据源：课程下拉（distinct course_name）与引用文件名映射
    const files: FileInfo[] = [];
    for (let page = 0; page < MAX_PAGES; page += 1) {
      const data = await this.requestJson(`/v1/files?limit=${PAGE_SIZE}&offset=${page * PAGE_SIZE}`);
      const items = FileInfoSchema.array().parse((data as { items?: unknown }).items);
      files.push(...items);
      if (items.length < PAGE_SIZE) return files;
    }
    throw new Error(`文件分页异常：连续 ${MAX_PAGES} 页未到末页，中止拉取`);
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

  /** 执行请求并做鉴权/错误语义处理，返回原始 Response（D-029：tasks 的
   *  X-Next-Cursor 头在 Response 上，调用方按需读取；其余走 requestJson）。 */
  private async requestRaw(path: string, init: RequestInit = {}, authenticated = true): Promise<Response> {
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
      throw new BackendHttpError(message, response.status);
    }
    return response;
  }

  private async requestJson(path: string, init: RequestInit = {}, authenticated = true): Promise<unknown> {
    const response = await this.requestRaw(path, init, authenticated);
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
