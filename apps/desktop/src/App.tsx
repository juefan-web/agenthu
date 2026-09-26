import { useEffect, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { FocusSession, Task } from "@agenthu/contracts";
import { createCampusRuntime } from "./adapters/campus/runtime";
import type { SessionStatus } from "./adapters/campus/types";
import { CampusAuthError } from "./adapters/campus/types";
import { isTauriRuntime } from "./adapters/campus/tauriTransport";
import { BackendClient } from "./backend/client";
import { createFocusDraftStore } from "./focus/draft";
import { useSessionStore } from "./state/session";
import { EventSyncCoordinator } from "./sync/coordinator";
import { createEventQueue } from "./sync/queue";

const backendUrl = import.meta.env.VITE_BACKEND_URL?.replace(/\/$/, "") ?? "";
const backend = backendUrl ? new BackendClient({ baseUrl: backendUrl }) : null;
const campus = createCampusRuntime().adapter;
const queue = createEventQueue();
const focusDraft = createFocusDraftStore();
const sync = backend ? new EventSyncCoordinator(backend, queue) : null;
type View = "today" | "tasks" | "focus";

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function applySession(status: SessionStatus): void {
  useSessionStore.getState().setTwoFactor(status.state === "need-2fa" ? status.methods : [], status.state === "need-2fa" && !!status.codeSent, status.state === "need-2fa" ? status.selectedMethod : undefined);
  useSessionStore.getState().setStatus(
    status.state,
    status.username,
    status.state === "error" ? status.message : null,
  );
}

export default function App() {
  const [view, setView] = useState<View>("today");
  const [notice, setNotice] = useState<string | null>(null);
  const [pending, setPending] = useState(0);
  const [collectionElapsed, setCollectionElapsed] = useState(0);
  const session = useSessionStore();
  const queryClient = useQueryClient();
  const tasks = useQuery({ queryKey: ["tasks"], queryFn: () => backend!.getTasks(), enabled: !!backend });
  const plan = useQuery({ queryKey: ["plan"], queryFn: () => backend!.getTodayPlan(), enabled: !!backend });
  const currentState = useQuery({ queryKey: ["current-state"], queryFn: () => backend!.getCurrentState(), enabled: !!backend });

  useEffect(() => {
    void campus.restore().then(applySession).catch((error) => setNotice(errorText(error)));
    void queue.list().then((events) => setPending(events.length));
  }, []);

  useEffect(() => {
    if (!sync) return;
    const retryOnReconnect = () => {
      void sync.flush()
        .then((result) => {
          setPending(result.pending);
          if (result.sent || result.duplicates) void queryClient.invalidateQueries();
        })
        .catch(() => undefined);
    };
    window.addEventListener("online", retryOnReconnect);
    return () => window.removeEventListener("online", retryOnReconnect);
  }, [queryClient]);

  const collect = useMutation({
    mutationFn: async () => {
      const snapshot = await campus.collectSnapshot();
      setNotice(`校园数据已采集 ${snapshot.events.length} 条，正在同步…`);
      if (sync) await sync.enqueue(snapshot.events);
      else await queue.add(snapshot.events);
      const result = sync ? await sync.flush() : null;
      setPending((await queue.list()).length);
      return { collected: snapshot.events.length, result };
    },
    onSuccess: ({ collected, result }) => {
      setNotice(result
        ? `采集 ${collected} 条，上传 ${result.sent} 条，重复 ${result.duplicates} 条，待同步 ${result.pending} 条。`
        : `采集 ${collected} 条，已保存到本地队列；配置 Backend 后可上传。`);
      void queryClient.invalidateQueries();
    },
    onError: (error) => {
      if (error instanceof CampusAuthError) applySession({ state: "error", username: null, message: error.message });
      void queue.list().then((events) => setPending(events.length));
      setNotice(`同步未完成，事件留在本地队列：${errorText(error)}`);
    },
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
      setNotice(`上传 ${result.sent} 条，重复 ${result.duplicates} 条，待同步 ${result.pending} 条。`);
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
        </div>
      </header>
      {notice && <div className="notice" role="status">{notice}</div>}
      {view === "today" && <div className="workspace-grid">
        <section className="workspace-section">
          <div className="section-heading"><h2>校园数据</h2><span className="section-meta">课程 · 作业 · 课表 · 校历</span></div>
          <CampusConnection onError={(error) => setNotice(errorText(error))} />
          <div className="section-actions"><button className="primary-button" disabled={session.status !== "ready" || collect.isPending} onClick={() => collect.mutate()}>{collect.isPending ? `正在采集（${collectionElapsed}s）…` : "采集并同步"}</button></div>
        </section>
        <section className="workspace-section">
          <div className="section-heading"><h2>今日计划</h2><span className="section-meta">{currentState.data?.context ?? "当前上下文未设置"}</span></div>
          <PlanView plan={plan.data} loading={plan.isPending && !!backend} error={plan.error} onChanged={() => void queryClient.invalidateQueries({ queryKey: ["plan"] })} />
        </section>
        <section className="workspace-section wide"><div className="section-heading"><h2>待办任务</h2><span className="section-meta">{taskList.length} 项</span></div><TaskList tasks={taskList} loading={tasks.isPending && !!backend} error={tasks.error ?? currentState.error} /></section>
      </div>}
      {view === "tasks" && <section className="workspace-section"><div className="section-heading"><h2>全部任务</h2><span className="section-meta">{taskList.length} 项</span></div><TaskList tasks={taskList} loading={tasks.isPending && !!backend} error={tasks.error} /></section>}
      {view === "focus" && <FocusView tasks={taskList} />}
    </section>
  </main>;
}

function CampusConnection({ onError }: { onError: (error: unknown) => void }) {
  const { status, message, methods, codeSent, selectedMethod } = useSessionStore();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [method, setMethod] = useState("totp");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [trustDevice, setTrustDevice] = useState(false);
  const activeMethod = methods.includes(method) ? method : methods[0] ?? "";

  async function login(event: FormEvent) {
    event.preventDefault(); setBusy(true);
    const input = { username, password }; setPassword("");
    try { applySession(await campus.login(input)); }
    catch (error) { onError(error); }
    finally { setBusy(false); }
  }
  async function verify(event: FormEvent) {
    event.preventDefault(); setBusy(true);
    const input = { method: selectedMethod, code, trustDevice }; setCode("");
    try { applySession(await campus.verify2fa(input)); }
    catch (error) { onError(error); }
    finally { setBusy(false); }
  }
  async function sendCode() {
    setBusy(true);
    try { applySession(await campus.send2fa(activeMethod)); }
    catch (error) { onError(error); }
    finally { setBusy(false); }
  }
  async function cancel() {
    setBusy(true);
    try { await campus.logout(); useSessionStore.getState().reset(); setCode(""); }
    catch (error) { onError(error); }
    finally { setBusy(false); }
  }
  if (status === "ready") return <p className="connected-message">校园会话已连接，可采集最新数据。</p>;
  if (!isTauriRuntime()) return <p className="empty-state">校园登录仅在 Tauri 客户端中可用。</p>;
  return <>
    {message && <p className="error-text" role="alert">{message}</p>}
    {status === "need-2fa" ? <form className="inline-form" onSubmit={(event) => void verify(event)}>
      <label>验证方式<select value={codeSent ? selectedMethod : activeMethod} disabled={busy || codeSent} onChange={(event) => setMethod(event.target.value)}>{methods.map((item) => <option key={item} value={item}>{({ totp: "TOTP", mobile: "短信", wechat: "企业微信" } as Record<string, string>)[item] ?? item}</option>)}</select></label>
      {!codeSent && <button type="button" className="primary-button" disabled={busy || !activeMethod} onClick={() => void sendCode()}>{activeMethod === "totp" ? "使用验证器" : "发送验证码"}</button>}
      {codeSent && <><label>验证码<input value={code} onChange={(event) => setCode(event.target.value)} autoComplete="one-time-code" required /></label><label className="checkbox-label"><input type="checkbox" checked={trustDevice} onChange={(event) => setTrustDevice(event.target.checked)} />信任此设备</label><button className="primary-button" disabled={busy}>验证</button></>}
      <button type="button" className="ghost-button" onClick={() => void cancel()}>取消</button>
    </form> : <form className="inline-form" onSubmit={(event) => void login(event)}>
      <label>学号<input value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="username" required /></label>
      <label>密码<input type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" required /></label>
      <button className="primary-button" disabled={busy}>登录</button>
    </form>}
  </>;
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
  return <><div className="plan-list">{plan.items.map((item) => <div className="plan-row" key={`${item.task_id}:${item.start_at}`}><time>{new Date(item.start_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</time><div><strong>{item.task_id}</strong><span>{item.reason}</span></div></div>)}</div>{plan.confirmation_required && plan.status === "draft" && <button className="primary-button" disabled={confirm.isPending} onClick={() => confirm.mutate()}>确认计划</button>}{confirm.error && <p className="error-text">{errorText(confirm.error)}</p>}</>;
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
      const next = await backend.updateFocus(active.id, { status, deviation_note: status === "completed" ? note || null : active.deviation_note, ended_at: status === "completed" ? new Date().toISOString() : null });
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
