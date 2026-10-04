import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import type { DecisionBasis } from "@agenthu/contracts";
import { DecisionBasisView, parseDecisionBasis } from "./DecisionBasisView";

const BASIS: DecisionBasis = {
  basis_version: "v1",
  summary: "作业临近且当前时段空闲，建议先复习第三章",
  references: [
    { kind: "task", id: "task-1", label: "HW1 第三章复习" },
    { kind: "event", id: "evt-1", label: "专注超时", locator: { occurred_at: "2026-10-03T09:00:00+08:00" } },
    { kind: "memory", id: "mem-1", label: "偏好上午复习", state: "source_deleted" },
    { kind: "material", id: "file-1", label: "lecture2.pdf", locator: { page: 74, quote: "Deterministic Games" } },
    { kind: "chat_message", id: "msg-9", label: "昨天的讨论", locator: { message_id: "0199f3c2-7d4a-4f21" } },
    { kind: "current_state", id: "state-42", label: "当前状态", locator: { state_version: 42 } },
  ],
  rule_versions: { planner: "v2", replan: "v1" },
  selected_tool_call_ids: ["call-1"],
};

describe("DecisionBasisView（契约 §4 共享 basis 渲染器）", () => {
  it("渲染服务端 summary 与规则版本，标注模型仅整理表述", () => {
    render(<DecisionBasisView basis={BASIS} />);
    expect(screen.getByText(BASIS.summary)).toBeTruthy();
    expect(screen.getByText(/规则版本：planner v2 · replan v1/)).toBeTruthy();
    expect(screen.getByText(/模型仅整理表述/)).toBeTruthy();
  });

  it("八种 kind 各自渲染人类标签与定位（定位不是正文）", () => {
    render(<DecisionBasisView basis={BASIS} />);
    expect(screen.getByText("任务")).toBeTruthy();
    expect(screen.getByText("HW1 第三章复习")).toBeTruthy();
    expect(screen.getByText(/发生于/)).toBeTruthy();
    expect(screen.getByText(/第 74 页/)).toBeTruthy();
    expect(screen.getByText(/「Deterministic Games」/)).toBeTruthy();
    // chat_message 是定位：只显示消息锚点短 id，不渲染消息内容
    expect(screen.getByText(/消息 0199f3c2/)).toBeTruthy();
    // current_state 是版本定位，不重复派生数字
    expect(screen.getByText(/状态版本 v42/)).toBeTruthy();
  });

  it("source_deleted / version_mismatch 显示失效标注，不改指同名对象", () => {
    render(<DecisionBasisView basis={{
      ...BASIS,
      references: [
        { kind: "memory", id: "mem-1", label: "偏好上午复习", state: "source_deleted" },
        { kind: "material", id: "file-1", label: "lecture2.pdf", state: "version_mismatch" },
      ],
    }} />);
    expect(screen.getByText(/来源已删除或不可用/)).toBeTruthy();
    expect(screen.getByText(/引用为旧版本/)).toBeTruthy();
    expect(screen.getByText("偏好上午复习")).toBeTruthy();
  });

  it("无 references / 无 rule_versions 时不渲染空容器", () => {
    const { container } = render(<DecisionBasisView basis={{
      ...BASIS, references: [], rule_versions: {},
    }} />);
    expect(container.querySelector(".basis-references")).toBeNull();
    expect(container.textContent).not.toContain("规则版本");
  });

  it("parseDecisionBasis：结构化形状通过，弱类型垃圾返回 null（兼容层兜底）", () => {
    expect(parseDecisionBasis(BASIS)?.basis_version).toBe("v1");
    expect(parseDecisionBasis({ deadline: "2026-10-04T23:59:00+08:00" })).toBeNull();
    expect(parseDecisionBasis(undefined)).toBeNull();
  });
});
