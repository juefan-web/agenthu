import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { AgentRunRead, ChatMessage, ChatSearchItem, ChatSession } from "@agenthu/contracts";
import { BackendHttpError, type BackendClient } from "../../backend/client";
import { errorText } from "../../lib/errors";
import { DecisionBasisView } from "../agent/DecisionBasisView";

/** Chat 视图骨架（契约 §5/§7）：同一 Agent 的一个入口。全局「Agent 模型
 *  上下文」同意门（默认关，文案由服务端下发、开启回显版本）→ 会话/消息
 *  cursor 列表 → 发送 202 {run_id, user_message_id} + 有限轮询 → 消息级
 *  删除。「为什么」直接展开同一份 DecisionBasisView，不二次调用模型编造
 *  解释；可执行建议只深链到确认卡片，聊天内没有绕过确认的快捷执行。
 *
 *  断供纪律（§7）：provider 故障/同意缺失显示「模型暂不可用」，不生成
 *  无依据回答；计划、重排建议与 Focus 不受影响（不在本视图内）。 */

const MAX_RUN_POLLS = 40;
const SETTLED_RUN_STATUSES = new Set(["SUCCEEDED", "FAILED", "CANCELLED", "WAITING_CONFIRMATION"]);
const PROVIDER_DOWN_CODES = new Set(["provider_unavailable", "model_consent_missing", "no_tool_support"]);

function newClientId(prefix: string): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") return `${prefix}:${crypto.randomUUID()}`;
  return `${prefix}:${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

function runOutcomeText(run: AgentRunRead): string | null {
  if (run.status === "SUCCEEDED") {
    if (run.result?.degraded) return `本轮降级完成（${run.result.degrade_code ?? "unknown"}）：${run.result.summary ?? ""}`.trim();
    return null;
  }
  if (run.status === "WAITING_CONFIRMATION") return "Agent 提出了需要你确认的动作，请到「确认」视图处理。";
  if (run.status === "CANCELLED") return "本轮已取消。";
  if (run.status === "FAILED") {
    if (run.failure && PROVIDER_DOWN_CODES.has(run.failure.code)) return "模型暂不可用：本轮没有生成回复，也不会用无依据的兜底回答替代。";
    return run.failure ? `本轮失败：${run.failure.safe_message}` : "本轮失败。";
  }
  return null;
}

function MessageBubble({ message, backend, onOpenAction }: {
  message: ChatMessage;
  backend: BackendClient;
  onOpenAction: (actionId: string) => void;
}) {
  const queryClient = useQueryClient();
  const [showBasis, setShowBasis] = useState(false);
  // 删除失败不得静默（裁定 2）：原地呈现错误并保留重试（按钮不隐藏——
  // DELETE 端点随 A3 交付，此前失败如实可见）。
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const remove = useMutation({
    mutationFn: () => backend.deleteChatMessage(message.id),
    onSuccess: () => {
      setDeleteError(null);
      queryClient.invalidateQueries({ queryKey: ["chat-messages"] });
    },
    onError: (error) => setDeleteError(errorText(error)),
  });
  const isUser = message.role === "user";
  return <li className={`chat-message ${isUser ? "from-user" : "from-agent"}`}>
    <div className="chat-message-head">
      <span>{isUser ? "我" : "助手"}</span>
      <time>{new Date(message.created_at).toLocaleTimeString()}</time>
      <button type="button" className="chat-message-delete" disabled={remove.isPending}
        onClick={() => { if (window.confirm("删除这条消息？删除后在列表、搜索与后续 Agent 检索中都不再出现。")) remove.mutate(); }}>
        删除
      </button>
    </div>
    <p className="chat-message-content">{message.content}</p>
    {deleteError && <p role="alert" className="chat-delete-error">删除未完成：{deleteError}</p>}
    {message.decision_basis && <button type="button" className="chat-message-why" aria-expanded={showBasis} onClick={() => setShowBasis(!showBasis)}>
      为什么
    </button>}
    {showBasis && message.decision_basis && <DecisionBasisView basis={message.decision_basis} />}
    {!isUser && message.pending_action_id && <div className="chat-action-row">
      <span>这条回复提出了一个待确认动作</span>
      <button type="button" onClick={() => onOpenAction(message.pending_action_id!)}>查看确认卡片</button>
    </div>}
  </li>;
}

export function ChatView({ backend, onOpenAction }: {
  backend: BackendClient | null;
  onOpenAction?: (actionId: string) => void;
}) {
  const queryClient = useQueryClient();
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [failedSend, setFailedSend] = useState<{ content: string; clientMessageId: string } | null>(null);
  const [activeRun, setActiveRun] = useState<{ runId: string; attempts: number } | null>(null);
  const [runOutcome, setRunOutcome] = useState<string | null>(null);
  const [pollNotice, setPollNotice] = useState<string | null>(null);
  const [runError, setRunError] = useState<string | null>(null);
  const [sessionDeleteError, setSessionDeleteError] = useState<string | null>(null);
  // D-035 检索（§5：显示原消息、时间与会话定位，不做摘要/高亮）
  const [searchInput, setSearchInput] = useState("");
  const [searchResults, setSearchResults] = useState<{ items: ChatSearchItem[]; nextCursor: string | null } | null>(null);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [searchBusy, setSearchBusy] = useState(false);
  const openAction = onOpenAction ?? (() => undefined);

  const consent = useQuery({
    queryKey: ["model-context-consent"],
    queryFn: () => backend!.getModelContextConsent(),
    enabled: !!backend,
  });
  const sessions = useQuery({
    queryKey: ["chat-sessions"],
    queryFn: () => backend!.listChatSessions(),
    enabled: !!backend && consent.data?.enabled === true,
  });
  const messages = useQuery({
    queryKey: ["chat-messages", sessionId],
    queryFn: () => backend!.listChatMessages(sessionId!),
    enabled: !!backend && !!sessionId,
  });

  const setConsent = useMutation({
    mutationFn: (input: { enabled: boolean; version: string }) =>
      backend!.setModelContextConsent(input.enabled, input.version),
    onSuccess: (row) => queryClient.setQueryData(["model-context-consent"], row),
  });

  const createSession = useMutation({
    mutationFn: (clientRequestId: string) => backend!.createChatSession({ clientRequestId }),
    onSuccess: (session: ChatSession) => {
      setSessionId(session.id);
      void queryClient.invalidateQueries({ queryKey: ["chat-sessions"] });
    },
  });
  const deleteSession = useMutation({
    mutationFn: (id: string) => backend!.deleteChatSession(id),
    onSuccess: (_data, id) => {
      setSessionDeleteError(null);
      if (sessionId === id) { setSessionId(null); setRunOutcome(null); }
      void queryClient.invalidateQueries({ queryKey: ["chat-sessions"] });
    },
    onError: (error) => setSessionDeleteError(errorText(error)),
  });

  const send = useMutation({
    mutationFn: (input: { content: string; clientMessageId: string }) =>
      backend!.sendChatMessage(sessionId!, input.content, input.clientMessageId),
    onSuccess: (response) => {
      setFailedSend(null);
      setRunOutcome(null);
      setRunError(null);
      setPollNotice(null);
      setActiveRun({ runId: response.run_id, attempts: 0 });
      void queryClient.invalidateQueries({ queryKey: ["chat-messages", sessionId] });
    },
    onError: (error, input) => {
      if (error instanceof BackendHttpError) {
        setRunError(error.status === 403
          ? "模型上下文同意未开启：请先阅读并同意上方的授权说明。"
          : `发送失败：${errorText(error)}`);
        return;
      }
      // 网络失败：保留同一 client_message_id 的重发入口（幂等返回同一 run）
      setFailedSend(input);
    },
  });

  async function runSearch(cursor?: string) {
    if (!backend || !searchInput.trim()) return;
    setSearchBusy(true);
    setSearchError(null);
    try {
      const page = await backend.searchChatMessages({ q: searchInput.trim() }, cursor);
      setSearchResults((previous) => previous && cursor
        ? { items: [...previous.items, ...page.items], nextCursor: page.next_cursor }
        : { items: page.items, nextCursor: page.next_cursor });
    } catch (error) {
      setSearchError(errorText(error));
    } finally {
      setSearchBusy(false);
    }
  }

  // 有限轮询（§5：非终态 run 定期查询，封顶 MAX_RUN_POLLS；终态或
  // WAITING_CONFIRMATION 即结算并刷新消息——响应永远以服务端为准）。
  useEffect(() => {
    if (!backend || !activeRun) return;
    let cancelled = false;
    const timer = window.setTimeout(() => {
      void backend.getAgentRun(activeRun.runId).then((run) => {
        if (cancelled) return;
        if (SETTLED_RUN_STATUSES.has(run.status)) {
          setRunOutcome(runOutcomeText(run));
          setActiveRun(null);
          void queryClient.invalidateQueries({ queryKey: ["chat-messages", sessionId] });
        } else if (activeRun.attempts + 1 >= MAX_RUN_POLLS) {
          setPollNotice("本轮仍在处理：稍后可手动刷新消息，不会重复发送。");
          setActiveRun(null);
        } else {
          setActiveRun({ runId: activeRun.runId, attempts: activeRun.attempts + 1 });
        }
      }).catch((error) => {
        if (cancelled) return;
        setRunError(`查询进度失败：${errorText(error)}`);
        setActiveRun(null);
      });
    }, 3_000);
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, [backend, activeRun, sessionId, queryClient]);

  const inputRef = useRef<HTMLTextAreaElement | null>(null);

  if (!backend) {
    return <section className="chat-view"><h2>对话</h2>
      <p role="status">未连接 Backend：对话不可用，也不会缓存任何待发送消息。</p>
    </section>;
  }
  if (consent.isError) {
    return <section className="chat-view"><h2>对话</h2>
      <p role="alert">加载授权状态失败：{errorText(consent.error)}</p>
    </section>;
  }
  if (!consent.data) {
    return <section className="chat-view"><h2>对话</h2><p role="status">正在加载授权状态…</p></section>;
  }
  if (!consent.data.enabled) {
    return <section className="chat-view"><h2>对话</h2>
      <div className="consent-panel">
        <p className="field-label">开启前请阅读授权说明</p>
        <p className="consent-text">{consent.data.consent_text}</p>
        {setConsent.isError && <p role="alert">{errorText(setConsent.error)}</p>}
        <button type="button" className="primary" disabled={setConsent.isPending}
          onClick={() => setConsent.mutate({ enabled: true, version: consent.data!.consent_text_version })}>
          同意并开启
        </button>
        <p className="field-label">默认关闭；开启后 CurrentState、记忆与对话内容才会进入模型上下文，可随时撤销。</p>
      </div>
    </section>;
  }

  function submitSend(content: string, clientMessageId: string) {
    if (!content.trim() || !sessionId) return;
    send.mutate({ content: content.trim(), clientMessageId });
  }

  return <section className="chat-view">
    <h2>对话</h2>
    <p className="field-label">模型上下文授权：已开启{consent.data.consented_at ? `（${new Date(consent.data.consented_at).toLocaleString()}）` : ""}
      {" "}<button type="button" className="link" disabled={setConsent.isPending}
        onClick={() => setConsent.mutate({ enabled: false, version: consent.data!.consent_text_version })}>撤销</button>
    </p>
    <div className="chat-workspace">
      <aside className="chat-sessions">
        <button type="button" className="primary" disabled={createSession.isPending}
          onClick={() => createSession.mutate(newClientId("chat-session"))}>新会话</button>
        {createSession.isError && <p role="alert">{errorText(createSession.error)}</p>}
        {sessionDeleteError && <p role="alert">会话删除未完成：{sessionDeleteError}</p>}
        {sessions.isError && <p role="alert">会话加载失败：{errorText(sessions.error)}</p>}
        {sessions.data?.map((session) => <div key={session.id} className={`chat-session-row ${session.id === sessionId ? "active" : ""}`}>
          <button type="button" onClick={() => { setSessionId(session.id); setRunOutcome(null); }}>
            {session.title || "未命名会话"}
          </button>
          <button type="button" className="chat-session-delete" title="删除会话"
            onClick={() => { if (window.confirm("删除整个会话及其全部消息？")) deleteSession.mutate(session.id); }}>
            ×
          </button>
        </div>)}
        {sessions.data?.length === 0 && <p className="field-label">还没有会话。</p>}
      </aside>
      <div className="chat-main">
        <form className="chat-search" onSubmit={(event) => { event.preventDefault(); void runSearch(); }}>
          <label className="field-label" htmlFor="chat-search">搜索</label>
          <div className="chat-search-row">
            <input id="chat-search" value={searchInput} onChange={(event) => setSearchInput(event.target.value)}
              placeholder="跨会话搜索原消息（命中显示会话与时间，深链进入）" />
            <button type="submit" disabled={searchBusy || !searchInput.trim()}>搜索</button>
          </div>
        </form>
        {searchError && <p role="alert">搜索失败：{searchError}</p>}
        {searchResults && <div className="chat-search-results">
          {searchResults.items.length === 0 && <p className="field-label">没有命中的消息。</p>}
          <ul>
            {searchResults.items.map((hit) => <li key={hit.id}>
              <button type="button" className="chat-search-hit" onClick={() => {
                setSessionId(hit.session_id);
                setRunOutcome(null);
                setSearchResults(null);
              }}>
                {hit.session_title} · {new Date(hit.created_at).toLocaleString()}
              </button>
              <p className="chat-search-content">{hit.content}</p>
            </li>)}
          </ul>
          {searchResults.nextCursor && <button type="button" disabled={searchBusy} onClick={() => void runSearch(searchResults.nextCursor!)}>加载更多</button>}
        </div>}
        {!sessionId && <p className="field-label">选择或创建一个会话开始对话。</p>}
        {sessionId && <>
          {messages.isError && <p role="alert">消息加载失败：{errorText(messages.error)}</p>}
          <ul className="chat-messages">
            {(messages.data ?? []).map((message) =>
              <MessageBubble key={message.id} message={message} backend={backend} onOpenAction={openAction} />)}
            {messages.isSuccess && messages.data.length === 0 && <li className="field-label">会话为空。</li>}
          </ul>
          {activeRun && <p role="status" className="chat-run-status">模型处理中（第 {activeRun.attempts + 1} 次查询）…</p>}
          {pollNotice && <p role="status">{pollNotice}</p>}
          {runOutcome && <p role="status" className="chat-run-outcome">{runOutcome}</p>}
          {runError && <p role="alert">{runError}</p>}
          {failedSend && <div className="chat-failed-send" role="alert">
            <p>上条消息未确认送达（{errorText(send.error)}）。以同一请求重发不会产生重复回复。</p>
            <button type="button" disabled={send.isPending} onClick={() => submitSend(failedSend.content, failedSend.clientMessageId)}>重发同一消息</button>
            <button type="button" disabled={send.isPending} onClick={() => setFailedSend(null)}>放弃</button>
          </div>}
          <form className="chat-input" onSubmit={(event) => {
            event.preventDefault();
            const content = draft;
            setDraft("");
            submitSend(content, newClientId("chat-msg"));
          }}>
            <label className="field-label" htmlFor="chat-input">消息</label>
            <textarea id="chat-input" ref={inputRef} rows={2} value={draft}
              onChange={(event) => setDraft(event.target.value)}
              placeholder={activeRun ? "模型处理中…" : "向 Agent 提问或下达指令"} />
            <button type="submit" className="primary" disabled={send.isPending || !draft.trim()}>发送</button>
          </form>
        </>}
      </div>
    </div>
  </section>;
}
