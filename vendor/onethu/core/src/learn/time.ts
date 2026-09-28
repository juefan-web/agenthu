/**
 * learn 时间字段解析（**依赖无关**的独立模块）。
 *
 * 刻意单独成文件：`learn/client.ts` 会拉进 HttpClient 与 SM2 加密（`sm-crypto` 是 CJS，
 * Node 侧无法作为 ESM 具名导入），任何想复用时间解析的纯计算模块（如通知计划
 * `state/notifyPlan.ts`）都会因此无法在无构建产物下直测。解析逻辑本身与 HTTP 无关，
 * 剥出来两边都干净。
 */

/* ---------- 时间解析（对照 thu-app mobile：dayjs 直吃 learn 字符串，
 *  但 learn JSON 的时间字段形态不一，统一在此归一化，杜绝 NaN/Invalid Date） ----------
 *  实测形态：常规 "2025-10-01 12:30(:ss)"、日期-only "2025-09-01"、ISO 串、
 *  毫秒时间戳（数字或数字串）、.NET 前后缀 "/Date(1698150000000+0800)/"，
 *  以及非字符串时的 *Str 兜底字段（learn-lib: fbsj→fbsjStr；learnApi: jzsj→jzsjStr）。 */

/** learn 时间字段 → Date（本地时区语义，解析失败返回 null）。
 *  core 归一化与 UI（fmtDateTime/timeLeft）共用同一套解析。 */
export function parseLearnTime(raw: unknown): Date | null {
  if (raw === null || raw === undefined) return null;
  // 数字 / 10~14 位纯数字串 = 秒（10 位）或毫秒（13 位）时间戳
  if (typeof raw === "number" && Number.isFinite(raw)) {
    return new Date(raw < 1e12 ? raw * 1000 : raw);
  }
  const s = String(raw).trim();
  if (!s) return null;
  if (/^\d{10,14}$/.test(s)) {
    const n = Number(s);
    return new Date(n < 1e12 ? n * 1000 : n);
  }
  // .NET JSON 日期前后缀：/Date(1698150000000+0800)/
  const dotnet = /\/Date\((-?\d+)/.exec(s);
  if (dotnet?.[1]) return new Date(Number(dotnet[1]));
  // "YYYY-M-D H:m(:ss)" / "YYYY-M-D"：learn 服务器给的是本地时区语义，
  // 不能交给 Date.parse（"2025-10-01" 会被当 UTC）→ 手工拆解
  const m = /^(\d{4})-(\d{1,2})-(\d{1,2})(?:[ T](\d{1,2}):(\d{2})(?::(\d{2}))?)?$/.exec(s);
  if (m?.[1] && m[2] && m[3]) {
    const [, y, mo, d, h = "0", mi = "0", se = "0"] = m;
    return new Date(+y, +mo - 1, +d, +h, +mi, +se);
  }
  // 其余（ISO 带 Z/偏移等）交给 Date.parse
  const t = Date.parse(s);
  return Number.isNaN(t) ? null : new Date(t);
}
