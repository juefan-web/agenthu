import { z } from "zod";

/** Memory API 是 backend-only（D-032 §8 裁定：不入客户端权威契约
 *  `@agenthu/contracts`）——本文件是消费侧本地 schema，服务端形状
 *  （backend/schemas/memory.py MemoryRead）演进时同步此处。 */

const IsoDateTime = z.string().datetime({ offset: true });

export const MemoryItemSchema = z.object({
  id: z.string(),
  user_id: z.string(),
  level: z.number().int().min(0).max(3),
  domain: z.string(),
  content: z.string(),
  source: z.record(z.unknown()),
  source_event_ids: z.array(z.string()),
  confidence: z.number().min(0).max(1),
  correction_status: z.enum(["UNREVIEWED", "CONFIRMED", "CORRECTED", "REJECTED"]),
  evidence: z.array(z.record(z.unknown())),
  kind: z.enum(["episode", "fact", "habit", "preference", "model"]).nullable(),
  subject_key: z.string().nullable(),
  supersedes_id: z.string().nullable(),
  valid_from: IsoDateTime.nullable(),
  valid_to: IsoDateTime.nullable(),
  use_count: z.number().int().nonnegative(),
  last_used_at: IsoDateTime.nullable(),
  created_at: IsoDateTime,
  updated_at: IsoDateTime,
});

export type MemoryItem = z.infer<typeof MemoryItemSchema>;
