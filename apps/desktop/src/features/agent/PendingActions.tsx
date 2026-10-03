import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { PendingActionRead } from "@agenthu/contracts";
import { BackendHttpError, type BackendClient } from "../../backend/client";
import { errorText } from "../../lib/errors";
import { DecisionBasisView } from "./DecisionBasisView";

/** 待确认动作面（契约 §3）：8 态呈现、仅 PENDING 倒计时、mutation 防双击、
 *  409 refetch、用户自致失败子码单列文案、更新类参数「旧 → 新」渲染。
 *
 *  离线纪律（§7）：确认/忽略/重试绝不本地排队、不伪造本地成功——按钮只在
 *  Backend 会话就绪时可用；网络失败如实区分「没有执行」与「执行结果未知」，
 *  结果未知只能以同一 mutation_id 重发（服务端幂等结算）或刷新状态。 */

const USER_CAUSED_FAILURE_CODES = new Set(["permission_revoked", "consent_revoked", "source_deleted"]);

const STATUS_LINES: Record<PendingActionRead["status"], string> = {
  PENDING: "待你决定",
  CONFIRMED: "已确认，等待执行",
  EXECUTING: "正在执行",
  SUCCEEDED: "已完成",
  FAILED_RETRYABLE: "执行失败（可原参数重试）",
  FAILED: "最终失败",
  IGNORED: "已忽略",
  EXPIRED: "已过期（未确认）",
};

function newMutationId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") return crypto.randomUUID();
  return `mut-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

function formatRemaining(expiresAt: string, now: number): string {
  const remaining = new Date(expiresAt).getTime() - now;
  if (Number.isNaN(remaining)) return "";
  if (remaining <= 0) return "已过显示的到期时间（以服务端状态为准）";
  const minutes = Math.floor(remaining / 60_000);
  const seconds = Math.floor((remaining % 60_000) / 1_000);
  return minutes > 0 ? `${minutes} 分 ${seconds} 秒后到期` : `${seconds} 秒后到期`;
}

/** 「确认执行」带动词对象（§3.1 第 4 条）：用服务端 display 摘要，不造
 *  模糊的「确定」。 */
function confirmLabel(action: PendingActionRead): string {
  return `确认：${action.display.summary}`;
}

function safeErrorLine(action: PendingActionRead): { title: string; userCaused: boolean } | null {
  const error = action.safe_error;
  if (!error) return null;
  // 用户自致子码（B3 裁定）：撤销授权/同意或来源删除是用户自己的选择，
  // 不显示为系统故障。
  if (action.status === "FAILED" && USER_CAUSED_FAILURE_CODES.has(error.code)) {
    return { title: "你撤销了授权/同意（或来源已删除），动作已失效", userCaused: true };
  }
  return { title: `${error.code}：${error.message}`, userCaused: false };
}

function resultLine(action: PendingActionRead): string | null {
  if (action.status !== "SUCCEEDED" || !action.result) return null;
  const resource = action.result.resource_type
    ? `（${action.result.resource_type}${action.result.resource_id ? ` ${action.result.resource_id.slice(0, 8)}` : ""}）`
    : "";
  return `${action.result.summary}${resource}`;
}

interface CardMutationState {
  kind: "confirm" | "ignore" | "retry";
  mutationId: string;
  unknownOutcome: boolean;
  message: string | null;
}

export function PendingActionCard({ action, backend }: { action: PendingActionRead; backend: BackendClient }) {
  const queryClient = useQueryClient();
  const [showBasis, setShowBasis] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  const [mutationState, setMutationState] = useState<CardMutationState | null>(null);
  // 倒计时只在 PENDING 渲染（§2：到期仅自 PENDING；确认后不再过期）
  useEffect(() => {
    if (action.status !== "PENDING") return;
    const timer = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => window.clearInterval(timer);
  }, [action.status]);

  const refetchActions = () => queryClient.invalidateQueries({ queryKey: ["pending-actions"] });

  const mutation = useMutation({
    mutationFn: (input: { kind: CardMutationState["kind"]; mutationId: string }) => {
      if (input.kind === "confirm") return backend.confirmPendingAction(action.id, action.version, input.mutationId);
      if (input.kind === "ignore") return backend.ignorePendingAction(action.id, action.version, input.mutationId);
      return backend.retryPendingAction(action.id, action.version, input.mutationId);
    },
    onSuccess: () => {
      setMutationState(null);
      void refetchActions();
    },
    onError: (error, input) => {
      if (error instanceof BackendHttpError && error.status === 409) {
        // 已被抢先结算/过期：以服务端状态重新呈现，不向用户声称失败
        setMutationState(null);
        void refetchActions();
        return;
      }
      // 网络层失败（未收到服务端裁定）：结果未知——保留同一 mutation_id
      // 的重发入口（服务端幂等返回前次结算），并提供刷新。
      setMutationState({
        kind: input.kind,
        mutationId: input.mutationId,
        unknownOutcome: true,
        message: `请求未确认送达：${errorText(error)}。动作状态以服务端为准。`,
      });
    },
  });

  const busy = mutation.isPending;
  const error = safeErrorLine(action);
  const result = resultLine(action);
  const canConfirm = action.status === "PENDING";
  const canIgnore = action.status === "PENDING";
  const canRetry = action.status === "FAILED_RETRYABLE" && action.retryable;

  function startMutation(kind: CardMutationState["kind"]) {
    const mutationId = newMutationId();
    setMutationState({ kind, mutationId, unknownOutcome: false, message: null });
    mutation.mutate({ kind, mutationId });
  }

  return <article className={`pending-action-card status-${action.status.toLowerCase()}`} id={`pending-action-${action.id}`}>
    <header className="pending-action-head">
      <h3>{action.tool.title}</h3>
      <span className="pending-action-level">
        {action.required_level === 3 ? "Level 3 · 已授权自动执行" : "Level 2 · 需要确认"}
      </span>
    </header>
    <p className="pending-action-summary">{action.display.summary}</p>
    {action.display.parameters.length > 0 && <dl className="pending-action-params">
      {/* 更新类动作的「字段：旧值 → 新值」由服务端 display_builder 生成，
          此处按行渲染并换行容错，未变字段服务端不下发。 */}
      {action.display.parameters.map((parameter) => <div key={parameter.label}>
        <dt>{parameter.label}</dt>
        <dd>{parameter.value}</dd>
      </div>)}
    </dl>}
    <p className="pending-action-impact">影响：{action.display.impact}</p>
    {action.display.risk_note && <p className="pending-action-risk">风险：{action.display.risk_note}</p>}
    {action.status === "PENDING" && <p className="pending-action-expiry">
      到期：{new Date(action.expires_at).toLocaleString()}（{formatRemaining(action.expires_at, now)}）
    </p>}
    {error && <p className={`pending-action-error ${error.userCaused ? "user-caused" : ""}`}>{error.title}</p>}
    {result && <p className="pending-action-result">{result}</p>}
    <button type="button" className="pending-action-why" aria-expanded={showBasis} onClick={() => setShowBasis(!showBasis)}>
      为什么
    </button>
    {showBasis && <DecisionBasisView basis={action.basis} />}
    {mutationState?.unknownOutcome && <div className="pending-action-unknown" role="alert">
      <p>{mutationState.message}</p>
      <button type="button" disabled={busy} onClick={() => mutation.mutate({ kind: mutationState.kind, mutationId: mutationState.mutationId })}>
        重发同一请求
      </button>
      <button type="button" disabled={busy} onClick={() => void refetchActions()}>刷新状态</button>
    </div>}
    <footer className="pending-action-actions">
      {canConfirm && <button type="button" className="primary" disabled={busy} onClick={() => startMutation("confirm")}>
        {confirmLabel(action)}
      </button>}
      {canIgnore && <button type="button" disabled={busy} onClick={() => startMutation("ignore")}>忽略</button>}
      {canRetry && <button type="button" disabled={busy} onClick={() => startMutation("retry")}>按原参数重试</button>}
      {(action.status === "CONFIRMED" || action.status === "EXECUTING") && <button type="button" disabled={busy} onClick={() => void refetchActions()}>刷新</button>}
      <span className="pending-action-status">{STATUS_LINES[action.status]}</span>
    </footer>
  </article>;
}

export function PendingActionsView({ backend, focusActionId, onFocusHandled }: {
  backend: BackendClient | null;
  focusActionId?: string | null;
  onFocusHandled?: () => void;
}) {
  const [tab, setTab] = useState<"active" | "history">("active");
  const actions = useQuery({
    queryKey: ["pending-actions", tab],
    queryFn: () => backend!.listPendingActions(tab),
    enabled: !!backend,
  });

  useEffect(() => {
    if (!focusActionId || actions.isLoading) return;
    const element = document.getElementById(`pending-action-${focusActionId}`);
    if (element) {
      element.scrollIntoView({ block: "center", behavior: "smooth" });
      element.classList.add("deep-link-focus");
      onFocusHandled?.();
    }
  }, [focusActionId, actions.isLoading, actions.data, onFocusHandled]);

  if (!backend) {
    return <section className="pending-actions-view"><h2>待你决定</h2>
      <p role="status">未连接 Backend：确认、忽略和重试不可用。本地不会替你记录任何确认。</p>
    </section>;
  }

  return <section className="pending-actions-view">
    <h2>待你决定</h2>
    <div className="pending-actions-tabs" role="tablist">
      <button type="button" role="tab" aria-selected={tab === "active"} onClick={() => setTab("active")}>待确认</button>
      <button type="button" role="tab" aria-selected={tab === "history"} onClick={() => setTab("history")}>历史账本</button>
      <button type="button" onClick={() => void actions.refetch()} disabled={actions.isFetching}>刷新</button>
    </div>
    {actions.isError && <p role="alert" className="pending-actions-error">加载失败：{errorText(actions.error)}</p>}
    {actions.isSuccess && actions.data.length === 0 && (
      <p>{tab === "active" ? "没有待确认的动作。" : "历史账本为空。"}</p>
    )}
    {actions.isSuccess && actions.data.length > 0 && <div className="pending-action-list">
      {actions.data.map((action) => <PendingActionCard key={action.id} action={action} backend={backend} />)}
    </div>}
  </section>;
}
