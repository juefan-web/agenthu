import type { Task } from "@agenthu/contracts";
import { errorText } from "../../lib/errors";

/** 派生任务可辨识（M1-1 B 侧验收）：manual / 缺省不标，其余来源标徽标；
 * 未知来源（未来 connector）直接显示原始 source 字符串。 */
const SOURCE_LABELS: Record<string, string> = { onethu: "校园采集" };

function sourceLabel(task: Task): string | null {
  if (!task.source || task.source === "manual") return null;
  return SOURCE_LABELS[task.source] ?? task.source;
}

export function TaskList({ tasks, loading, error, configured }: { tasks: Task[]; loading: boolean; error: unknown; configured: boolean }) {
  if (!configured) return <p className="empty-state">配置 Backend 地址后显示任务。</p>;
  if (loading) return <p className="empty-state">正在读取任务…</p>;
  if (error) return <p className="error-text">任务读取失败：{errorText(error)}</p>;
  if (tasks.length === 0) return <p className="empty-state">暂无任务。</p>;
  return <div className="task-list">{tasks.map((task) => {
    const badge = sourceLabel(task);
    return <div className="task-row" key={task.id}>
      <div>
        <div className="task-title-line"><strong>{task.title}</strong>{badge && <span className="source-badge">{badge}</span>}</div>
        <span>{task.due_at ? `截止 ${new Date(task.due_at).toLocaleString()}` : "无截止时间"}</span>
      </div>
      <span className="status-label">{task.status}</span>
    </div>;
  })}</div>;
}
