import { Fragment } from "react";
import { DecisionBasisSchema, type DecisionBasis, type DecisionReference } from "@agenthu/contracts";

/** 共享 basis 渲染器（契约 §4）：Plan 的 `BasisPanel`、重排建议、
 *  pending action 和 Chat「为什么」复用同一份 `DecisionBasis` 结构化
 *  渲染；历史 Plan 的 `Record<string, unknown>` 弱类型仍走 `BasisPanel`
 *  兼容层（`agent_decision` 子键由 BasisPanel 检出后转交本组件）。
 *
 *  渲染纪律：`summary` 是服务端按规则/证据产生的摘要（模型仅润色）；
 *  reference 是定位不是正文——不渲染原始 tool args、prompt、课件正文
 *  或聊天内容；来源不可达显示失效标注，不改指同名对象。 */

const KIND_LABELS: Record<DecisionReference["kind"], string> = {
  event: "事件",
  memory: "记忆",
  goal: "目标",
  plan: "计划",
  task: "任务",
  material: "资料",
  chat_message: "聊天消息",
  current_state: "当前状态",
};

function formatTime(value: string): string {
  const time = new Date(value);
  return Number.isNaN(time.getTime()) ? value : time.toLocaleString();
}

/** 单条 reference 的定位行：只渲染定位元数据，绝不展开来源正文。 */
function referenceLocatorText(reference: DecisionReference): string | null {
  const locator = reference.locator;
  if (!locator) return null;
  const parts: string[] = [];
  if (locator.occurred_at !== undefined && locator.occurred_at !== null) parts.push(`发生于 ${formatTime(locator.occurred_at)}`);
  if (locator.page !== undefined && locator.page !== null) parts.push(`第 ${locator.page} 页`);
  if (locator.quote) parts.push(`「${locator.quote}」`);
  if (locator.message_id) parts.push(`消息 ${locator.message_id.slice(0, 8)}`);
  if (locator.state_version !== undefined && locator.state_version !== null) parts.push(`状态版本 v${locator.state_version}`);
  return parts.length > 0 ? parts.join(" · ") : null;
}

function stateBadge(reference: DecisionReference): string | null {
  if (reference.state === "source_deleted") return "来源已删除或不可用";
  if (reference.state === "version_mismatch") return "引用为旧版本（来源已更新）";
  return null;
}

export function DecisionBasisView({ basis }: { basis: DecisionBasis }) {
  const ruleText = Object.entries(basis.rule_versions)
    .map(([rule, version]) => `${rule} ${version}`)
    .join(" · ");
  return <div className="decision-basis" data-basis-version={basis.basis_version}>
    <p className="basis-summary">{basis.summary}</p>
    <p className="basis-note">事实与引用以服务端记录为准；模型仅整理表述。</p>
    {basis.references.length > 0 && <ul className="basis-references">
      {basis.references.map((reference, index) => {
        const badge = stateBadge(reference);
        const locator = referenceLocatorText(reference);
        return <li key={`${reference.kind}-${reference.id}-${index}`} className={badge ? "basis-reference-stale" : undefined}>
          <span className="basis-reference-kind">{KIND_LABELS[reference.kind] ?? reference.kind}</span>
          {" "}
          <span className="basis-reference-label">{reference.label}</span>
          {badge && <span className="basis-reference-badge"> · {badge}</span>}
          {locator && <Fragment>{" — "}{locator}</Fragment>}
        </li>;
      })}
    </ul>}
    {ruleText && <p className="basis-rules">规则版本：{ruleText}</p>}
  </div>;
}

/** 弱类型入口（BasisPanel 兼容路径 / 未来新调用方）：能解析成结构化形状才
 *  交给 DecisionBasisView，否则返回 null 由调用方走原兜底——契约形状演进
 *  不炸历史面板。 */
export function parseDecisionBasis(value: unknown): DecisionBasis | null {
  const parsed = DecisionBasisSchema.safeParse(value);
  return parsed.success ? parsed.data : null;
}
