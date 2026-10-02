import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { BasisPanel } from "./BasisPanel";

const BASIS = {
  deadline: "2026-10-04T23:59:00+08:00",
  slack_minutes: -30,
  estimate_minutes: 75,
  estimate_source: "learned:course",
  slot_reason: "14:00-15:30 是今天课间最长空档",
  at_risk: true,
};

describe("BasisPanel（D-031 §1「为什么」面板）", () => {
  it("缺失或空 basis 不渲染（服务端缺省归一为空对象）", () => {
    const { container } = render(<BasisPanel basis={undefined} />);
    expect(container.childElementCount).toBe(0);
    const { container: empty } = render(<BasisPanel basis={{}} />);
    expect(empty.childElementCount).toBe(0);
  });

  it("已知字段按语义渲染：估时来源本地化、缓冲与预计分钟数", () => {
    render(<BasisPanel basis={BASIS} />);
    expect(screen.getByText("为什么")).toBeTruthy();
    expect(screen.getByText("同课程历史实际用时（中位数）")).toBeTruthy();
    expect(screen.getByText("75 分钟")).toBeTruthy();
    expect(screen.getByText("14:00-15:30 是今天课间最长空档")).toBeTruthy();
  });

  it("负 slack 与 at_risk 走风险样式并明确提示", () => {
    render(<BasisPanel basis={BASIS} />);
    expect(screen.getByText("⚠ -30 分钟（时间已不足）").className).toContain("basis-at-risk");
    expect(screen.getByText("⚠ 截止临近，缓冲不足")).toBeTruthy();
  });

  it("未知字段（契约演进）原样透出，不需要客户端发版", () => {
    render(<BasisPanel basis={{ energy_level: 3, note: "考前周" }} />);
    expect(screen.getByText("energy_level")).toBeTruthy();
    expect(screen.getByText("3")).toBeTruthy();
    expect(screen.getByText("note")).toBeTruthy();
    expect(screen.getByText("考前周")).toBeTruthy();
  });

  it("learned 估时带样本数（与 reason 同口径），user/default 不带", () => {
    render(<BasisPanel basis={{ estimate_source: "learned:course", sample_count: 4 } as Record<string, unknown>} />);
    expect(screen.getByText("同课程历史实际用时（中位数），近 4 次")).toBeTruthy();
    const { container } = render(<BasisPanel basis={{ estimate_source: "user" } as Record<string, unknown>} />);
    expect(container.textContent).not.toContain("近");
  });

  it("score 分量展开为打分行", () => {
    render(<BasisPanel basis={{ score: { urgency: 12, goal_weight: 3 } }} />);
    expect(screen.getByText("打分 · urgency")).toBeTruthy();
    expect(screen.getByText("12")).toBeTruthy();
    expect(screen.getByText("打分 · goal_weight")).toBeTruthy();
  });

  it("未知估时来源显示原始字符串（未来枚举值）", () => {
    render(<BasisPanel basis={{ estimate_source: "learned:type" } as Record<string, unknown>} />);
    expect(screen.getByText("learned:type")).toBeTruthy();
  });
});
