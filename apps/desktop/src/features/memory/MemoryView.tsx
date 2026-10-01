import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { MemoryItem } from "../../backend/memory";
import { errorText } from "../../lib/errors";
import { useServices } from "../../app/services";

/** Memory 页（m2-breakdown B-3）：「可修正」验收句的落点。三动作对应
 *  D-032 §8 裁定的三语义端点（#23）：确认 = confirm（幂等，含 un-reject）、
 *  修正 = correct（新版本走 superseded-by 版本链）、拒绝 = reject（live
 *  占位阻断再派生）。主列表只显示 live 行（supersedes_id IS NULL）。 */

const STATUS_LABELS: Record<MemoryItem["correction_status"], string> = {
  UNREVIEWED: "未确认",
  CONFIRMED: "已确认",
  CORRECTED: "已修正（历史版本）",
  REJECTED: "已拒绝",
};
const KIND_LABELS: Record<string, string> = {
  episode: "经历",
  fact: "事实",
  habit: "习惯",
  preference: "偏好",
  model: "个人模型",
};

function evidenceText(memory: MemoryItem): string {
  const events = memory.evidence.filter((item) => item["type"] === "event").length;
  const documents = memory.evidence.filter((item) => item["type"] === "document").length;
  const parts: string[] = [];
  if (events > 0) parts.push(`事件 ${events}`);
  if (documents > 0) parts.push(`文档 ${documents}`);
  return parts.length > 0 ? `证据：${parts.join(" · ")}` : "暂无证据";
}

function MemoryRow({ memory }: { memory: MemoryItem }) {
  const { backend } = useServices();
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [content, setContent] = useState(memory.content);
  const [confidence, setConfidence] = useState(String(Math.round(memory.confidence * 100)));
  const invalidate = () => void queryClient.invalidateQueries({ queryKey: ["memories"] });

  const confirm = useMutation({ mutationFn: () => backend!.confirmMemory(memory.id), onSuccess: invalidate });
  const reject = useMutation({ mutationFn: () => backend!.rejectMemory(memory.id), onSuccess: invalidate });
  const correct = useMutation({
    mutationFn: () => backend!.correctMemory(memory.id, {
      content,
      confidence: Number.isFinite(Number(confidence)) ? Math.min(1, Math.max(0, Number(confidence) / 100)) : undefined,
    }),
    onSuccess: () => { setEditing(false); invalidate(); },
  });

  return <div className="memory-row">
    <div>
      <div className="task-title-line"><strong>{memory.content}</strong><span className={`memory-status ${memory.correction_status.toLowerCase()}`}>{STATUS_LABELS[memory.correction_status]}</span></div>
      <span>
        L{memory.level}{memory.kind ? ` · ${KIND_LABELS[memory.kind] ?? memory.kind}` : ""} · {memory.domain} · 置信 {Math.round(memory.confidence * 100)}% · {evidenceText(memory)}
      </span>
      {memory.subject_key && <span>聚合键 {memory.subject_key}</span>}
    </div>
    {editing
      ? <div className="memory-edit">
          <textarea value={content} onChange={(event) => setContent(event.target.value)} rows={3} />
          <label>置信度（%）<input type="number" min={0} max={100} value={confidence} onChange={(event) => setConfidence(event.target.value)} /></label>
          <div className="section-actions">
            <button className="primary-button" disabled={correct.isPending || !content.trim()} onClick={() => correct.mutate()}>保存修正（生成新版本）</button>
            <button className="ghost-button" disabled={correct.isPending} onClick={() => setEditing(false)}>取消</button>
          </div>
          {correct.error && <p className="error-text">{errorText(correct.error)}</p>}
        </div>
      : memory.supersedes_id === null && <div className="memory-actions">
          {memory.correction_status !== "CONFIRMED" && <button className="ghost-button" disabled={confirm.isPending} onClick={() => confirm.mutate()}>确认</button>}
          <button className="ghost-button" onClick={() => { setContent(memory.content); setConfidence(String(Math.round(memory.confidence * 100))); setEditing(true); }}>修正</button>
          {memory.correction_status !== "REJECTED"
            ? <button className="ghost-button" disabled={reject.isPending} onClick={() => { if (window.confirm("拒绝这条记忆？聚合将不再生成同类内容（可再确认恢复）。")) reject.mutate(); }}>拒绝</button>
            : null}
        </div>}
    {(confirm.error ?? reject.error) && <p className="error-text">{errorText(confirm.error ?? reject.error)}</p>}
  </div>;
}

export function MemoryView() {
  const { backend } = useServices();
  const [showHistory, setShowHistory] = useState(false);
  const memories = useQuery({ queryKey: ["memories"], queryFn: () => backend!.listMemories(), enabled: !!backend });
  if (!backend) return <section className="workspace-section"><p className="empty-state">配置 Backend 地址后可以查看记忆。</p></section>;
  if (memories.isPending) return <section className="workspace-section"><p className="empty-state">正在读取记忆…</p></section>;
  if (memories.error) return <section className="workspace-section"><p className="error-text">记忆读取失败：{errorText(memories.error)}</p></section>;

  const all = memories.data ?? [];
  const live = all.filter((memory) => memory.supersedes_id === null);
  const history = all.filter((memory) => memory.supersedes_id !== null);
  return <section className="workspace-section memory-workspace">
    <div className="section-heading"><h2>学习记忆</h2><span className="section-meta">live {live.length} 条{history.length > 0 ? ` · 历史 ${history.length} 条` : ""}</span></div>
    {live.length === 0 ? <p className="empty-state">还没有记忆。完成专注并触发学习后，这里会出现带证据的记忆条目。</p> : <div className="memory-list">{live.map((memory) => <MemoryRow key={memory.id} memory={memory} />)}</div>}
    {history.length > 0 && <>
      <button className="ghost-button" onClick={() => setShowHistory(!showHistory)}>{showHistory ? "收起历史版本" : `展开历史版本（${history.length}）`}</button>
      {showHistory && <div className="memory-list memory-history">{history.map((memory) => <MemoryRow key={memory.id} memory={memory} />)}</div>}
    </>}
  </section>;
}
