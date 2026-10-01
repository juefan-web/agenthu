import { useMutation } from "@tanstack/react-query";
import { errorText } from "../../lib/errors";
import { useServices } from "../../app/services";

type TodayPlan = Awaited<ReturnType<import("../../backend/client").BackendClient["getTodayPlan"]>>;

/** 今日计划列表与确认。M2 的 basis（「为什么」面板）在此扩展。 */
export function PlanView({ plan, loading, error, onChanged }: { plan: TodayPlan | undefined; loading: boolean; error: unknown; onChanged: () => void }) {
  const { backend } = useServices();
  const confirm = useMutation({ mutationFn: () => backend!.confirmPlan(plan!.id), onSuccess: onChanged });
  if (!backend) return <p className="empty-state">配置 Backend 地址后显示今日计划。</p>;
  if (loading) return <p className="empty-state">正在读取计划…</p>;
  if (error) return <p className="error-text">计划读取失败：{errorText(error)}</p>;
  if (!plan || plan.items.length === 0) return <p className="empty-state">今天还没有计划。</p>;
  return <><div className="plan-list">{plan.items.map((item) => <div className="plan-row" key={`${item.task_id}:${item.start_at}`}><time>{new Date(item.start_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</time><div><strong>{item.title}</strong><span>{item.reason}</span></div></div>)}</div>{plan.confirmation_required && plan.status === "draft" && <button className="primary-button" disabled={confirm.isPending} onClick={() => confirm.mutate()}>确认计划</button>}{confirm.error && <p className="error-text">{errorText(confirm.error)}</p>}</>;
}
