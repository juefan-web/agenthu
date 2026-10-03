import { z } from "zod";

/** GET/PUT /v1/model-context-consent：全局「Agent 模型上下文」同意
 *  （D-034 §6.2，默认关；形状镜像 M3 grounding-consent——backend-only，
 *  不入 `@agenthu/contracts`，服务端形状（backend/schemas/consent.py）
 *  演进时同步此处）。consent_text 由后端下发，「开启」必须回显用户实际
 *  读到的 consent_text_version（版本回显规则：文案更新强制重新确认）。 */

const IsoDateTime = z.string().datetime({ offset: true });

export const ModelContextConsentSchema = z.object({
  enabled: z.boolean(),
  consent_text: z.string(),
  consent_text_version: z.string(),
  consented_at: IsoDateTime.nullable(),
});
export type ModelContextConsent = z.infer<typeof ModelContextConsentSchema>;
