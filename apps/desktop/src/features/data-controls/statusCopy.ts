import type { DataEffect, DataOperationOut } from "@agenthu/contracts";

/** B 稿 §2 状态文案表（冻结）：只按服务端字段措辞，不自推断级联、
 *  不虚构百分比；preview_digest 是不透明回显——本模块与视图都不得
 *  渲染或重算它。 */

export const TERMINAL_OPERATION_STATUSES: ReadonlySet<string> = new Set([
  "READY",
  "COMPLETED",
  "EXPIRED",
  "FAILED",
]);

export function isTerminalStatus(status: string): boolean {
  return TERMINAL_OPERATION_STATUSES.has(status);
}

function formatTime(iso: string | null): string {
  if (!iso) return "稍后";
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString();
}

/** preview 行：只加总服务端 effects 计数，「独立编辑内容按清单保留」。 */
export function effectSummaryLine(effects: DataEffect[]): string {
  const sum = (pick: (effect: DataEffect) => number) => effects.reduce((total, effect) => total + pick(effect), 0);
  return `将删除 ${sum((e) => e.delete_count)} 项、清除 ${sum((e) => e.redact_count)} 项派生内容、重算 ${sum((e) => e.recompute_count)} 项；独立编辑内容按清单保留`;
}

/** 进度行：只用 processed/total/outstanding（QUEUED/RUNNING/RETRY_WAIT）。 */
export function progressLine(operation: DataOperationOut): string {
  const { processed, total, outstanding_count: outstanding } = operation.progress;
  const totalText = total === null ? "未知总量" : `共 ${total} 项`;
  return `已处理 ${processed} 项（${totalText}，剩余 ${outstanding} 项）`;
}

export function operationStatusLine(operation: DataOperationOut): string {
  switch (operation.status) {
    case "QUEUED":
    case "RUNNING":
      return "删除已提交，正在清理";
    case "RETRY_WAIT":
      return `部分清理尚未完成，系统将在 ${formatTime(operation.next_retry_at)} 重试（剩余 ${operation.progress.outstanding_count} 项）`;
    case "FAILED":
      return `删除未完成${operation.error ? `：${operation.error.message}` : ""}`;
    case "COMPLETED":
      return "服务端在线数据已清除";
    case "READY":
      return `可下载至 ${formatTime(operation.expires_at)}`;
    case "EXPIRED":
      return "导出包已到期";
    default:
      return `未知状态 ${operation.status}，已停用危险操作，请联系支持`;
  }
}

/** 已知 409/错误码 → 用户文案（B 稿 §2 表）；未识别返回 null 交上层
 *  通用错误展示，不吞错。 */
export function knownErrorCopy(code: string | undefined): string | null {
  switch (code) {
    case "deletion_in_progress":
      return "已有删除正在进行";
    case "preview_stale":
    case "preview_expired":
      return "数据已变化，请重新查看删除范围";
    case "version_conflict":
      return "操作已被更新，已重新获取最新状态";
    case "generation_stale":
      return "本地数据代际已过期，已重新对齐";
    default:
      return null;
  }
}
