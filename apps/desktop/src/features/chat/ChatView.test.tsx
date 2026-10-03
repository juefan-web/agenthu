import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { AgentRunRead, ChatMessage, ChatSession } from "@agenthu/contracts";
import { ChatView } from "./ChatView";

/** 契约 §5/§7：同意门（文案下发 + 版本回显开启）、202 + 有限轮询、
 *  provider 断供「模型暂不可用」不伪造兜底回答、消息删除、「为什么」
 *  展开共享 basis、pending action 深链、网络失败同一 client_message_id
 *  幂等重发、离线失败面。 */

const getModelContextConsent = vi.fn();
const setModelContextConsent = vi.fn();
const listChatSessions = vi.fn();
const createChatSession = vi.fn();
const deleteChatSession = vi.fn();
const listChatMessages = vi.fn();
const sendChatMessage = vi.fn();
const deleteChatMessage = vi.fn();
const getAgentRun = vi.fn();

function backendFixture() {
  return {
    getModelContextConsent, setModelContextConsent,
    listChatSessions, createChatSession, deleteChatSession,
    listChatMessages, sendChatMessage, deleteChatMessage, getAgentRun,
  } as unknown as Parameters<typeof ChatView>[0]["backend"];
}

const consentOff = { enabled: false, consent_text: "开启后，你的当前状态、记忆与对话内容会进入模型上下文（用于生成回复）。", consent_text_version: "v1", consented_at: null };
const consentOn = { ...consentOff, enabled: true, consented_at: "2026-10-03T12:00:00+08:00" };
const session: ChatSession = { id: "sess-1", title: "第一条", created_at: "2026-10-03T12:00:00+08:00", updated_at: "2026-10-03T12:00:00+08:00", archived_at: null };
const userMessage: ChatMessage = { id: "msg-1", role: "user", content: "把作业加进日程", created_at: "2026-10-03T12:01:00+08:00" };
const agentMessage: ChatMessage = {
  id: "msg-2", role: "assistant", content: "建议创建一个任务。", created_at: "2026-10-03T12:01:05+08:00",
  agent_run_id: "run-1", pending_action_id: "pa-1",
  decision_basis: { basis_version: "v1", summary: "作业临近且时段空闲", references: [{ kind: "task", id: "task-1", label: "HW1" }], rule_versions: { planner: "v2" }, selected_tool_call_ids: [] },
};

function makeRun(overrides: Partial<AgentRunRead>): AgentRunRead {
  return {
    id: "run-1", status: "SUCCEEDED", invocation_kind: "chat",
    trigger_ref: { kind: "chat", event_id: null, trigger_signature: null, chat_message_id: "msg-1" },
    provider: { name: "openai", model: "gpt-x", capability: "tools" },
    created_at: "2026-10-03T12:01:00+08:00", updated_at: "2026-10-03T12:01:04+08:00",
    started_at: "2026-10-03T12:01:00+08:00", finished_at: "2026-10-03T12:01:04+08:00",
    tool_calls: [], decision_basis: null, pending_action_ids: ["pa-1"],
    usage: null, result: { summary: null, degraded: false, degrade_code: null }, failure: null,
    ...overrides,
  } satisfies AgentRunRead;
}

function renderChat(backend = backendFixture(), onOpenAction?: (id: string) => void) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}>
    <ChatView backend={backend} onOpenAction={onOpenAction} />
  </QueryClientProvider>);
}

beforeEach(() => {
  vi.clearAllMocks();
  getModelContextConsent.mockResolvedValue(consentOff);
  listChatSessions.mockResolvedValue([session]);
  listChatMessages.mockResolvedValue([userMessage, agentMessage]);
  getAgentRun.mockResolvedValue(makeRun({}));
});

describe("ChatView（契约 §5 骨架）", () => {
  // fake timers 用 shouldAdvanceTime：RTL waitFor 依赖真实时间推进；
  // 超时中止路径下 finally 不保证执行，afterEach 无条件恢复真时钟。
  afterEach(() => {
    vi.useRealTimers();
  });

  it("未开启同意：先见服务端文案，开启回显版本号", async () => {
    setModelContextConsent.mockResolvedValue(consentOn);
    renderChat();
    expect(await screen.findByText(/开启后，你的当前状态、记忆与对话内容会进入模型上下文/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "同意并开启" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "同意并开启" }));
    await waitFor(() => expect(setModelContextConsent).toHaveBeenCalledWith(true, "v1"));
  });

  it("同意开启后：会话列表 + 选会话 + 消息流 + 共享 basis + 深链", async () => {
    const onOpenAction = vi.fn();
    getModelContextConsent.mockResolvedValue(consentOn);
    renderChat(backendFixture(), onOpenAction);
    fireEvent.click(await screen.findByRole("button", { name: "第一条" }));
    expect(await screen.findByText("把作业加进日程")).toBeTruthy();
    expect(screen.getByText("建议创建一个任务。")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "为什么" }));
    expect(await screen.findByText("作业临近且时段空闲")).toBeTruthy();
    expect(screen.getByText(/规则版本：planner v2/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "查看确认卡片" }));
    expect(onOpenAction).toHaveBeenCalledWith("pa-1");
  });

  it("发送：202 后轮询 run 到终态并刷新消息（fake timers）", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      getModelContextConsent.mockResolvedValue(consentOn);
      getAgentRun.mockResolvedValueOnce(makeRun({ status: "RUNNING", result: null, finished_at: null }))
        .mockResolvedValueOnce(makeRun({}));
      sendChatMessage.mockResolvedValue({ run_id: "run-1", user_message_id: "msg-3" });
      renderChat();
      fireEvent.click(await screen.findByRole("button", { name: "第一条" }));
      fireEvent.change(await screen.findByLabelText("消息"), { target: { value: "帮我把 HW1 排进今天" } });
      fireEvent.click(screen.getByRole("button", { name: "发送" }));
      await waitFor(() => expect(sendChatMessage).toHaveBeenCalledTimes(1));
      expect(sendChatMessage.mock.calls[0][2]).toMatch(/^chat-msg:/);
      // 第一次轮询：RUNNING → 继续排程
      await vi.advanceTimersByTimeAsync(3_000);
      await waitFor(() => expect(getAgentRun).toHaveBeenCalledTimes(1));
      // 第二次轮询：SUCCEEDED → 结算 + 刷新消息
      await vi.advanceTimersByTimeAsync(3_000);
      await waitFor(() => expect(getAgentRun).toHaveBeenCalledTimes(2));
      await waitFor(() => expect(listChatMessages.mock.calls.length).toBeGreaterThanOrEqual(2));
      expect(screen.queryByText(/模型处理中/)).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it("provider 断供：run FAILED 显示「模型暂不可用」，不伪造兜底回答", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      getModelContextConsent.mockResolvedValue(consentOn);
      sendChatMessage.mockResolvedValue({ run_id: "run-9", user_message_id: "msg-9" });
      getAgentRun.mockResolvedValueOnce(makeRun({
        id: "run-9", status: "FAILED", result: null, finished_at: "2026-10-03T12:02:00+08:00",
        failure: { code: "provider_unavailable", retryable: true, safe_message: "上游不可用" },
      }));
      renderChat();
      fireEvent.click(await screen.findByRole("button", { name: "第一条" }));
      fireEvent.change(await screen.findByLabelText("消息"), { target: { value: "再问一个" } });
      fireEvent.click(screen.getByRole("button", { name: "发送" }));
      await vi.advanceTimersByTimeAsync(3_000);
      expect(await screen.findByText(/模型暂不可用/)).toBeTruthy();
      expect(screen.getByText(/不会用无依据的兜底回答替代/)).toBeTruthy();
    } finally {
      vi.useRealTimers();
    }
  });

  it("网络失败：保留同一 client_message_id 重发（幂等同一 run）", async () => {
    getModelContextConsent.mockResolvedValue(consentOn);
    sendChatMessage.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    sendChatMessage.mockResolvedValueOnce({ run_id: "run-2", user_message_id: "msg-4" });
    renderChat();
    fireEvent.click(await screen.findByRole("button", { name: "第一条" }));
    fireEvent.change(await screen.findByLabelText("消息"), { target: { value: "第一条消息" } });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));
    expect(await screen.findByRole("alert")).toBeTruthy();
    const firstId = sendChatMessage.mock.calls[0][2];
    fireEvent.click(screen.getByRole("button", { name: "重发同一消息" }));
    await waitFor(() => expect(sendChatMessage).toHaveBeenCalledTimes(2));
    expect(sendChatMessage.mock.calls[1][2]).toBe(firstId);
  });

  it("删除消息：确认后调用并刷新（不再出现）", async () => {
    window.confirm = vi.fn(() => true);
    getModelContextConsent.mockResolvedValue(consentOn);
    deleteChatMessage.mockResolvedValue(undefined);
    renderChat();
    fireEvent.click(await screen.findByRole("button", { name: "第一条" }));
    fireEvent.click((await screen.findAllByRole("button", { name: "删除" }))[0]);
    await waitFor(() => expect(deleteChatMessage).toHaveBeenCalledWith("msg-1"));
    await waitFor(() => expect(listChatMessages.mock.calls.length).toBeGreaterThanOrEqual(2));
  });

  it("删除失败不静默（裁定 2）：消息级与会话级原地呈现错误、按钮保留", async () => {
    window.confirm = vi.fn(() => true);
    getModelContextConsent.mockResolvedValue(consentOn);
    deleteChatMessage.mockRejectedValueOnce(new Error("DELETE 未交付（404）"));
    deleteChatSession.mockRejectedValueOnce(new Error("会话删除失败"));
    renderChat();
    fireEvent.click(await screen.findByRole("button", { name: "第一条" }));
    fireEvent.click((await screen.findAllByRole("button", { name: "删除" }))[0]);
    expect(await screen.findByText(/删除未完成：/)).toBeTruthy();
    // 按钮保留（A3 交付 DELETE 后即可用），失败态可重试
    expect(screen.getAllByRole("button", { name: "删除" }).length).toBeGreaterThan(0);
    fireEvent.click(screen.getByTitle("删除会话"));
    expect(await screen.findByText(/会话删除未完成：/)).toBeTruthy();
  });

  it("离线：明确失败面，不渲染会话与输入", () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { container } = render(<QueryClientProvider client={queryClient}>
      <ChatView backend={null} />
    </QueryClientProvider>);
    expect(screen.getByText(/未连接 Backend/)).toBeTruthy();
    expect(container.querySelector(".chat-workspace")).toBeNull();
  });
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});
