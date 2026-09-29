import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { TaskList } from "./TaskList";
import type { Task } from "@agenthu/contracts";

function makeTask(overrides: Partial<Task> = {}): Task {
  return {
    id: "t1",
    title: "Linear Algebra HW2",
    due_at: "2026-10-01T23:59:00+08:00",
    estimate_minutes: 60,
    status: "todo",
    source_event_ids: [],
    ...overrides,
  };
}

describe("TaskList 来源徽标（M1-1 派生任务可辨识）", () => {
  it("onethu 派生任务显示「校园采集」徽标", () => {
    render(<TaskList tasks={[makeTask({ source: "onethu" })]} loading={false} error={null} configured={true} />);
    expect(screen.getByText("校园采集")).toBeTruthy();
    expect(screen.getByText("Linear Algebra HW2")).toBeTruthy();
  });

  it("manual 任务不显示徽标", () => {
    render(<TaskList tasks={[makeTask({ source: "manual" })]} loading={false} error={null} configured={true} />);
    expect(screen.queryByText("校园采集")).toBeNull();
  });

  it("缺失 source（旧 Backend 载荷）不显示徽标且正常渲染", () => {
    const task = makeTask();
    delete (task as Partial<Task>).source;
    render(<TaskList tasks={[task]} loading={false} error={null} configured={true} />);
    expect(screen.queryByText("校园采集")).toBeNull();
    expect(screen.getByText("Linear Algebra HW2")).toBeTruthy();
  });

  it("未知来源显示原始 source 字符串", () => {
    render(<TaskList tasks={[makeTask({ source: "learnx" })]} loading={false} error={null} configured={true} />);
    expect(screen.getByText("learnx")).toBeTruthy();
  });

  it("截止时间以本地化格式展示", () => {
    render(<TaskList tasks={[makeTask({ due_at: null })]} loading={false} error={null} configured={true} />);
    expect(screen.getByText("无截止时间")).toBeTruthy();
  });

  it("未配置 Backend / 加载中 / 错误 / 空列表的既有状态不变", () => {
    const { rerender } = render(<TaskList tasks={[]} loading={false} error={null} configured={false} />);
    expect(screen.getByText("配置 Backend 地址后显示任务。")).toBeTruthy();
    rerender(<TaskList tasks={[]} loading={true} error={null} configured={true} />);
    expect(screen.getByText("正在读取任务…")).toBeTruthy();
    rerender(<TaskList tasks={[]} loading={false} error={new Error("boom")} configured={true} />);
    expect(screen.getByText("任务读取失败：boom")).toBeTruthy();
    rerender(<TaskList tasks={[]} loading={false} error={null} configured={true} />);
    expect(screen.getByText("暂无任务。")).toBeTruthy();
  });
});
