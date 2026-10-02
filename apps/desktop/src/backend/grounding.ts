import { z } from "zod";

/** Grounding / material-answers API 是 backend-only（TASKS/
 * m3-grounded-answers.md §6 冻结形状；与 Memory API 同口径不入
 * `@agenthu/contracts`）——本文件是消费侧本地 schema，服务端形状
 * （backend/schemas/material.py）演进时同步此处。 */

const IsoDateTime = z.string().datetime({ offset: true });

/** §6：citations 是快照元组；span_* 为 chunk 归一化文本坐标系
 * （UI 不依赖 span 精确渲染，跳转按 quote + page 呈现）。 */
export const MaterialCitationSchema = z.object({
  file_id: z.string(),
  checksum: z.string().nullable(),
  page: z.number().int().nullable(),
  span_start: z.number().int(),
  span_end: z.number().int(),
  quote: z.string(),
});
export type MaterialCitation = z.infer<typeof MaterialCitationSchema>;

export const MaterialAnswerSchema = z.object({
  id: z.string(),
  course_name: z.string(),
  question: z.string(),
  answer: z.string(),
  grounded: z.boolean(),
  citations: z.array(MaterialCitationSchema),
  chunk_ids: z.array(z.string()),
  memory_ids: z.array(z.string()),
  model_version: z.string(),
  prompt_version: z.string(),
  created_at: IsoDateTime,
});
export type MaterialAnswer = z.infer<typeof MaterialAnswerSchema>;

/** GET/PUT /v1/grounding-consent：consent_text 由后端下发——「开启」
 *  必须展示用户实际读到的措辞（stale-version 拒绝的另一半语义）。 */
export const GroundingConsentSchema = z.object({
  course_name: z.string(),
  enabled: z.boolean(),
  consent_text: z.string(),
  consent_text_version: z.string(),
  consented_at: IsoDateTime.nullable(),
});
export type GroundingConsent = z.infer<typeof GroundingConsentSchema>;

/** GET /v1/files（backend-only）：讲解页取课程列表与引用文件名。 */
export const FileInfoSchema = z.object({
  id: z.string(),
  filename: z.string(),
  checksum_sha256: z.string().nullable(),
  course_name: z.string().nullable(),
  status: z.string(),
});
export type FileInfo = z.infer<typeof FileInfoSchema>;
