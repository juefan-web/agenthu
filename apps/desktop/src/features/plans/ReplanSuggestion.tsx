import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { Plan } from "@agenthu/contracts";
import { errorText } from "../../lib/errors";
import { BasisPanel } from "./BasisPanel";
import { useServices } from "../../app/services";

/** 一条重排建议 = DRAFT + replaces_plan_id 非空（D-031 §2，Level 1 语义）。
 *  接受走既有 confirm（服务端同事务把旧 CONFIRMED 置 SUPERSEDED——接受即
 *  取代）；忽略走既有 cancel。绝不修改被替代计划。 */

interface PlanItemDiff {
  added: Plan["items"];
  droppedTitles: string[];
  moved: Array<{ title: string; from: string; to: string }>;
}

function timeOf(item: Plan["items"][number]): string {
  return new Date(item.start_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export function diffPlans(current: Plan | undefined, suggestion: Plan): PlanItemDiff {
  const currentItems = current?.items ?? [];
  const byTaskId = new Map(currentItems.map((item) => [item.task_id, item]));
  const suggestionIds = new Set(suggestion.items.map((item) => item.task_id));
  const added = suggestion.items.filter((item) => !byTaskId.has(item.task_id));
  const droppedTitles = currentItems.filter((item) => !suggestionIds.has(item.task_id)).map((item) => item.title);
  const moved = suggestion.items.flatMap((item) => {
    const before = byTaskId.get(item.task_id);
    return before && before.start_at !== item.start_at
      ? [{ title: item.title, from: timeOf(before), to: timeOf(item) }]
      : [];
  });
  return { added, droppedTitles, moved };
}

export function ReplanSuggestion({ currentPlan }: { currentPlan: Plan | undefined }) {
  const { backend } = useServices();
  const queryClient = useQueryClient();
  const suggestions = useQuery({
    queryKey: ["plan-suggestions"],
    queryFn: () => backend!.listPlans("draft"),
    enabled: !!backend,
    refetchInterval: 60_000,
  });
  const latest = (suggestions.data ?? [])
    .filter((plan) => plan.replaces_plan_id != null)
    // 绝对时刻比较而非 localeCompare——+08:00 与 Z 混合偏移的 ISO 串字典序不可靠（#22 审阅备注）
    .sort((a, b) => Date.parse(b.generated_at) - Date.parse(a.generated_at))[0];

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ["plan"] });
    void queryClient.invalidateQueries({ queryKey: ["plan-suggestions"] });
    void queryClient.invalidateQueries({ queryKey: ["current-state"] });
  };
  const accept = useMutation({ mutationFn: () => backend!.confirmPlan(latest!.id), onSuccess: invalidate });
  const dismiss = useMutation({ mutationFn: () => backend!.cancelPlan(latest!.id), onSuccess: invalidate });

  if (!backend || !latest) return null;
  const diff = diffPlans(currentPlan, latest);
  return <section className="replan-suggestion" role="status">
    <div className="section-heading"><h2>重排建议</h2><span className="section-meta">Level 1 · 不会改动当前计划，接受后生效</span></div>
    <p className="replan-reason">{latest.replan_reason}</p>
    {/* 契约 §4：重排建议与计划/确认卡/Chat 复用同一 basis 渲染——plan 级
        basis 的 agent_decision 子键（#59 起 generate_plan 写入）由 BasisPanel
        检出后转交共享 DecisionBasisView；legacy 弱类型键照旧透出。 */}
    <BasisPanel basis={latest.basis} />
    <ul className="replan-diff">
      {diff.moved.map((item) => <li key={`m:${item.title}`}>调整 {item.title}：{item.from} → {item.to}</li>)}
      {diff.added.map((item) => <li key={`a:${item.task_id}`}>新增 {item.title}（{timeOf(item)} 起）</li>)}
      {diff.droppedTitles.map((title) => <li key={`d:${title}`}>移出 {title}</li>)}
      {diff.moved.length + diff.added.length + diff.droppedTitles.length === 0 && <li>安排无变化</li>}
    </ul>
    <div className="section-actions">
      <button className="primary-button" disabled={accept.isPending || dismiss.isPending} onClick={() => accept.mutate()}>接受建议</button>
      <button className="ghost-button" disabled={accept.isPending || dismiss.isPending} onClick={() => dismiss.mutate()}>忽略</button>
    </div>
    {(accept.error ?? dismiss.error) && <p className="error-text" role="alert">{errorText(accept.error ?? dismiss.error)}</p>}
  </section>;
}
