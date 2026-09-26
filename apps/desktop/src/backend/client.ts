import {
  CurrentStateSchema,
  EventBatchResponseSchema,
  EventBatchRequestSchema,
  FocusSessionSchema,
  PlanSchema,
  TaskSchema,
  type CurrentState,
  type EventBatchRequest,
  type EventBatchResponse,
  type FocusSession,
  type Plan,
  type Task,
} from "@agenthu/contracts";

export interface BackendClientOptions {
  baseUrl: string;
  fetcher?: typeof fetch;
}

export class BackendClient {
  private readonly fetcher: typeof fetch;

  constructor(private readonly options: BackendClientOptions) {
    // Keep the browser fetch call bound to its global context. Some WebView
    // implementations reject a detached `fetch` function with Illegal invocation.
    this.fetcher = options.fetcher ?? ((input, init) => fetch(input, init));
  }

  async pushEvents(request: EventBatchRequest): Promise<EventBatchResponse> {
    const body = EventBatchRequestSchema.parse(request);
    const response = await this.fetcher(`${this.options.baseUrl}/v1/events/batch`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify(body),
    });
    if (!response.ok) throw new Error(`事件同步失败（HTTP ${response.status}）`);
    return EventBatchResponseSchema.parse(await response.json());
  }

  async getCurrentState(): Promise<CurrentState> {
    return this.getValidated("/v1/current-state", CurrentStateSchema);
  }

  async getTasks(): Promise<Task[]> {
    const data = await this.getJson("/v1/tasks");
    return TaskSchema.array().parse(data);
  }

  async getTodayPlan(): Promise<Plan> {
    return this.getValidated("/v1/plans/today", PlanSchema);
  }

  async confirmPlan(planId: string): Promise<Plan> {
    return this.getValidated(`/v1/plans/${encodeURIComponent(planId)}/confirm`, PlanSchema, {
      method: "POST",
    });
  }

  async startFocus(taskId: string): Promise<FocusSession> {
    return this.getValidated("/v1/focus-sessions", FocusSessionSchema, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ task_id: taskId }),
    });
  }

  async updateFocus(sessionId: string, patch: Partial<FocusSession>): Promise<FocusSession> {
    return this.getValidated(`/v1/focus-sessions/${encodeURIComponent(sessionId)}`, FocusSessionSchema, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    });
  }

  private async getJson(path: string, init?: RequestInit): Promise<unknown> {
    const response = await this.fetcher(`${this.options.baseUrl}${path}`, {
      credentials: "include",
      ...init,
    });
    if (!response.ok) throw new Error(`Backend 请求失败（HTTP ${response.status}）`);
    return response.json();
  }

  private async getValidated<T>(
    path: string,
    schema: { parse: (value: unknown) => T },
    init?: RequestInit,
  ): Promise<T> {
    return schema.parse(await this.getJson(path, init));
  }
}
