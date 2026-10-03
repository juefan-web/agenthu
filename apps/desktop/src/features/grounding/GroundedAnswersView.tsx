import { Fragment, useMemo, useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { MaterialAnswer } from "../../backend/grounding";
import { BackendHttpError } from "../../backend/client";
import { MaterialsPanel } from "./MaterialsPanel";
import { errorText } from "../../lib/errors";
import { useServices } from "../../app/services";

/** 讲解页（M3 grounding 客户端半边，TASKS/m3-grounded-answers.md §6 冻结
 *  形状）：课程选择 → 同意门（consent_text 由后端下发，「开启」基于用户
 *  实际读到的措辞）→ 提问（403 fail-closed / 503 不降级分流）→ 回答 +
 *  引用卡（quote + page 呈现，§6 裁定不依赖 span 精确渲染；引用与文中
 *  标记双向跳转）→ 历史与删除。文件已删/已换版本 → 失效锚点标注（§6：
 *  删除文件后旧引用指向失效锚点属预期，由 UI 标注）。
 *
 * 课件上传 UI 不在本切片（后端 /v1/files 已可用；上传入口是后续项）。 */

// 与后端 verify_citations 的存活标记同形：清洗后的回答文本只保留通过
// 机械校验的 「quote」[n]，位置顺序即 citations 数组顺序。
const CITATION_MARKER = /「([^」]{1,400})」\[(\d{1,3})]/g;

function scrollToId(id: string) {
  document.getElementById(id)?.scrollIntoView({ block: "center", behavior: "smooth" });
}

function answerMetaText(answer: MaterialAnswer): string {
  const time = new Date(answer.created_at).toLocaleString();
  return `${answer.grounded ? `已落地 · ${answer.citations.length} 条引用` : "未落地（无通过校验的引用）"} · 模型 ${answer.model_version} · prompt ${answer.prompt_version} · ${time}`;
}

function askErrorText(error: unknown): string {
  if (error instanceof BackendHttpError && error.status === 403) {
    return "该课程未开启资料问答：请先阅读并同意上方授权，再提问。";
  }
  if (error instanceof BackendHttpError && error.status === 503) {
    return "生成服务暂不可用（模型供应商故障或未配置），请稍后重试；不会降级为无引用回答。";
  }
  return errorText(error);
}

/** 回答正文：把存活引用标记渲染为可点击引用点（与引用卡双向跳转）。
 *  idPrefix 给「最新回答卡」命名空间——它常与历史列表里的同一条回答
 *  同时渲染，共用 answer.id 拼 DOM id 会重复，跳转/高亮命中第一处
 *  （E5-UI 验收轮观察）。 */
function AnswerText({ answer, highlighted, idPrefix = "" }: {
  answer: MaterialAnswer;
  highlighted: number | null;
  idPrefix?: string;
}) {
  const parts: ReactNode[] = [];
  let cursor = 0;
  let survivor = 0;
  let match: RegExpExecArray | null;
  CITATION_MARKER.lastIndex = 0;
  while ((match = CITATION_MARKER.exec(answer.answer)) !== null) {
    const index = survivor;
    parts.push(<Fragment key={`t${cursor}`}>{answer.answer.slice(cursor, match.index)}</Fragment>);
    parts.push(
      <button
        key={`m${match.index}`}
        type="button"
        id={`${idPrefix}marker-${answer.id}-${index}`}
        className={`citation-marker ${highlighted === index ? "highlighted" : ""}`}
        title="跳到引用"
        onClick={() => scrollToId(`${idPrefix}citation-${answer.id}-${index}`)}
      >
        「{match[1]}」<sup>[{match[2]}]</sup>
      </button>,
    );
    cursor = match.index + match[0].length;
    survivor += 1;
  }
  parts.push(<Fragment key={`t${cursor}`}>{answer.answer.slice(cursor)}</Fragment>);
  return <p className="answer-text">{parts}</p>;
}

function CitationList({ answer, filesById, highlighted, onHighlight, idPrefix = "" }: {
  answer: MaterialAnswer;
  filesById: Map<string, { filename: string; checksum: string | null }>;
  highlighted: number | null;
  onHighlight: (index: number) => void;
  idPrefix?: string;
}) {
  if (answer.citations.length === 0) return null;
  return <ul className="citation-list">
    {answer.citations.map((citation, index) => {
      const file = filesById.get(citation.file_id);
      const stale = file === undefined;
      const outdated = file !== undefined && file.checksum !== null && citation.checksum !== null && file.checksum !== citation.checksum;
      return <li key={index} id={`${idPrefix}citation-${answer.id}-${index}`} className={`citation-card ${highlighted === index ? "highlighted" : ""}`}>
        <button type="button" className="citation-source" onClick={() => { onHighlight(index); scrollToId(`${idPrefix}marker-${answer.id}-${index}`); }}>
          [{index + 1}] {file ? file.filename : `文件已删除（${citation.file_id.slice(0, 8)}…）`}
          {citation.page !== null ? ` · 第 ${citation.page} 页` : ""}
        </button>
        <blockquote>{citation.quote}</blockquote>
        {stale && <span className="citation-note">文件已删除，引用指向失效锚点</span>}
        {outdated && <span className="citation-note">文件已更新（重传），引用指向旧版本</span>}
      </li>;
    })}
  </ul>;
}

function AnswerCard({ answer, filesById, onDelete, idPrefix = "" }: {
  answer: MaterialAnswer;
  filesById: Map<string, { filename: string; checksum: string | null }>;
  onDelete?: (answer: MaterialAnswer) => void;
  idPrefix?: string;
}) {
  const [highlighted, setHighlighted] = useState<number | null>(null);
  return <article className="answer-card">
    {onDelete && <div className="task-title-line">
      <strong>{answer.question}</strong>
      <button className="ghost-button" onClick={() => onDelete(answer)}>删除</button>
    </div>}
    <AnswerText answer={answer} highlighted={highlighted} idPrefix={idPrefix} />
    <span className="section-meta">{answerMetaText(answer)}</span>
    <CitationList answer={answer} filesById={filesById} highlighted={highlighted} onHighlight={setHighlighted} idPrefix={idPrefix} />
  </article>;
}

export function GroundedAnswersView() {
  const { backend } = useServices();
  const queryClient = useQueryClient();
  const [courseName, setCourseName] = useState("");
  const [question, setQuestion] = useState("");
  const course = courseName.trim();

  const files = useQuery({ queryKey: ["grounding-files"], queryFn: () => backend!.listFiles(), enabled: !!backend, retry: false });
  const consent = useQuery({
    queryKey: ["grounding-consent", course],
    queryFn: () => backend!.getGroundingConsent(course),
    enabled: !!backend && course !== "",
    retry: false,
  });
  const answers = useQuery({
    queryKey: ["grounded-answers", course],
    queryFn: () => backend!.listGroundedAnswers(course),
    enabled: !!backend && course !== "" && consent.data?.enabled === true,
  });

  const filesById = useMemo(
    () => new Map((files.data ?? []).map((file) => [file.id, { filename: file.filename, checksum: file.checksum_sha256 }])),
    [files.data],
  );
  const courses = useMemo(
    () => [...new Set((files.data ?? []).map((file) => file.course_name).filter((name): name is string => name !== null))],
    [files.data],
  );

  const invalidateConsent = () => {
    void queryClient.invalidateQueries({ queryKey: ["grounding-consent", course] });
    void queryClient.invalidateQueries({ queryKey: ["grounded-answers", course] });
  };
  const setConsent = useMutation({
    mutationFn: (enabled: boolean) => {
      if (!consent.data) throw new Error("尚未读取授权文本");
      return backend!.setGroundingConsent(course, enabled, consent.data.consent_text_version);
    },
    onSuccess: invalidateConsent,
  });

  const ask = useMutation({
    mutationFn: () => backend!.askGroundedQuestion(course, question.trim()),
    onSuccess: () => {
      setQuestion("");
      void queryClient.invalidateQueries({ queryKey: ["grounded-answers", course] });
    },
  });
  const remove = useMutation({
    mutationFn: (answerId: string) => backend!.deleteGroundedAnswer(answerId),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["grounded-answers", course] }),
  });
  const deleteAnswer = (answer: MaterialAnswer) => {
    if (window.confirm("删除这条问答记录？引用快照将一并删除。")) remove.mutate(answer.id);
  };

  if (!backend) return <section className="workspace-section"><p className="empty-state">配置 Backend 地址后可以使用课程讲解。</p></section>;

  const enabled = consent.data?.enabled === true;
  const latest = ask.data ?? null;

  return <section className="workspace-section grounding-workspace">
    <div className="section-heading">
      <h2>课程讲解</h2>
      <span className="section-meta">基于已上传课料的落地问答 · 引用可核</span>
    </div>

    <label className="field-label" htmlFor="grounding-course">课程</label>
    <input
      id="grounding-course"
      list="grounding-course-options"
      value={courseName}
      placeholder="课程名（与上传课件时一致）"
      onChange={(event) => setCourseName(event.target.value)}
    />
    <datalist id="grounding-course-options">
      {courses.map((name) => <option key={name} value={name} />)}
    </datalist>
    {files.data && courses.length === 0 && <p className="empty-state">尚无带课程的已上传课件；也可以从下方课件面板直接上传（需校园账号）。</p>}

    {course !== "" && <MaterialsPanel
      courseName={course}
      consentEnabled={consent.data?.enabled ?? null}
      backendFiles={files.data ?? []}
    />}

    {course !== "" && consent.isPending && <p className="empty-state">正在读取授权状态…</p>}
    {course !== "" && consent.error && <p className="error-text">授权状态读取失败：{errorText(consent.error)}</p>}
    {course !== "" && consent.data && <div className="consent-panel">
      <details>
        <summary>{enabled ? "本课程资料问答已开启（点击查看授权内容）" : "开启前请阅读授权说明"}</summary>
        <p className="consent-text">{consent.data.consent_text}</p>
      </details>
      {enabled
        ? <button className="ghost-button" disabled={setConsent.isPending} onClick={() => { if (window.confirm("关闭后不再发送新的生成请求（已上传文件与历史回答保留）。")) setConsent.mutate(false); }}>关闭资料问答</button>
        : <button className="primary-button" disabled={setConsent.isPending} onClick={() => setConsent.mutate(true)}>同意并开启</button>}
      {setConsent.error && <p className="error-text">{errorText(setConsent.error)}</p>}
    </div>}

    {enabled && <>
      <div className="ask-form">
        <label className="field-label" htmlFor="grounding-question">问题</label>
        <textarea
          id="grounding-question"
          rows={2}
          value={question}
          placeholder="例如：采样定理的要求是什么？"
          onChange={(event) => setQuestion(event.target.value)}
        />
        <div className="section-actions">
          <button className="primary-button" disabled={ask.isPending || question.trim() === ""} onClick={() => ask.mutate()}>
            {ask.isPending ? "生成中…（调用模型，稍候）" : "提问"}
          </button>
        </div>
      </div>
      {ask.error && <p className="error-text" role="alert">{askErrorText(ask.error)}</p>}
      {latest && <AnswerCard answer={latest} filesById={filesById} idPrefix="latest-" />}
    </>}

    {enabled && <div className="section-heading">
      <h3>历史回答</h3>
      <span className="section-meta">{answers.data?.length ?? "…"} 条</span>
    </div>}
    {enabled && answers.isPending && <p className="empty-state">正在读取历史…</p>}
    {enabled && answers.error && <p className="error-text">历史读取失败：{errorText(answers.error)}</p>}
    {enabled && answers.data && answers.data.length === 0 && <p className="empty-state">还没有回答记录。</p>}
    {enabled && answers.data && answers.data.length > 0 && (
      <details className="answer-history">
        <summary>展开历史（{answers.data.length} 条）</summary>
        <div className="answer-list">
          {answers.data.map((answer) => <AnswerCard key={answer.id} answer={answer} filesById={filesById} onDelete={deleteAnswer} />)}
        </div>
      </details>
    )}
    {remove.error && <p className="error-text">删除失败：{errorText(remove.error)}</p>}
  </section>;
}
