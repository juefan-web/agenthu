import { invoke } from "@tauri-apps/api/core";
import { BackendAuthError } from "../backend/client";
import { FileInfoSchema, type FileInfo } from "../backend/grounding";
import { isTauriRuntime } from "./campus/tauriTransport";

/** 课件转送 wrapper（TASKS/m3-materials-upload-ui.md §3.2/§3.3）：Rust 单
 *  命令内完成 learn 下载 → 无名临时文件 → 流式 multipart POST /v1/files。
 *  React 层只发命令、收状态——文件字节不进 WebView（与 campus 采集同
 *  边界）；临时文件句柄 RAII 删除，失败路径无残留。
 *
 *  `downloadUrl` 是当次文件列表响应里的会话态 URL，用完即弃（不落
 *  Event/存储）。 */

export interface MaterialUploadInput {
  /** learn 文件下载 URL（来自当次 getCourseFiles 响应）。 */
  downloadUrl: string;
  /** Backend base URL（wrapper 内拼 `/v1/files`，单点口径）。 */
  backendUrl: string;
  bearerToken: string;
  courseName: string;
  filename: string;
  contentType?: string;
}

interface TransferResponse {
  status: number;
  body: string;
}

export async function uploadCourseMaterial(input: MaterialUploadInput): Promise<FileInfo> {
  if (!isTauriRuntime()) throw new Error("课件上传需要 Tauri 客户端");
  const response = await invoke<TransferResponse>("material_upload", {
    request: {
      downloadUrl: input.downloadUrl,
      backendUrl: `${input.backendUrl.replace(/\/+$/, "")}/v1/files`,
      bearerToken: input.bearerToken,
      courseName: input.courseName,
      filename: input.filename,
      contentType: input.contentType ?? null,
    },
  });
  if (response.status === 401) throw new BackendAuthError();
  if (response.status >= 400) {
    let message = `课件上传失败（HTTP ${response.status}）`;
    try {
      const envelope = JSON.parse(response.body) as { error?: { message?: string } };
      if (envelope?.error?.message) message = envelope.error.message;
    } catch {
      // 非 JSON 错误体保持通用文案
    }
    throw new Error(message);
  }
  return FileInfoSchema.parse(JSON.parse(response.body));
}
