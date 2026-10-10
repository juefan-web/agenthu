import { useCallback, useEffect, useState } from "react";
import type { DataReceiptOut } from "@agenthu/contracts";
import { isTauriRuntime } from "../../adapters/campus/tauriTransport";
import { fetchReceiptWithCapability } from "../../backend/data";
import { backendFetch } from "../../backend/transport";
import type { ReceiptSlotSummary, ReceiptStore } from "../../backend/receiptStore";

/** 回执独立最小视图（B 稿 §1/§3）：业务 401 退出后的读取面——登录屏
 *  入口，不经 AppServices 业务会话、不进 React Query；capability 作
 *  Bearer 直连，且从不进 URL/日志/DOM 文本。无效能力统一「回执不可
 *  用」（不区分不存在/过期/身份不符）。手动刷新（GET only）——回执
 *  视图的轮询节奏 B 稿未冻结，本片不擅自定参（任务书判断记录）。
 *  打包态流量走 backend_request 受控转发（生产 CSP 无直连出口，默认
 *  fetch 会被拦——外审 #10）；浏览器开发态沿用原生 fetch。 */
export function ReceiptViewer({ baseUrl, store }: { baseUrl: string; store: ReceiptStore }) {
  const [summaries, setSummaries] = useState<ReceiptSlotSummary[]>([]);
  const [selected, setSelected] = useState<DataReceiptOut | null>(null);
  const [selectedOwner, setSelectedOwner] = useState<string | null>(null);
  const [unavailable, setUnavailable] = useState(false);
  const [loading, setLoading] = useState(false);

  const reload = useCallback(async () => {
    setSummaries(await store.list());
  }, [store]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const open = useCallback(
    async (summary: ReceiptSlotSummary) => {
      setLoading(true);
      setUnavailable(false);
      setSelected(null);
      setSelectedOwner(summary.owner);
      try {
        // capability 只在内存中转：slot → 直连请求，不渲染、不外发；
        // Tauri 下经 IPC 受控转发，不走 WebView 直连 fetch
        const stored = await store.read(summary.owner);
        const receipt = stored
          ? await fetchReceiptWithCapability(baseUrl, summary.receipt_id, stored.capability, isTauriRuntime() ? backendFetch : undefined)
          : null;
        if (!receipt) {
          setUnavailable(true);
        } else {
          setSelected(receipt);
        }
      } catch {
        setUnavailable(true);
      } finally {
        setLoading(false);
      }
    },
    [baseUrl, store],
  );

  return <section className="workspace-section" aria-label="删除回执">
    <div className="section-heading"><h2>删除回执</h2><span className="section-meta">独立读取 · 不依赖登录</span></div>
    {summaries.length === 0 && <p className="empty-state">本机没有留存的删除回执。</p>}
    {summaries.length > 0 && <ul className="data-effect-list">
      {summaries.map((summary) => <li key={summary.owner} className="data-effect-row">
        <span>删除于 {new Date(summary.issued_at).toLocaleString()}</span>
        <span className="section-meta">{selectedOwner === summary.owner && selected ? "查看中" : `保留至 ${new Date(summary.expires_at).toLocaleDateString()}`}</span>
        <button className="ghost-button" disabled={loading} onClick={() => void open(summary)}>查看</button>
      </li>)}
    </ul>}
    {loading && <p className="empty-state">正在读取回执…</p>}
    {unavailable && <p className="error-text">回执不可用</p>}
    {selected && <div className="data-receipt">
      <p>{selected.outstanding_count > 0 ? `清理仍在进行（剩余 ${selected.outstanding_count} 项）` : "服务端清理已完成"}</p>
      {selected.completed_at && <p className="section-meta">完成于 {new Date(selected.completed_at as string).toLocaleString()}</p>}
      {selected.backup_expires_at && <p className="section-meta">备份最晚失效：{new Date(selected.backup_expires_at).toLocaleString()}</p>}
      {selected.provider_limitations.length > 0 && <ul className="data-limitations">{selected.provider_limitations.map((item) => <li key={item}>{item}</li>)}</ul>}
      {selected.local_cleanup_required && <p className="error-text">本机仍需清理（见数据与隐私页）</p>}
      <table className="data-effect-table"><caption>清理账目</caption><thead><tr><th>内容族</th><th>删除</th><th>清除</th><th>重算</th></tr></thead><tbody>
        {selected.effects.map((effect) => <tr key={effect.resource_type}><td>{effect.resource_type}</td><td>{effect.delete_count}</td><td>{effect.redact_count}</td><td>{effect.recompute_count}</td></tr>)}
      </tbody></table>
    </div>}
    <button className="ghost-button" onClick={() => void reload()}>刷新列表</button>
  </section>;
}
