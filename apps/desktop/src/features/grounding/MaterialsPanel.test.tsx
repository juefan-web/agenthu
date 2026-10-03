import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { CampusCourse } from "../../adapters/campus/types";
import type { FileInfo } from "../../backend/grounding";
import { AppServicesContext, type AppServices } from "../../app/services";
import { MaterialsPanel } from "./MaterialsPanel";

const getCourses = vi.hoisted(() => vi.fn());
const getCourseFiles = vi.hoisted(() => vi.fn());
vi.mock("../../campus/instance", () => ({
  campus: { getCourses, getCourseFiles },
}));
const uploadCourseMaterial = vi.hoisted(() => vi.fn());
vi.mock("../../adapters/materials", () => ({ uploadCourseMaterial }));

const course: CampusCourse = {
  id: "course-1",
  name: "信号与系统",
  englishName: "Signals",
  courseNumber: "00420052",
  teacherName: "Teacher",
  timeAndLocation: [],
  url: "https://learn.tsinghua.edu.cn/course-1",
};
const learnFile = {
  id: "wjid-1",
  courseId: "course-1",
  title: "第3讲 傅里叶变换.pdf",
  uploadTime: "2026-09-26 10:00",
  downloadUrl: "https://learn.tsinghua.edu.cn/b/download?wjid=wjid-1",
  fileType: "pdf",
  size: "2.3MB",
  important: false,
};
const backendFile: FileInfo = {
  id: "file-9",
  filename: "第3讲 傅里叶变换.pdf",
  checksum_sha256: null,
  course_name: "信号与系统",
  status: "extracted",
};

function renderPanel(props: { consentEnabled?: boolean | null; backendFiles?: FileInfo[] } = {}) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const services = {
    backendUrl: "http://backend",
    backendSession: { token: () => "jwt" },
    backend: {} as never,
  } as unknown as AppServices;
  return render(<QueryClientProvider client={queryClient}>
    <AppServicesContext.Provider value={services}>
      <MaterialsPanel
        courseName="信号与系统"
        consentEnabled={props.consentEnabled ?? null}
        backendFiles={props.backendFiles ?? []}
      />
    </AppServicesContext.Provider>
  </QueryClientProvider>);
}

describe("MaterialsPanel（课件上传入口，M3 §3）", () => {
  beforeEach(() => {
    getCourses.mockReset().mockResolvedValue([course]);
    getCourseFiles.mockReset().mockResolvedValue([learnFile]);
    uploadCourseMaterial.mockReset().mockResolvedValue({ ...backendFile, status: "uploaded" });
  });

  it("renders the on-demand list and uploads one file with the joined arguments", async () => {
    renderPanel();
    fireEvent.click(await screen.findByRole("button", { name: "上传" }));
    await waitFor(() => expect(uploadCourseMaterial).toHaveBeenCalledWith({
      downloadUrl: "https://learn.tsinghua.edu.cn/b/download?wjid=wjid-1",
      backendUrl: "http://backend",
      bearerToken: "jwt",
      courseName: "信号与系统",
      filename: "第3讲 傅里叶变换.pdf",
    }));
  });

  it("annotates the consent gate both ways (§3.5 如实标注)", async () => {
    const { unmount } = renderPanel({ consentEnabled: false });
    expect(await screen.findByText(/不会发送给模型供应商做嵌入或生成/)).toBeTruthy();
    unmount();
    renderPanel({ consentEnabled: true });
    expect(await screen.findByText(/将参与语义检索与回答生成/)).toBeTruthy();
  });

  it("surfaces backend status per file and campus failures without a silent empty list", async () => {
    renderPanel({ backendFiles: [backendFile] });
    expect(await screen.findByText("已抽取")).toBeTruthy();
  });

  it("shows the campus-auth failure as an explicit error", async () => {
    getCourses.mockReset().mockRejectedValue(new Error("校园账号未连接"));
    renderPanel();
    expect(await screen.findByText(/课件列表需要校园账号：校园账号未连接/)).toBeTruthy();
  });

  it("hints when the typed course is not in this semester's learn list", async () => {
    getCourses.mockReset().mockResolvedValue([]);
    renderPanel();
    expect(await screen.findByText(/不在网络学堂本学期课程列表中/)).toBeTruthy();
  });

  it("propagates upload failures inline", async () => {
    uploadCourseMaterial.mockReset().mockRejectedValue(new Error("课件上传失败（HTTP 502）"));
    renderPanel();
    fireEvent.click(await screen.findByRole("button", { name: "上传" }));
    expect((await screen.findByRole("alert")).textContent).toBe("课件上传失败（HTTP 502）");
  });
});
