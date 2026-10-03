import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { campus } from "../../campus/instance";
import type { CampusCourseFile } from "../../adapters/campus/types";
import type { FileInfo } from "../../backend/grounding";
import { uploadCourseMaterial } from "../../adapters/materials";
import { errorText } from "../../lib/errors";
import { useServices } from "../../app/services";

/** 讲解页课件面板（TASKS/m3-materials-upload-ui.md §3）：按需拉取 learn 域
 *  文件列表（不进采集循环，§2 裁定；离开页面即弃——gcTime 0），显式单
 *  文件上传经 Rust 单命令（下载→无名临时文件→流式 POST，字节不进
 *  WebView）。§3.5 同意门标注：上传/抽取不需要授权，未授权前课件只做
 *  本地文本检索、不嵌入不外送。上传后的 status 生命周期（uploaded →
 *  extracted/unsupported_type/extraction_failed）由外层 grounding-files
 *  查询按文件名对应透出。 */

const FILE_STATUS_LABELS: Record<string, string> = {
  uploaded: "已上传 · 抽取进行中",
  extracted: "已抽取",
  unsupported_type: "类型不支持",
  extraction_failed: "抽取失败",
};

function uploadFilename(file: CampusCourseFile): string {
  if (file.title.includes(".")) return file.title;
  return file.fileType ? `${file.title}.${file.fileType}` : file.title;
}

export function MaterialsPanel({ courseName, consentEnabled, backendFiles }: {
  courseName: string;
  consentEnabled: boolean | null;
  backendFiles: FileInfo[];
}) {
  const { backendUrl, backendSession } = useServices();
  const queryClient = useQueryClient();

  const courses = useQuery({
    queryKey: ["campus-courses"],
    queryFn: () => campus.getCourses(),
    retry: false,
    gcTime: 0,
  });
  const courseId = courses.data?.find((course) => course.name === courseName)?.id ?? null;
  const files = useQuery({
    queryKey: ["campus-course-files", courseId],
    queryFn: () => campus.getCourseFiles(courseId!),
    enabled: courseId !== null,
    retry: false,
    gcTime: 0,
  });
  // 先按课程过滤再建图：backendFiles 是全课程列表，跨课程同名文件会
  // 互相串状态标签（#46 评审观察）
  const backendStatusByName = new Map(
    backendFiles
      .filter((file) => file.course_name === courseName)
      .map((file) => [file.filename, file.status]),
  );

  const upload = useMutation({
    mutationFn: (file: CampusCourseFile) => uploadCourseMaterial({
      downloadUrl: file.downloadUrl,
      backendUrl,
      bearerToken: backendSession?.token() ?? "",
      courseName,
      filename: uploadFilename(file),
    }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["grounding-files"] }),
  });

  return <div className="materials-panel">
    <div className="section-heading">
      <h3>课件（网络学堂）</h3>
      <span className="section-meta">按需拉取 · 单文件显式上传 · 临时文件即删</span>
    </div>
    {consentEnabled === false && (
      <p className="consent-text">上传与本地抽取不需要问答授权；未开启授权前，这些课件只用于本地文本检索（关键词命中），不会发送给模型供应商做嵌入或生成。</p>
    )}
    {consentEnabled === true && (
      <p className="consent-text">已开启本课问答授权：新上传的课件在抽取完成后将参与语义检索与回答生成。</p>
    )}
    {courses.isPending && <p className="empty-state">正在读取本学期课程列表…</p>}
    {courses.error && <p className="error-text">课件列表需要校园账号：{errorText(courses.error)}</p>}
    {courses.data && courseId === null && (
      <p className="empty-state">「{courseName}」不在网络学堂本学期课程列表中——课程名需与学堂课程名一致。</p>
    )}
    {courseId !== null && files.isPending && <p className="empty-state">正在读取课件列表…</p>}
    {courseId !== null && files.error && <p className="error-text">课件列表读取失败：{errorText(files.error)}</p>}
    {files.data && files.data.length === 0 && <p className="empty-state">该课程在学堂上没有可见的课件文件。</p>}
    {files.data && files.data.length > 0 && (
      <ul className="material-list">
        {files.data.map((file) => {
          const status = backendStatusByName.get(uploadFilename(file))
            ?? (upload.data && upload.variables?.id === file.id ? upload.data.status : undefined);
          const inFlight = upload.isPending && upload.variables?.id === file.id;
          return <li key={file.id} className="material-row">
            <div className="material-meta">
              <strong>{file.title}</strong>
              <span>{[file.size, file.fileType, file.uploadTime].filter(Boolean).join(" · ")}{file.important ? " · 重要" : ""}</span>
              {status && <span className="section-meta">{FILE_STATUS_LABELS[status] ?? status}</span>}
            </div>
            <button
              className="ghost-button"
              disabled={upload.isPending || !backendSession}
              title={backendSession ? "下载并上传到 Backend（抽取后进入讲解检索范围）" : "先登录 Backend"}
              onClick={() => upload.mutate(file)}
            >
              {inFlight ? "转送中…" : "上传"}
            </button>
          </li>;
        })}
      </ul>
    )}
    {upload.error && <p className="error-text" role="alert">{errorText(upload.error)}</p>}
  </div>;
}
