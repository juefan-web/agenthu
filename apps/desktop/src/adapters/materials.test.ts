import { describe, expect, it, vi, beforeEach } from "vitest";
import { BackendAuthError } from "../backend/client";
import { uploadCourseMaterial } from "./materials";

const invoke = vi.hoisted(() => vi.fn());
vi.mock("@tauri-apps/api/core", () => ({ invoke }));
vi.mock("./campus/tauriTransport", () => ({
  isTauriRuntime: () => true,
}));

const uploadFixture = {
  id: "019b3c2d-0000-7000-8000-000000000001",
  filename: "lecture3.pdf",
  checksum_sha256: "chk-3",
  course_name: "信号与系统",
  status: "uploaded",
};

function ok(body: unknown = uploadFixture) {
  return { status: 201, body: JSON.stringify(body) };
}

describe("uploadCourseMaterial（material_upload 命令 wrapper）", () => {
  beforeEach(() => invoke.mockReset());

  it("sends the transfer request with a joined /v1/files URL and null contentType default", async () => {
    invoke.mockResolvedValue(ok());
    const file = await uploadCourseMaterial({
      downloadUrl: "https://learn.tsinghua.edu.cn/b/download?wjid=wjid-1",
      backendUrl: "http://127.0.0.1:8000/",
      bearerToken: "jwt",
      courseName: "信号与系统",
      filename: "lecture3.pdf",
    });
    expect(file.id).toBe(uploadFixture.id);
    expect(file.status).toBe("uploaded");
    expect(invoke).toHaveBeenCalledWith("material_upload", {
      request: {
        downloadUrl: "https://learn.tsinghua.edu.cn/b/download?wjid=wjid-1",
        backendUrl: "http://127.0.0.1:8000/v1/files",
        bearerToken: "jwt",
        courseName: "信号与系统",
        filename: "lecture3.pdf",
        contentType: null,
      },
    });
  });

  it("surfaces the backend error envelope on failure", async () => {
    invoke.mockResolvedValue({ status: 422, body: JSON.stringify({ error: { code: "validation", message: "不支持的文件类型" } }) });
    await expect(uploadCourseMaterial({
      downloadUrl: "u", backendUrl: "http://127.0.0.1:8000", bearerToken: "jwt",
      courseName: "c", filename: "f.exe",
    })).rejects.toThrow("不支持的文件类型");
  });

  it("maps 401 to the session-expired error, non-JSON bodies keep a generic message", async () => {
    invoke.mockResolvedValueOnce({ status: 401, body: "" });
    await expect(uploadCourseMaterial({
      downloadUrl: "u", backendUrl: "http://127.0.0.1:8000", bearerToken: "jwt",
      courseName: "c", filename: "f",
    })).rejects.toBeInstanceOf(BackendAuthError);

    invoke.mockResolvedValueOnce({ status: 502, body: "<html>bad gateway</html>" });
    await expect(uploadCourseMaterial({
      downloadUrl: "u", backendUrl: "http://127.0.0.1:8000", bearerToken: "jwt",
      courseName: "c", filename: "f",
    })).rejects.toThrow("课件上传失败（HTTP 502）");
  });
});
