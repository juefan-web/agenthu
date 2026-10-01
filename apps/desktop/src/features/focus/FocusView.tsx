import { useEffect, useState } from "react";
import type { FocusSession, Task } from "@agenthu/contracts";
import { errorText } from "../../lib/errors";
import { useServices } from "../../app/services";

export function FocusView({ tasks }: { tasks: Task[] }) {
  const { backend, focusDraft } = useServices();
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
