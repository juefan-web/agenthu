import { beforeAll, describe, expect, it, vi } from "vitest";
import { MemoryReceiptStore } from "../../backend/receiptStore";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { MaterialAnswer } from "../../backend/grounding";
import { BackendHttpError } from "../../backend/client";
import { AppServicesContext, type AppServices } from "../../app/services";
import { GroundedAnswersView } from "./GroundedAnswersView";

vi.mock("../../campus/instance", () => ({
  campus: { getCourses: vi.fn().mockResolvedValue([]), getCourseFiles: vi.fn().mockResolvedValue([]) },
}));

const listFiles = vi.fn();
const getGroundingConsent = vi.fn();
const setGroundingConsent = vi.fn();
const askGroundedQuestion = vi.fn();
const listGroundedAnswers = vi.fn();
const deleteGroundedAnswer = vi.fn();

const consentDisabled = {
  course_name: "信号与系统",
  enabled: false,
  consent_text: "开启后，当你在此课程中提问，系统会把与问题最相关的课程资料片段发送给模型供应商。",
  consent_text_version: "v1",
  consented_at: null,
};
const consentEnabled = { ...consentDisabled, enabled: true, consented_at: "2026-10-02T09:00:00+08:00" };
const files = [
  { id: "file-1", filename: "lecture1.pdf", checksum_sha256: "chk-1", course_name: "信号与系统", status: "ready" },
  { id: "file-2", filename: "lecture2.pdf", checksum_sha256: "chk-2-new", course_name: "信号与系统", status: "ready" },
];

function makeAnswer(overrides: Partial<MaterialAnswer>): MaterialAnswer {
  return {
    id: "ans-1",
    course_name: "信号与系统",
    question: "什么是采样定理",
    answer: "约束是「采样率至少为信号最高频率的两倍」[2]。",
    grounded: true,
    citations: [{
      file_id: "file-1",
      checksum: "chk-1",
      page: 2,
      span_start: 0,
      span_end: 13,
      quote: "采样率至少为信号最高频率的两倍",
    }],
    chunk_ids: ["chunk-1"],
    memory_ids: [],
    model_version: "fake-model",
    prompt_version: "v1",
    created_at: "2026-10-02T10:00:00+08:00",
    ...overrides,
  };
}

/** 各测试先统一重置并给默认值，再按需覆盖（避免 once 队列跨测试泄漏）。 */
function setupDefaultMocks() {
  listFiles.mockReset().mockResolvedValue(files);
  getGroundingConsent.mockReset().mockResolvedValue(consentEnabled);
  setGroundingConsent.mockReset().mockResolvedValue(consentEnabled);
  askGroundedQuestion.mockReset();
  listGroundedAnswers.mockReset();
  deleteGroundedAnswer.mockReset();
}

function renderView() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const backend = {
    listFiles, getGroundingConsent, setGroundingConsent, askGroundedQuestion, listGroundedAnswers, deleteGroundedAnswer,
  } as unknown as AppServices["backend"];
  const services = { backend, backendSession: null, queue: {} as never, focusDraft: {} as never, sync: null, receipts: new MemoryReceiptStore(), resolveOwner: () => null, backendUrl: "http://backend", buildTimeBackendUrl: "" };
  return render(<QueryClientProvider client={queryClient}><AppServicesContext.Provider value={services}><GroundedAnswersView /></AppServicesContext.Provider></QueryClientProvider>);
}

/** 选课程（label 关联 input）——同意门与提问表单都以课程为前提。 */
async function pickCourse() {
  fireEvent.change(screen.getByLabelText("课程"), { target: { value: "信号与系统" } });
  await screen.findByText(/开启前请阅读授权说明|资料问答已开启/);
}

describe("GroundedAnswersView（讲解页，M3 §6 客户端半边）", () => {
  beforeAll(() => {
    // jsdom 无滚动实现；引用跳转的 scrollIntoView 只需不抛错
    window.HTMLElement.prototype.scrollIntoView = () => {};
    window.confirm = () => true;
  });

  it("未开启时展示后端下发的授权文本，开启需回显其版本", async () => {
    setupDefaultMocks();
    getGroundingConsent.mockResolvedValue(consentDisabled);
    listFiles.mockResolvedValue(files);
    getGroundingConsent.mockResolvedValue(consentDisabled);
    renderView();
    await pickCourse();
    expect(screen.getByText(/系统会把与问题最相关的课程资料片段发送给模型供应商/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "提问" })).toBeNull(); // 未开启不可问
    fireEvent.click(screen.getByRole("button", { name: "同意并开启" }));
    await waitFor(() => expect(setGroundingConsent).toHaveBeenCalledWith("信号与系统", true, "v1"));
  });

  it("开启后提问：回答、引用卡（文件名+页码+摘录）与标记可跳转元素渲染", async () => {
    setupDefaultMocks();
    listFiles.mockResolvedValue(files);
    getGroundingConsent.mockResolvedValue(consentEnabled);
    askGroundedQuestion.mockResolvedValue(makeAnswer({}));
    renderView();
    await pickCourse();
    fireEvent.change(screen.getByLabelText("问题"), { target: { value: "什么是采样定理" } });
    fireEvent.click(screen.getByRole("button", { name: "提问" }));
    await waitFor(() => expect(askGroundedQuestion).toHaveBeenCalledWith("信号与系统", "什么是采样定理"));
    expect(await screen.findByText(/约束是/)).toBeTruthy();
    // 最新回答卡走 latest- 命名空间：与历史同条回答并存时 DOM id 不重复
    expect(screen.getByTitle("跳到引用").id).toBe("latest-marker-ans-1-0");
    expect(screen.getByText(/lecture1\.pdf · 第 2 页/)).toBeTruthy();
    expect(screen.getByText("采样率至少为信号最高频率的两倍")).toBeTruthy();
    expect(screen.getByText(/已落地 · 1 条引用 · 模型 fake-model/)).toBeTruthy();
  });

  it("文件已删/已换版本的引用标失效锚点（§6：由 UI 标注）", async () => {
    setupDefaultMocks();
    listFiles.mockResolvedValue(files);
    getGroundingConsent.mockResolvedValue(consentEnabled);
    askGroundedQuestion.mockResolvedValue(makeAnswer({
      citations: [
        { file_id: "file-gone", checksum: "chk-0", page: 1, span_start: 0, span_end: 5, quote: "第一条" },
        { file_id: "file-2", checksum: "chk-2-old", page: 3, span_start: 0, span_end: 5, quote: "第二条" },
        { file_id: "file-1", checksum: "chk-1", page: 2, span_start: 0, span_end: 5, quote: "第三条" },
      ],
    }));
    renderView();
    await pickCourse();
    fireEvent.change(screen.getByLabelText("问题"), { target: { value: "q" } });
    fireEvent.click(screen.getByRole("button", { name: "提问" }));
    expect(await screen.findByText(/文件已删除，引用指向失效锚点/)).toBeTruthy();
    expect(screen.getByText(/文件已更新（重传），引用指向旧版本/)).toBeTruthy();
    expect(screen.getByText(/lecture2\.pdf · 第 3 页/)).toBeTruthy();
  });

  it("403 fail-closed 与 503 不降级在 UI 分流提示", async () => {
    setupDefaultMocks();
    listFiles.mockResolvedValue(files);
    getGroundingConsent.mockResolvedValue(consentEnabled);
    askGroundedQuestion.mockRejectedValueOnce(new BackendHttpError("not enabled", 403));
    askGroundedQuestion.mockRejectedValueOnce(new BackendHttpError("provider down", 503));
    renderView();
    await pickCourse();
    fireEvent.change(screen.getByLabelText("问题"), { target: { value: "q" } });
    fireEvent.click(screen.getByRole("button", { name: "提问" }));
    expect((await screen.findByRole("alert")).textContent).toMatch(/请先阅读并同意上方授权/);
    fireEvent.click(screen.getByRole("button", { name: "提问" }));
    await waitFor(() => expect(screen.getByRole("alert").textContent).toMatch(/生成服务暂不可用/));
  });

  it("未落地徽标：无存活引用的回答如实标注", async () => {
    setupDefaultMocks();
    listFiles.mockResolvedValue(files);
    getGroundingConsent.mockResolvedValue(consentEnabled);
    askGroundedQuestion.mockResolvedValue(makeAnswer({ grounded: false, citations: [] }));
    renderView();
    await pickCourse();
    fireEvent.change(screen.getByLabelText("问题"), { target: { value: "q" } });
    fireEvent.click(screen.getByRole("button", { name: "提问" }));
    expect(await screen.findByText(/未落地（无通过校验的引用）/)).toBeTruthy();
  });

  it("历史列表与删除入口（引用快照一并删除）", async () => {
    setupDefaultMocks();
    listFiles.mockResolvedValue(files);
    getGroundingConsent.mockResolvedValue(consentEnabled);
    listGroundedAnswers.mockResolvedValue([makeAnswer({ id: "ans-hist" }), makeAnswer({ id: "ans-hist-2", question: "什么是频谱" })]);
    deleteGroundedAnswer.mockResolvedValue(undefined);
    renderView();
    await pickCourse();
    fireEvent.click(await screen.findByText(/展开历史（2 条）/));
    expect(screen.getByText("什么是采样定理")).toBeTruthy();
    // 历史卡保持裸 id（latest 专属前缀不进历史）
    expect(document.getElementById("citation-ans-hist-0")).toBeTruthy();
    expect(document.getElementById("latest-citation-ans-hist-0")).toBeNull();
    fireEvent.click(screen.getAllByRole("button", { name: "删除" })[0]!);
    await waitFor(() => expect(deleteGroundedAnswer).toHaveBeenCalledWith("ans-hist"));
  });
});
