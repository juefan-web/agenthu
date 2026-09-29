import { useEffect, useState, type FormEvent } from "react";
import { invoke } from "@tauri-apps/api/core";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { FocusSession, Task } from "@agenthu/contracts";
import { CampusAuthError } from "./adapters/campus/types";
import { isTauriRuntime } from "./adapters/campus/tauriTransport";
import { campus } from "./campus/instance";
import { CampusConnection, applySession } from "./components/CampusConnection";
import { BackendClient } from "./backend/client";
import { createBackendSession } from "./backend/session";
import { backendFetch } from "./backend/transport";
import { createFocusDraftStore } from "./focus/draft";
import { useSessionStore } from "./state/session";
import { formatAvailableMinutes } from "./state/format";
import { useBackendSessionStore } from "./state/backendSession";
import { EventSyncCoordinator } from "./sync/coordinator";
import { createEventQueue } from "./sync/queue";

const BUILD_TIME_BACKEND_URL = import.meta.env.VITE_BACKEND_URL?.replace(/\/$/, "") ?? "";
const BACKEND_URL_PREFERENCE_KEY = "agenthu.backend-url";

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

const backendUrl = readBackendUrlPreference();
const backendSession = backendUrl ? createBackendSession({
  baseUrl: backendUrl,
  fetcher: isTauriRuntime() ? backendFetch : undefined,
}) : null;
const backend = backendSession?.client ?? null;
const queue = createEventQueue();
const focusDraft = createFocusDraftStore();
const sync = backend ? new EventSyncCoordinator(backend, queue) : null;
type View = "today" | "tasks" | "focus";
type CollectionStage = "collecting" | "saving" | "syncing" | null;

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function syncResultText(result: Awaited<ReturnType<EventSyncCoordinator["flush"]>>): string {
  const rejectionSummary = result.rejections.length > 0
    ? `拒绝 ${result.rejections.length} 条：${result.rejections.slice(0, 3).map(({ reason }) => reason).join("；")}${result.rejections.length > 3 ? `；另有 ${result.rejections.length - 3} 条` : ""}`
    : "";
  return `上传 ${result.sent} 条，重复 ${result.duplicates} 条${rejectionSummary ? `，${rejectionSummary}` : ""}，待同步 ${result.pending} 条。`;
}

export default function App() {
  const [view, setView] = useState<View>("today");
  const [notice, setNotice] = useState<string | null>(null);
  const [pending, setPending] = useState(0);
  const [collectionElapsed, setCollectionElapsed] = useState(0);
  const [collectionStage, setCollectionStage] = useState<CollectionStage>(null);
  const [backendEmail, setBackendEmail] = useState("");
  const [backendPassword, setBackendPassword] = useState("");
  const [backendBusy, setBackendBusy] = useState(false);
  const [backendOriginInput, setBackendOriginInput] = useState(backendUrl);
  const [backendOriginBusy, setBackendOriginBusy] = useState(false);
  const session = useSessionStore();
  const backendState = useBackendSessionStore();
  const queryClient = useQueryClient();
  const backendReady = !!backend && backendState.status === "ready";
  const tasks = useQuery({ queryKey: ["tasks"], queryFn: () => backend!.getTasks(), enabled: backendReady });
  const plan = useQuery({ queryKey: ["plan"], queryFn: () => backend!.getTodayPlan(), enabled: backendReady });
  const currentState = useQuery({ queryKey: ["current-state"], queryFn: () => backend!.getCurrentState(), enabled: backendReady });

  useEffect(() => {
    void campus.restore().then(applySession).catch((error) => setNotice(errorText(error)));
    void queue.list().then((events) => setPending(events.length));
    if (backendSession && isTauriRuntime()) {
      // B-4：先幂等登记 allowlist（构建期源已在 Rust 常量里，运行时源经此入列），
      // 再恢复会话——首个请求不会因源未登记被拒。
      void (async () => {
        try {
          await invoke("backend_origin_add", { origin: new URL(backendUrl).origin });
        } catch (error) {
          setNotice(`Backend 源登记失败：${errorText(error)}`);
        } finally {
          await backendSession?.restore();
        }
      })();
    } else if (backendSession) {
      void backendSession.restore();
    }
  }, []);

  async function backendLogin(event: FormEvent) {
    event.preventDefault();
    if (!backend) return;
    setBackendBusy(true);
    const email = backendEmail;
    const password = backendPassword;
    setBackendPassword("");
    try {
      await backendSession?.login(email, password);
      setNotice("Backend 已连接");
      await queryClient.invalidateQueries();
    } catch (error) { setNotice(errorText(error)); }
    finally { setBackendBusy(false); }
  }

  /** B-4 运行时源切换：Rust 侧先验证并入 allowlist，持久化偏好后重载生效
   *  （校验失败即拒，不落任何状态）。清空输入则回落构建期默认。 */
  async function saveBackendOrigin(event: FormEvent) {
    event.preventDefault();
    setBackendOriginBusy(true);
    try {
      const trimmed = backendOriginInput.trim().replace(/\/$/, "");
      if (!trimmed) {
        localStorage.removeItem(BACKEND_URL_PREFERENCE_KEY);
      } else {
        if (isTauriRuntime()) await invoke("backend_origin_add", { origin: new URL(trimmed).origin });
        localStorage.setItem(BACKEND_URL_PREFERENCE_KEY, trimmed);
      }
      window.location.reload();
    } catch (error) {
      setNotice(`Backend 地址无法使用：${errorText(error)}`);
      setBackendOriginBusy(false);
    }
  }

  async function backendLogout() {
    try {
      await backendSession?.logout();
    } catch (error) {
      setNotice(errorText(error));
    }
    try {
      await queryClient.invalidateQueries();
    } catch (error) {
      setNotice(errorText(error));
    }
  }

  useEffect(() => {
    if (!sync) return;
    const retryOnReconnect = () => {
      void sync.flush()
        .then((result) => {
          setPending(result.pending);
          if (result.rejected > 0) setNotice(`重新连接后同步完成：${syncResultText(result)}`);
          if (result.sent || result.duplicates) void queryClient.invalidateQueries();
        })
        .catch(() => undefined);
    };
    window.addEventListener("online", retryOnReconnect);
    return () => window.removeEventListener("online", retryOnReconnect);
  }, [queryClient]);

  const collect = useMutation({
    mutationFn: async () => {
      const startedAt = performance.now();
      let collected = 0;
      let saved = false;
      try {
        setCollectionStage("collecting");
        const snapshot = await campus.collectSnapshot();
        collected = snapshot.events.length;
        const collectionSeconds = ((performance.now() - startedAt) / 1_000).toFixed(1);
        setCollectionStage("saving");
        if (sync) await sync.enqueue(snapshot.events);
        else await queue.add(snapshot.events);
        saved = true;
        if (sync) setCollectionStage("syncing");
        const syncStartedAt = performance.now();
        const result = sync ? await sync.flush() : null;
        const syncSeconds = ((performance.now() - syncStartedAt) / 1_000).toFixed(1);
        setPending((await queue.list()).length);
        return { collected, collectionSeconds, syncSeconds, result };
      } catch (error) {
        setNotice(saved
          ? `采集 ${collected} 条已保存到本地，上传未完成：${errorText(error)}`
          : `校园数据未保存：${errorText(error)}`);
        throw error;
      }
    },
    onSuccess: ({ collected, collectionSeconds, syncSeconds, result }) => {
      setNotice(result
        ? `采集 ${collected} 条（${collectionSeconds} 秒），同步 ${syncSeconds} 秒；${syncResultText(result)}`
        : `采集 ${collected} 条（${collectionSeconds} 秒），已保存到本地队列；配置 Backend 后可上传。`);
      void queryClient.invalidateQueries();
    },
    onError: (error) => {
      if (error instanceof CampusAuthError) applySession({ state: "error", username: null, message: error.message });
      void queue.list().then((events) => setPending(events.length));
    },
    onSettled: () => setCollectionStage(null),
  });

  useEffect(() => {
    if (!collect.isPending) {
      setCollectionElapsed(0);
      return;
    }
    const startedAt = Date.now();
    const update = () => setCollectionElapsed(Math.floor((Date.now() - startedAt) / 1000));
    update();
    const timer = setInterval(update, 1_000);
    return () => clearInterval(timer);
  }, [collect.isPending]);

  const retry = useMutation({
    mutationFn: async () => {
      if (!sync) throw new Error("尚未配置 Backend 地址");
      const result = await sync.flush();
      setPending(result.pending);
      return result;
    },
    onSuccess: (result) => {
      setNotice(syncResultText(result));
      void queryClient.invalidateQueries();
    },
    onError: (error) => setNotice(errorText(error)),
  });

  async function logout() {
    await campus.logout();
    session.reset();
  }

  const taskList = tasks.data ?? currentState.data?.tasks ?? [];
  return <main className="shell">
    <aside className="sidebar">
      <div className="brand">agenthu</div>
      <nav aria-label="主导航">
        {(["today", "tasks", "focus"] as const).map((item) =>
          <button key={item} className={`nav-item ${view === item ? "active" : ""}`} onClick={() => setView(item)}>
            {item === "today" ? "今天" : item === "tasks" ? "任务" : "专注"}
          </button>)}
      </nav>
      <div className="sidebar-footer"><span className={`status-dot ${session.status}`} />{session.status === "ready" ? `${session.username} 已连接` : "校园未连接"}</div>
    </aside>

    <section className="content">
      <header className="topbar">
        <div><p className="eyebrow">STUDY / TIME</p><h1>{view === "today" ? "今天" : view === "tasks" ? "任务" : "专注"}</h1></div>
        <div className="top-actions">
          {pending > 0 && <span className="pending-count">{pending} 条待同步</span>}
          <button className="ghost-button" disabled={!sync || pending === 0 || retry.isPending} onClick={() => retry.mutate()}>重试同步</button>
          {session.status === "ready" && <button className="ghost-button" onClick={() => void logout()}>退出校园账号</button>}
          {backendState.status === "ready" && <button className="ghost-button" onClick={() => void backendLogout()}>退出 Backend</button>}
        </div>
      </header>
      {backend && backendState.status !== "ready" && <>
        <form className="backend-login" onSubmit={(event) => void saveBackendOrigin(event)}>
          <label>Backend 地址<input type="url" value={backendOriginInput} onChange={(event) => setBackendOriginInput(event.target.value)} placeholder={BUILD_TIME_BACKEND_URL || "https://api.example.com"} /></label>
          <button className="ghost-button" disabled={backendOriginBusy}>{backendOriginBusy ? "保存中…" : "保存并重载"}</button>
        </form>
        <form className="backend-login" onSubmit={(event) => void backendLogin(event)}>
          <label>Backend 邮箱<input type="email" value={backendEmail} onChange={(event) => setBackendEmail(event.target.value)} required /></label>
          <label>Backend 密码<input type="password" value={backendPassword} onChange={(event) => setBackendPassword(event.target.value)} required /></label>
          <button className="primary-button" disabled={backendBusy}>{backendBusy ? "登录中…" : "登录 Backend"}</button>
        </form>
      </>}
      {backendState.message && <p className="error-text" role="alert">{backendState.message}</p>}
      {notice && <div className="notice" role="status">{notice}</div>}
      {view === "today" && <div className="workspace-grid">
        <section className="workspace-section">
          <div className="section-heading"><h2>校园数据</h2><span className="section-meta">课程 · 作业 · 课表 · 校历</span></div>
          <CampusConnection onError={(error) => setNotice(errorText(error))} />
          <div className="section-actions"><button className="primary-button" disabled={session.status !== "ready" || collect.isPending} onClick={() => collect.mutate()}>{collect.isPending ? `${collectionStage === "saving" ? "正在保存" : collectionStage === "syncing" ? "正在同步" : "正在采集"}（${collectionElapsed}s）…` : "采集并同步"}</button></div>
        </section>
        <section className="workspace-section">
          <div className="section-heading"><h2>今日计划</h2><div className="section-heading-meta"><span className="section-meta">{currentState.data?.context ?? "当前上下文未设置"}</span>{currentState.data?.available_minutes != null && <span className="section-meta minutes-badge">剩余可用 {formatAvailableMinutes(currentState.data.available_minutes)}</span>}</div></div>
          <PlanView plan={plan.data} loading={plan.isPending && !!backend} error={plan.error} onChanged={() => void queryClient.invalidateQueries({ queryKey: ["plan"] })} />
        </section>
        <section className="workspace-section wide"><div className="section-heading"><h2>待办任务</h2><span className="section-meta">{taskList.length} 项</span></div><TaskList tasks={taskList} loading={tasks.isPending && !!backend} error={tasks.error ?? currentState.error} /></section>
      </div>}
      {view === "tasks" && <section className="workspace-section"><div className="section-heading"><h2>全部任务</h2><span className="section-meta">{taskList.length} 项</span></div><TaskList tasks={taskList} loading={tasks.isPending && !!backend} error={tasks.error} /></section>}
      {view === "focus" && <FocusView tasks={taskList} />}
    </section>
  </main>;
}

function TaskList({ tasks, loading, error }: { tasks: Task[]; loading: boolean; error: unknown }) {
  if (!backend) return <p className="empty-state">配置 Backend 地址后显示任务。</p>;
  if (loading) return <p className="empty-state">正在读取任务…</p>;
  if (error) return <p className="error-text">任务读取失败：{errorText(error)}</p>;
  if (tasks.length === 0) return <p className="empty-state">暂无任务。</p>;
  return <div className="task-list">{tasks.map((task) => <div className="task-row" key={task.id}><div><strong>{task.title}</strong><span>{task.due_at ? `截止 ${new Date(task.due_at).toLocaleString()}` : "无截止时间"}</span></div><span className="status-label">{task.status}</span></div>)}</div>;
}

function PlanView({ plan, loading, error, onChanged }: { plan: Awaited<ReturnType<BackendClient["getTodayPlan"]>> | undefined; loading: boolean; error: unknown; onChanged: () => void }) {
  const confirm = useMutation({ mutationFn: () => backend!.confirmPlan(plan!.id), onSuccess: onChanged });
  if (!backend) return <p className="empty-state">配置 Backend 地址后显示今日计划。</p>;
  if (loading) return <p className="empty-state">正在读取计划…</p>;
  if (error) return <p className="error-text">计划读取失败：{errorText(error)}</p>;
  if (!plan || plan.items.length === 0) return <p className="empty-state">今天还没有计划。</p>;
  return <><div className="plan-list">{plan.items.map((item) => <div className="plan-row" key={`${item.task_id}:${item.start_at}`}><time>{new Date(item.start_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</time><div><strong>{item.title}</strong><span>{item.reason}</span></div></div>)}</div>{plan.confirmation_required && plan.status === "draft" && <button className="primary-button" disabled={confirm.isPending} onClick={() => confirm.mutate()}>确认计划</button>}{confirm.error && <p className="error-text">{errorText(confirm.error)}</p>}</>;
}

function FocusView({ tasks }: { tasks: Task[] }) {
  const [taskId, setTaskId] = useState("");
  const [active, setActive] = useState<FocusSession | null>(null);
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [restoring, setRestoring] = useState(true);

  useEffect(() => {
    void focusDraft.read()
      .then((draft) => {
        if (draft) { setActive(draft.session); setNote(draft.note); }
      })
      .catch((cause) => setError(`本地专注记录读取失败：${errorText(cause)}`))
      .finally(() => setRestoring(false));
  }, []);

  async function start() {
    if (!backend || !taskId) return;
    setBusy(true);
    try {
      const next = await backend.startFocus(taskId);
      setActive(next); setError(null);
      await focusDraft.write({ session: next, note: "" });
    }
    catch (cause) { setError(errorText(cause)); }
    finally { setBusy(false); }
  }
  async function update(status: "paused" | "running" | "completed") {
    if (!backend || !active) return;
    setBusy(true);
    try {
      const next = await backend.updateFocus(active.id, { status, deviation_note: status === "completed" ? note || null : active.deviation_note });
      setActive(status === "completed" ? null : next); setError(null);
      if (status === "completed") setNote("");
      await focusDraft.write(status === "completed" ? null : { session: next, note });
    } catch (cause) { setError(errorText(cause)); }
    finally { setBusy(false); }
  }
  async function discard() {
    if (!window.confirm("清除这台设备上的专注草稿？Backend 中已记录的专注不会删除。")) return;
    try { await focusDraft.write(null); setActive(null); setNote(""); setError(null); }
    catch (cause) { setError(errorText(cause)); }
  }
  return <section className="workspace-section focus-workspace"><div className="section-heading"><h2>专注记录</h2><span className="section-meta">{active?.status ?? "未开始"}</span></div>{restoring ? <p className="empty-state">正在恢复专注记录…</p> : !backend ? <p className="empty-state">配置 Backend 地址后可以记录专注。</p> : active ? <><p>开始时间：{new Date(active.started_at).toLocaleString()}</p><div className="section-actions">{active.status === "running" ? <button className="ghost-button" disabled={busy} onClick={() => void update("paused")}>暂停</button> : <button className="ghost-button" disabled={busy} onClick={() => void update("running")}>继续</button>}</div><label className="note-label">实际偏差<textarea value={note} onChange={(event) => { const next = event.target.value; setNote(next); void focusDraft.write({ session: active, note: next }).catch((cause) => setError(errorText(cause))); }} rows={3} placeholder="可选：记录计划与实际的差异" /></label><div className="section-actions"><button className="primary-button" disabled={busy} onClick={() => void update("completed")}>完成专注</button><button className="ghost-button" disabled={busy} onClick={() => void discard()}>清除本地草稿</button></div></> : <><label className="note-label">选择任务<select value={taskId} onChange={(event) => setTaskId(event.target.value)}><option value="">选择一项任务</option>{tasks.filter((task) => task.status === "todo" || task.status === "in_progress").map((task) => <option value={task.id} key={task.id}>{task.title}</option>)}</select></label><button className="primary-button" disabled={!taskId || busy} onClick={() => void start()}>开始专注</button></>}{error && <p className="error-text" role="alert">{error}</p>}</section>;
}
