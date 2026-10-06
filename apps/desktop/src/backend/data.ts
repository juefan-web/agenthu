import { DataReceiptOutSchema, type DataReceiptOut } from "@agenthu/contracts";
import { sha256Hex } from "../sync/owner";

/** recover 请求摘要的规范化 JSON（D-036 §8-2 冻结算法）：
 *  `sha256(utf8(json.dumps(body, sort_keys=True, separators=(',',':'),
 *  ensure_ascii=False)))` 的 TS 镜像——递归键排序 + 紧凑分隔 + 非 ASCII
 *  不转义（JSON.stringify 默认即不转义）。键排序只需覆盖请求体自身的
 *  固定 ASCII 键（client_request_id/confirmed/preview_digest/preview_id）；
 *  值不参与排序，故 JS/Python 排序差异面对该形状不可达。
 *  冻结样本：tests/fixtures/deletion-recover-digest.json（双端必须逐字节
 *  同摘要，data.test.ts 以同值钉住）。 */
export function canonicalJson(value: unknown): string {
  return JSON.stringify(sortKeys(value));
}

function sortKeys(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(sortKeys);
  if (value !== null && typeof value === "object") {
    const record = value as Record<string, unknown>;
    return Object.fromEntries(
      Object.keys(record)
        .sort()
        .map((key) => [key, sortKeys(record[key])]),
    );
  }
  return value;
}

/** POST /deletions 请求体的 recover 二因子摘要（自包含同步 SHA-256，
 *  跨 WebView/jsdom/Node 确定性优先——不依赖 subtleCrypto）。 */
export function deletionRequestDigest(body: Record<string, unknown>): string {
  return sha256Hex(canonicalJson(body));
}

/** 回执能力读取（B 稿 §1/§3）：capability 作 Bearer 直连，不经业务
 *  会话/不进 URL/日志/遥测；404/401/过期一律 null——客户端对无效能力
 *  统一显示「回执不可用」，不区分不存在/过期/身份不符（无枚举面）。
 *  fetcher 可注入（最小视图与测试都不依赖 AppServices）。 */
export async function fetchReceiptWithCapability(
  baseUrl: string,
  receiptId: string,
  capability: string,
  fetcher: typeof fetch = (input, init) => fetch(input, init),
): Promise<DataReceiptOut | null> {
  const response = await fetcher(`${baseUrl}/v1/data/receipts/${receiptId}`, {
    method: "GET",
    headers: { Authorization: `Bearer ${capability}` },
    credentials: "omit",
  });
  if (!response.ok) return null;
  return DataReceiptOutSchema.parse(await response.json());
}
