/** 「为什么」面板（D-031 §1）：`reason` 是人话渲染层，`basis` 是结构化依据。
 *  契约弱类型（z.record(z.unknown())），已知字段按语义渲染，未知字段原样
 *  透出——服务端形状演进不需要客户端同步发版。 */

const ESTIMATE_SOURCE_LABELS: Record<string, string> = {
  default: "默认值（60 分钟）",
  user: "你手动设置的估时",
  "learned:course": "同课程历史实际用时（中位数）",
  "learned:ratio": "个人校准比推算",
};

function asNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function asString(value: unknown): string | null {
  return typeof value === "string" && value ? value : null;
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function basisRows(basis: Record<string, unknown>): Array<{ label: string; value: string; atRisk?: boolean }> {
  const rows: Array<{ label: string; value: string; atRisk?: boolean }> = [];
  const deadline = asString(basis["deadline"]);
  if (deadline) rows.push({ label: "截止时间", value: new Date(deadline).toLocaleString() });
  const slack = asNumber(basis["slack_minutes"]);
  if (slack !== null) {
    rows.push(slack < 0
      ? { label: "剩余缓冲", value: `⚠ ${slack} 分钟（时间已不足）`, atRisk: true }
      : { label: "剩余缓冲", value: `${slack} 分钟` });
  }
  const estimate = asNumber(basis["estimate_minutes"]);
  if (estimate !== null) rows.push({ label: "预计用时", value: `${estimate} 分钟` });
  const estimateSource = asString(basis["estimate_source"]);
  if (estimateSource) {
    const sampleCount = asNumber(basis["sample_count"]);
    const label = ESTIMATE_SOURCE_LABELS[estimateSource] ?? estimateSource;
    // 服务端 reason 已带样本数（plan_reason）；basis 面板对齐呈现（planner
    // 写入 sample_count，缺失不显示——user/default 来源无样本概念）
    const suffix = estimateSource.startsWith("learned:") && sampleCount !== null ? `，近 ${sampleCount} 次` : "";
    rows.push({ label: "估时来源", value: `${label}${suffix}` });
  }
  const slotReason = asString(basis["slot_reason"]);
  if (slotReason) rows.push({ label: "时段理由", value: slotReason });
  const goalId = asString(basis["goal_id"]);
  if (goalId) rows.push({ label: "关联目标", value: goalId });
  if (basis["at_risk"] === true) rows.push({ label: "风险", value: "⚠ 截止临近，缓冲不足", atRisk: true });
  const score = basis["score"];
  if (score && typeof score === "object" && !Array.isArray(score)) {
    for (const [key, value] of Object.entries(score as Record<string, unknown>)) {
      rows.push({ label: `打分 · ${key}`, value: formatValue(value) });
    }
  }
  const known = new Set(["deadline", "slack_minutes", "estimate_minutes", "estimate_source", "sample_count", "slot_reason", "goal_id", "at_risk", "score"]);
  for (const [key, value] of Object.entries(basis)) {
    if (!known.has(key) && value !== null && value !== undefined) rows.push({ label: key, value: formatValue(value) });
  }
  return rows;
}

export function BasisPanel({ basis }: { basis: Record<string, unknown> | undefined }) {
  const rows = basis ? basisRows(basis) : [];
  if (rows.length === 0) return null;
  return <details className="basis-panel">
    <summary>为什么</summary>
    <dl>{rows.map((row) => <div key={row.label}><dt>{row.label}</dt><dd className={row.atRisk ? "basis-at-risk" : undefined}>{row.value}</dd></div>)}</dl>
  </details>;
}
