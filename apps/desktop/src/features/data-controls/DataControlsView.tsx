import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { invoke } from "@tauri-apps/api/core";
import type { DataOperationOut, DataPreviewOut, DeleteTarget } from "@agenthu/contracts";
import { isTauriRuntime } from "../../adapters/campus/tauriTransport";
import { BackendHttpError } from "../../backend/client";
import { useServices } from "../../app/services";
import { useBackendSessionStore } from "../../state/backendSession";
import { LocalFocusDraftStore } from "../../focus/draft";
import { focusDraftKey } from "../../sync/owner";
import { effectSummaryLine, knownErrorCopy, operationStatusLine, progressLine } from "./statusCopy";
import { useOperationPoll } from "./useOperationPoll";
import {
  type LocalCleanupDeps,
  type LocalCleanupRecord,
  cleanupStateText,
  readCleanupRecord,
  retryLocalCleanup,
  runLocalCleanup,
} from "./cleanup";

/** 「数据与隐私」页（B 稿 §1/§2/§3）：导出/删除全流 + 无主处置 + 本机
 *  清理状态面。React 不执行删除业务规则——effects/limitations/状态全部
 *  来自服务端响应；额度与残留推断一概不自算（P0-5 裁定④同源纪律）。 */

type TargetKind = "account" | "source" | "memory";

function errorCopy(error: unknown): string {
  if (error instanceof BackendHttpError) {
    return knownErrorCopy(error.code) ?? error.message;
  }
  return error instanceof Error ? error.message : String(error);
}

function newRequestId(): string {
  return (globalThis.crypto?.randomUUID?.() ?? `req-${Date.now()}-${Math.random().toString(36).slice(2)}`);
}

export function DataControlsView() {
  const services = useServices();
  const { backend, backendSession, queue, focusDraft, receipts, resolveOwner } = services;
  const backendState = useBackendSessionStore();
  const queryClient = useQueryClient();
  const backendReady = !!backend && backendState.status === "ready";

  const [targetKind, setTargetKind] = useState<TargetKind>("source");
  const [sourceKind, setSourceKind] = useState("event");
  const [idsText, setIdsText] = useState("");
  const [preview, setPreview] = useState<DataPreviewOut | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [exportIncludeFiles, setExportIncludeFiles] = useState(true);
  const [polledOperationId, setPolledOperationId] = useState<string | null>(null);
  const [accountStep, setAccountStep] = useState(0);
  const [accountAcknowledged, setAccountAcknowledged] = useState(false);
  const [cleanupOwnerKey, setCleanupOwnerKey] = useState<string | null>(null);
  const [cleanupRecord, setCleanupRecord] = useState<LocalCleanupRecord | null>(null);

  const capabilities = useQuery({
    queryKey: ["data-capabilities"],
    queryFn: () => backend!.getDataCapabilities(),
    enabled: backendReady,
    retry: false,
  });

  const unowned = useQuery({
    queryKey: ["unowned-disposition"],
    queryFn: async () => ({
      events: await queue.countUnowned(),
      draft: isTauriRuntime()
        ? (await invoke<unknown>("focus_get_draft", { owner: "unowned" })) !== null
        : (typeof localStorage !== "undefined" && localStorage.getItem(focusDraftKey("unowned")) !== null),
    }),
  });

  const poll = useOperationPoll({
    operationId: polledOperationId,
    fetchOperation: (id) => backend!.getDataOperation(id),
  });

  function buildTarget(): DeleteTarget | null {
    const ids = idsText.split(/[\s,]+/).map((id) => id.trim()).filter(Boolean);
    if (targetKind === "account") return { kind: "account" };
    if (ids.length === 0) {
      setNotice("请先填写要删除的对象 ID。");
      return null;
    }
    if (targetKind === "source") return { kind: "source", source_kind: sourceKind as "event" | "file" | "chat_session" | "chat_message", ids };
    return { kind: "memory", ids, include_history: true };
  }

  function cleanupDeps(): LocalCleanupDeps {
    const storage = typeof localStorage === "undefined" ? null : localStorage;
    return {
      clearQueueData: (ownerKey) => queue.clearOwnerData(ownerKey, true),
      countQueueData: (ownerKey) => queue.countOwnerData(ownerKey),
      clearDraft: async (ownerKey) => {
        if (isTauriRuntime()) await invoke("focus_set_draft", { draft: null, owner: ownerKey });
        else await new LocalFocusDraftStore({ storage, resolveOwner: () => ownerKey }).write(null);
      },
      draftPresent: async (ownerKey) => {
        if (isTauriRuntime()) return (await invoke<unknown>("focus_get_draft", { owner: ownerKey })) !== null;
        return storage?.getItem(focusDraftKey(ownerKey)) !== null;
      },
      logoutSession: async () => {
        await backendSession?.logout();
      },
      tokenPresent: async () => {
        if (!isTauriRuntime()) return null;
        return (await invoke<string | null>("backend_token_get")) !== null;
      },
      storage,
    };
  }

  const previewMutation = useMutation({
    mutationFn: async () => {
      const target = buildTarget();
      if (!target) throw new Error("NO_TARGET");
      return await backend!.createDataPreview(target);
    },
    onSuccess: (result) => {
      setPreview(result);
      setAccountStep(0);
      setAccountAcknowledged(false);
      setNotice(null);
    },
    onError: (error) => setNotice(errorCopy(error)),
  });

  /** 确认键锁定同一 client_request_id（B 稿 §2）：202 丢失重发同 ID 幂等
   *  收敛，不因重试点击生成新删除。 */
  const confirmSourceMutation = useMutation({
    mutationFn: async () => {
      if (!preview) throw new Error("先查看删除范围");
      const client_request_id = `del-${newRequestId()}`.slice(0, 128);
      const operation = await backend!.confirmDataDeletion({
        preview_id: preview.id,
        preview_digest: preview.preview_digest,
        client_request_id,
        confirmed: true,
      });
      return { operation, client_request_id };
    },
    onSuccess: ({ operation }) => {
      setPreview(null);
      setPolledOperationId(operation.id);
      setNotice("删除已提交。");
    },
    onError: (error) => setNotice(errorCopy(error)),
  });

  const confirmAccountMutation = useMutation({
    mutationFn: async () => {
      if (!preview) throw new Error("先查看删除范围");
      const ownerKey = resolveOwner();
      if (!ownerKey) throw new Error("账号身份尚未落定，无法关联本机数据");
      const client_request_id = `del-${newRequestId()}`.slice(0, 128);
      const confirm_body = {
        preview_id: preview.id,
        preview_digest: preview.preview_digest,
        client_request_id,
        confirmed: true,
      } as const;
      const operation = await backend!.confirmDataDeletion({ ...confirm_body });
      return { operation, ownerKey, confirm_body };
    },
    onSuccess: async ({ operation, ownerKey, confirm_body }) => {
      // 回执留存（recover 三件套 = 完整确认请求体；capability 只进槽位）
      if (operation.receipt_capability && operation.receipt_id) {
        await receipts.write(ownerKey, {
          capability: operation.receipt_capability,
          receipt_id: operation.receipt_id,
          client_request_id: confirm_body.client_request_id,
          confirm_body: { ...confirm_body },
          issued_at: new Date().toISOString(),
          expires_at: new Date(Date.now() + 90 * 24 * 60 * 60 * 1000).toISOString(),
        });
      }
      setPreview(null);
      setAccountStep(0);
      setCleanupOwnerKey(ownerKey);
      // B 稿 §3 顺序：登出（业务 token 槽；回执槽不动）→ 本机清理矩阵。
      // queryClient 整池清空（账号作用域缓存，无用户维度键）。
      const record = await runLocalCleanup(cleanupDeps(), ownerKey);
      setCleanupRecord(record);
      await queryClient.invalidateQueries();
      queryClient.clear();
      setNotice("账号删除已确认，本机清理已执行——状态见下方。");
    },
    onError: (error) => setNotice(errorCopy(error)),
  });

  const exportMutation = useMutation({
    mutationFn: async () => {
      const client_request_id = `exp-${newRequestId()}`.slice(0, 128);
      const operation = await backend!.createDataExport({ client_request_id, include_files: exportIncludeFiles });
      return { operation, client_request_id };
    },
    onSuccess: ({ operation }) => {
      setPolledOperationId(operation.id);
      setNotice("导出已提交。");
    },
    onError: (error) => setNotice(errorCopy(error)),
  });

  const retryMutation = useMutation({
    mutationFn: async () => {
      const operation = poll.operation;
      if (!operation) throw new Error("尚无可重试的操作");
      return await backend!.retryDataOperation(operation.id, operation.version);
    },
    onSuccess: () => void poll.refresh(),
    onError: (error) => setNotice(errorCopy(error)),
  });

  async function downloadExport(operation: DataOperationOut) {
    try {
      const response = await backend!.downloadDataExport(operation.id);
      if (!response.ok) throw new Error(`下载失败（HTTP ${response.status}）——导出包可能已到期或不可用`);
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `agenthu-export-${operation.id}.zip`;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : String(error));
    }
  }

  async function disposeUnowned(adopt: boolean) {
    try {
      if (adopt) {
        const ownerKey = resolveOwner();
        if (!ownerKey) throw new Error("需要先登录 Backend 账号，才能把无主数据归入当前账号");
        const events = await queue.adoptUnowned(ownerKey);
        const drafts = await focusDraft.adoptUnownedDraft(ownerKey);
        setNotice(`已归入当前账号：事件 ${events} 条，草稿 ${drafts} 条。`);
      } else {
        const events = await queue.discardUnowned();
        const drafts = await focusDraft.discardUnownedDraft();
        setNotice(`已丢弃无主数据：事件 ${events} 条，草稿 ${drafts} 条。`);
      }
      await queryClient.invalidateQueries({ queryKey: ["unowned-disposition"] });
      await queryClient.invalidateQueries({ queryKey: ["queue-pending"] });
    } catch (error) {
      setNotice(error instanceof Error ? error.message : String(error));
    }
  }

  async function rerunCleanup() {
    const ownerKey = cleanupOwnerKey ?? resolveOwner();
    if (!ownerKey) {
      setNotice("尚未关联本机清理（登录后进行一次删除，或先完成账号删除）。");
      return;
    }
    const record = await retryLocalCleanup(cleanupDeps(), ownerKey);
    setCleanupRecord(record);
  }

  const shownCleanup = cleanupRecord
    ?? (cleanupOwnerKey ?? resolveOwner()
      ? readCleanupRecord(typeof localStorage === "undefined" ? null : localStorage, (cleanupOwnerKey ?? resolveOwner()) as string)
      : null);
  const sourceKinds = capabilities.data?.supported_source_kinds ?? ["event", "file", "chat_session", "chat_message"];
  const operation = poll.operation;

  return <section className="workspace-section" aria-label="数据与隐私">
    <div className="section-heading"><h2>数据与隐私</h2><span className="section-meta">导出 · 删除 · 回执 · 本机清理</span></div>
    {notice && <p className="notice" role="status">{notice}</p>}

    <div className="data-controls-card">
      <h3>服务能力</h3>
      {!backendReady && <p className="empty-state">登录 Backend 后可管理数据导出与删除。</p>}
      {backendReady && capabilities.isPending && <p className="empty-state">正在读取服务能力…</p>}
      {backendReady && capabilities.isError && <p className="empty-state">此服务尚未支持完整导出/删除。</p>}
      {capabilities.data && <p className="section-meta">
        契约版本 {capabilities.data.schema_version} · 数据图谱 {capabilities.data.graph_version} ·
        导出{capabilities.data.export_enabled ? "可用" : "不可用"} · 删除{capabilities.data.deletion_enabled ? "可用" : "不可用"}
      </p>}
    </div>

    <div className="data-controls-card">
      <h3>导出我的数据</h3>
      <label className="data-check"><input type="checkbox" aria-label="包含文件对象" checked={exportIncludeFiles} onChange={(event) => setExportIncludeFiles(event.target.checked)} />包含文件对象</label>
      <div className="section-actions">
        <button className="primary-button" disabled={!backendReady || !capabilities.data?.export_enabled || exportMutation.isPending || !!polledOperationId} onClick={() => exportMutation.mutate()}>导出我的数据</button>
        {operation?.kind === "EXPORT" && <button className="ghost-button" disabled={operation.status !== "READY"} onClick={() => void downloadExport(operation)}>下载导出包</button>}
      </div>
      <p className="section-meta">本地下载副本由你本人保管；清客户端缓存不会擦除你保存的导出文件。Backend 导出不含离线未同步草稿。</p>
    </div>

    <div className="data-controls-card">
      <h3>删除我的数据</h3>
      <div className="section-actions">
        <select aria-label="删除范围" value={targetKind} onChange={(event) => { setTargetKind(event.target.value as TargetKind); setPreview(null); setAccountStep(0); }}>
          <option value="source">按来源删除</option>
          <option value="memory">永久忘记记忆（含历史版本）</option>
          <option value="account">删除整个账号</option>
        </select>
        {targetKind === "source" && <select aria-label="来源类型" value={sourceKind} onChange={(event) => setSourceKind(event.target.value)}>
          {sourceKinds.map((kind) => <option key={kind} value={kind}>{kind}</option>)}
        </select>}
        {targetKind !== "account" && <textarea aria-label="对象 ID" rows={2} placeholder="对象 ID（每行或逗号分隔）" value={idsText} onChange={(event) => setIdsText(event.target.value)} />}
      </div>
      {targetKind === "memory" && <p className="section-meta">永久忘记将删除整条记忆链（含历史版本）。「拒绝再派生」是另一个动作，不会擦除既有内容。</p>}
      <div className="section-actions">
        <button className="ghost-button" disabled={!backendReady || previewMutation.isPending} onClick={() => previewMutation.mutate()}>查看删除范围</button>
      </div>

      {preview && <div className="data-preview">
        <p>{effectSummaryLine(preview.effects)}</p>
        <table className="data-effect-table"><caption>分内容族</caption><thead><tr><th>内容族</th><th>删除</th><th>清除</th><th>重算</th><th>保留</th></tr></thead><tbody>
          {preview.effects.map((effect) => <tr key={effect.resource_type}><td>{effect.resource_type}</td><td>{effect.delete_count}</td><td>{effect.redact_count}</td><td>{effect.recompute_count}</td><td>{effect.retain_count}</td></tr>)}
        </tbody></table>
        {preview.limitations.length > 0 && <ul className="data-limitations">{preview.limitations.map((item) => <li key={item}>{item}</li>)}</ul>}
        <p className="section-meta">预览有时效；数据变化后需重新查看范围。</p>

        {targetKind === "account" && accountStep === 0 && <>
          <p>即将删除 <strong>{backendState.email ?? "当前登录账号"}</strong> 的全部数据。建议先导出（不会自动代你导出）。</p>
          <div className="section-actions"><button className="danger-button" onClick={() => setAccountStep(1)}>继续</button></div>
        </>}
        {targetKind === "account" && accountStep === 1 && <>
          <label className="data-check"><input type="checkbox" aria-label="我理解此操作不可恢复" checked={accountAcknowledged} onChange={(event) => setAccountAcknowledged(event.target.checked)} />我理解此操作不可恢复</label>
          <div className="section-actions">
            <button className="danger-button" disabled={!accountAcknowledged || confirmAccountMutation.isPending} onClick={() => confirmAccountMutation.mutate()}>永久删除账号</button>
            <button className="ghost-button" onClick={() => setAccountStep(0)}>返回</button>
          </div>
        </>}
        {targetKind !== "account" && <div className="section-actions">
          <button className="danger-button" disabled={confirmSourceMutation.isPending} onClick={() => confirmSourceMutation.mutate()}>确认删除</button>
        </div>}
      </div>}

      {operation && operation.kind === "DELETION" && <div className="data-operation" role="status">
        <p>{operationStatusLine(operation)}</p>
        {(operation.status === "QUEUED" || operation.status === "RUNNING" || operation.status === "RETRY_WAIT") && <p className="section-meta">{progressLine(operation)}</p>}
        {poll.capped && <p className="section-meta">处理时间较长，已暂停自动查询——可手动刷新。</p>}
        {poll.error && <p className="error-text">{poll.error}</p>}
        <div className="section-actions">
          <button className="ghost-button" onClick={() => void poll.refresh()}>手动刷新</button>
          {operation.status === "FAILED" && <button className="ghost-button" disabled={retryMutation.isPending} onClick={() => retryMutation.mutate()}>重试同一删除</button>}
        </div>
        {operation.status === "COMPLETED" && <p className="section-meta">服务端数据已清除；本机与其他设备仍可能有残留副本（其他设备状态未知）。被删来源的本地待同步事件会在下次同步时由服务端抑制自动出队。</p>}
      </div>}
      {operation && operation.kind === "EXPORT" && <div className="data-operation" role="status">
        <p>{operationStatusLine(operation)}</p>
        {poll.capped && <p className="section-meta">已暂停自动查询——可手动刷新。</p>}
        <div className="section-actions">
          <button className="ghost-button" onClick={() => void poll.refresh()}>手动刷新</button>
          <button className="ghost-button" disabled={operation.status !== "READY"} onClick={() => void downloadExport(operation)}>下载导出包</button>
        </div>
      </div>}
    </div>

    <div className="data-controls-card">
      <h3>无主本机数据</h3>
      <p className="section-meta">历史遗留的本机事件/草稿未归属任何账号；不会自动并入当前账号或上传。</p>
      <p>{(unowned.data?.events ?? 0) + (unowned.data?.draft ? 1 : 0) > 0
        ? `待处置：事件 ${unowned.data?.events ?? 0} 条${unowned.data?.draft ? "，Focus 草稿 1 份" : ""}。`
        : "没有待处置的无主数据。"}</p>
      <div className="section-actions">
        {/* #69 advisory #4：adopt 需在席会话（live ownerKey）；点击时取值，
            会话切变由命令层 owner 校验兜底 */}
        <button className="ghost-button" disabled={!backendReady || (unowned.data?.events ?? 0) + (unowned.data?.draft ? 1 : 0) === 0} onClick={() => void disposeUnowned(true)}>归入当前账号</button>
        <button className="ghost-button" disabled={(unowned.data?.events ?? 0) + (unowned.data?.draft ? 1 : 0) === 0} onClick={() => void disposeUnowned(false)}>丢弃</button>
      </div>
    </div>

    <div className="data-controls-card">
      <h3>本机清理</h3>
      {shownCleanup
        ? <>
            <p>{cleanupStateText(shownCleanup.state)}（更新于 {shownCleanup.updated_at ? new Date(shownCleanup.updated_at).toLocaleString() : "—"}）</p>
            {shownCleanup.error && <p className="error-text">{shownCleanup.error}</p>}
            {shownCleanup.checks && <ul className="data-checks">
              {shownCleanup.checks.map((check) => <li key={check.name} className={check.ok ? "check-ok" : "check-fail"}>{check.name}：{check.detail}{check.ok ? "" : "（未通过）"}</li>)}
            </ul>}
            {shownCleanup.state === "verified" && <p className="section-meta">服务端完成 ≠ 本机完成；其他设备状态未知（unknown/pending），没有设备响应时不得视为已清理。</p>}
            <div className="section-actions">
              <button className="ghost-button" onClick={() => void rerunCleanup()}>{shownCleanup.state === "failed" ? "重试本机清理" : "重新核账"}</button>
            </div>
          </>
        : <p className="empty-state">完成一次账号删除后，这里会展示本机清理状态与可复跑的核验清单。</p>}
      <p className="section-meta">校园会话独立于 Backend 账号；需要断开校园登录请使用顶栏「退出校园账号」。</p>
    </div>
  </section>;
}
