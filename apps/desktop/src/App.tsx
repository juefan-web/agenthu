import { useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CampusAuthError } from "./adapters/campus/types";
import { isTauriRuntime } from "./adapters/campus/tauriTransport";
import { campus } from "./campus/instance";
import { CampusConnection, applySession } from "./components/CampusConnection";
import { AppServicesContext, createAppServices } from "./app/services";
import { BackendForms } from "./features/backend/BackendForms";
import { FocusView } from "./features/focus/FocusView";
import { PlanView } from "./features/plans/PlanView";
import { ReplanSuggestion } from "./features/plans/ReplanSuggestion";
import { TaskList } from "./features/tasks/TaskList";
import { MemoryView } from "./features/memory/MemoryView";
import { GroundedAnswersView } from "./features/grounding/GroundedAnswersView";
import { PendingActionsView } from "./features/agent/PendingActions";
import { ChatView } from "./features/chat/ChatView";
import { NotificationPreferencesView } from "./features/notifications/NotificationPreferencesView";
import { DataControlsView } from "./features/data-controls/DataControlsView";
import { ReceiptViewer } from "./features/data-controls/ReceiptViewer";
import { errorText } from "./lib/errors";
import { useSessionStore } from "./state/session";
import { formatAvailableMinutes } from "./state/format";
import { useBackendSessionStore } from "./state/backendSession";
import type { EventSyncCoordinator } from "./sync/coordinator";

type View = "today" | "tasks" | "focus" | "memory" | "explain" | "pending" | "chat" | "reminders" | "data";
const VIEW_LABELS: Record<View, string> = { today: "今天", tasks: "任务", focus: "专注", memory: "记忆", explain: "讲解", pending: "确认", chat: "对话", reminders: "提醒", data: "数据与隐私" };
type CollectionStage = "collecting" | "saving" | "syncing" | null;

function syncResultText(result: Awaited<ReturnType<EventSyncCoordinator["flush"]>>): string {
  const rejectionSummary = result.rejections.length > 0
    ? `拒绝 ${result.rejections.length} 条：${result.rejections.slice(0, 3).map(({ reason }) => reason).join("；")}${result.rejections.length > 3 ? `；另有 ${result.rejections.length - 3} 条` : ""}`
    : "";
  return `上传 ${result.sent} 条，重复 ${result.duplicates} 条${rejectionSummary ? `，${rejectionSummary}` : ""}，待同步 ${result.pending} 条。`;
}

export default function App() {
  // 应用级单例经 Context 注入（M2 拆分）：视图经 useServices() 取用，测试可替换
  const [services] = useState(() => createAppServices());
  const { backend, backendSession, backendUrl, queue, sync } = services;
  const [view, setView] = useState<View>("today");
  // Chat → 确认卡片的深链（契约 §3.1：同一 id 只有一张卡，聊天不提供绕过
  // 确认的快捷执行）
  const [focusActionId, setFocusActionId] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [pending, setPending] = useState(0);
  const [collectionElapsed, setCollectionElapsed] = useState(0);
  const [collectionStage, setCollectionStage] = useState<CollectionStage>(null);
  const [showReceipts, setShowReceipts] = useState(false);
  const session = useSessionStore();
  const backendState = useBackendSessionStore();
  const queryClient = useQueryClient();
  const backendReady = !!backend && backendState.status === "ready";
  const tasks = useQuery({ queryKey: ["tasks"], queryFn: () => backend!.getTasks(), enabled: backendReady });
  const plan = useQuery({ queryKey: ["plan"], queryFn: () => backend!.getTodayPlan(), enabled: backendReady });
  const currentState = useQuery({ queryKey: ["current-state"], queryFn: () => backend!.getCurrentState(), enabled: backendReady });
  // 「待你决定」徽标（契约 §3.1：应用根部可见）：与 PendingActionsView
  // 共用 query key，缓存互备。
  const activeActions = useQuery({
    queryKey: ["pending-actions", "active"],
    queryFn: () => backend!.listPendingActions("active"),
    enabled: backendReady,
  });

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

  async function backendLogout() {
    try {
      await backendSession?.logout();
    } catch (error) {
      setNotice(errorText(error));
    }
    // 退出即忘却：查询缓存是用户作用域的数据，但键上没有用户维度——失效
    // 只会拿已死 token 立刻重取且错误态保留旧 data，下一个用户登录后在未
    // 重挂载的视图里会端出前一账号的缓存（E6 s1 首跑实证）。整池清空才
    // 是「换用户」的诚实语义；登录后各视图按挂载重取。
    queryClient.clear();
  }

  // 外审 #27：401 失效与显式 logout 同为「换用户前奏」——session 已清
  // token/owner，但查询池不随之清，下一账号在未重挂载的视图里会端出前
  // 一账号的缓存（backendLogout 注释的同一实证，补齐失效路径）。
  useEffect(() => {
    if (backendState.invalidations > 0) queryClient.clear();
  }, [backendState.invalidations, queryClient]);

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
    const update = () => setCollectionElapsed(Math.floor((Date.now() - startedAt) / 1_000));
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
  return <AppServicesContext.Provider value={services}>
    <main className="shell">
      <aside className="sidebar">
        <div className="brand">agenthu</div>
        <nav aria-label="主导航">
          {(Object.keys(VIEW_LABELS) as View[]).map((item) =>
            <button key={item} className={`nav-item ${view === item ? "active" : ""}`} onClick={() => setView(item)}>
              {VIEW_LABELS[item]}
              {item === "pending" && (activeActions.data?.length ?? 0) > 0 && <span className="nav-badge">{activeActions.data?.length}</span>}
            </button>)}
        </nav>
        <div className="sidebar-footer"><span className={`status-dot ${session.status}`} />{session.status === "ready" ? `${session.username} 已连接` : "校园未连接"}</div>
      </aside>

      <section className="content">
        <header className="topbar">
          <div><p className="eyebrow">STUDY / TIME</p><h1>{VIEW_LABELS[view]}</h1></div>
          <div className="top-actions">
            {pending > 0 && <span className="pending-count">{pending} 条待同步</span>}
            <button className="ghost-button" disabled={!sync || pending === 0 || retry.isPending} onClick={() => retry.mutate()}>重试同步</button>
            {session.status === "ready" && <button className="ghost-button" onClick={() => void logout()}>退出校园账号</button>}
            {backendState.status === "ready" && <button className="ghost-button" onClick={() => void backendLogout()}>退出 Backend</button>}
          </div>
        </header>
        {backend && backendState.status !== "ready" && <BackendForms onNotice={setNotice} />}
        {/* 回执独立入口（B 稿 §1）：业务 401/未登录时仍可读——不经业务会话
            与 React Query；capability 只在 ReceiptViewer 内部流转 */}
        {backend && backendState.status !== "ready" && <div className="top-actions" style={{ justifyContent: "flex-start" }}>
          <button className="ghost-button" onClick={() => setShowReceipts((value) => !value)}>{showReceipts ? "收起删除回执" : "查看删除回执"}</button>
        </div>}
        {backend && showReceipts && backendState.status !== "ready" && <ReceiptViewer baseUrl={backendUrl} store={services.receipts} />}
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
            <ReplanSuggestion currentPlan={plan.data ?? undefined} />
            <PlanView plan={plan.data} loading={plan.isPending && !!backend} error={plan.error} onChanged={() => void queryClient.invalidateQueries({ queryKey: ["plan"] })} />
          </section>
          <section className="workspace-section wide"><div className="section-heading"><h2>待办任务</h2><span className="section-meta">{taskList.length} 项</span></div><TaskList tasks={taskList} loading={tasks.isPending && !!backend} error={tasks.error ?? currentState.error} configured={!!backend} /></section>
        </div>}
        {view === "tasks" && <section className="workspace-section"><div className="section-heading"><h2>全部任务</h2><span className="section-meta">{taskList.length} 项</span></div><TaskList tasks={taskList} loading={tasks.isPending && !!backend} error={tasks.error} configured={!!backend} /></section>}
        {/* 外审 #26：专注草稿存储已按 owner 命名空间，残留的是 mount 时读入
            的组件态——按账号 key 重挂载，登出/换号即重读当前 owner 的草稿 */}
        {view === "focus" && <FocusView key={backendState.userId ?? "anonymous"} tasks={taskList} />}
        {view === "memory" && <MemoryView />}
        {view === "explain" && <GroundedAnswersView />}
        {view === "pending" && <PendingActionsView
          backend={backendReady ? backend : null}
          focusActionId={focusActionId}
          onFocusHandled={() => setFocusActionId(null)} />}
        {view === "chat" && <ChatView
          backend={backendReady ? backend : null}
          onOpenAction={(actionId) => { setFocusActionId(actionId); setView("pending"); }} />}
        {view === "reminders" && <NotificationPreferencesView backend={backendReady ? backend : null} />}
        {view === "data" && <DataControlsView />}
      </section>
    </main>
  </AppServicesContext.Provider>;
}
