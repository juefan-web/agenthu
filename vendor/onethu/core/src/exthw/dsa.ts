/**
 * DSA OJ（数据结构课 OJ，dsa.cs.tsinghua.edu.cn/oj）只读客户端。
 *
 * 实测（R15 20.1，酒狐 2026-09-19）：
 * - 老式 Bootstrap/jQuery 站；接口均为 `POST` form-urlencoded，会话靠 cookie：
 *   - 会话检查 `user.php` `{action:"checklogin"}` → `{islogin:boolean}`
 *   - 登录     `user.php` `{action:"login", username, password}` → `{error:0}`
 *   - 课程列表 `course.php` `{action:"usercourses", type:1}` →
 *       `{error:0, courseList:[{courseId, name, ...}]}`
 *   - 课程详情 `course.php` `{action:"courseinfo", course_id}` →
 *       `{error:0, courseList:[{myRole, assignmentList:[{id, name, endDate, status, ...}]}]}`
 * - DDL = `assignment.endDate`（站点标注 UTC+8，格式不确定 → 见 parseDsaDate 容错解析）
 * - 无统一认证（邮箱 + 密码），仅手动账密
 *
 * ⚠️ 只读：只拉标题 / 课程 / DDL，不提交、不抓题目正文。
 * ⚠️ 提交状态：20.1 未确认 `assignment.status` 的语义，**保守判为未提交**
 *   （与 types.ts「无法判定时保守 false」一致），待真机联调后再补判定。
 */
import type { FetchLike } from "../http.js";
import type { ExternalHomework, HomeworkSource } from "./types.js";

export const BASE = "https://dsa.cs.tsinghua.edu.cn/oj/";
const ORIGIN = "https://dsa.cs.tsinghua.edu.cn";
const UA =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/79.0.3945.88 Safari/537.36";

interface DsaCred {
  /** 登录后拼好的会话 Cookie（PHPSESSID 等） */
  cookie: string;
  /** 登录邮箱；仅用于设置页回填 */
  username?: string;
}

/** DSA OJ 会话失效（checklogin=false / 业务 error≠0）。设置页据此引导重新登录。 */
export class DsaSessionError extends Error {
  constructor(message = "DSA OJ 会话已失效，请在设置页重新登录") {
    super(message);
    this.name = "DsaSessionError";
  }
}

/** 是否为 DSA 会话失效错误（设置页 / 调用方据此提示重登） */
export function isDsaSessionError(e: unknown): e is DsaSessionError {
  return e instanceof DsaSessionError;
}

/** 服务端 `error` 字段（0 / "0" = 成功；缺失按 0；非数字按 0 不误判） */
function errorCode(body: Record<string, unknown>): number {
  const e = body["error"];
  if (e === undefined || e === null) return 0;
  const n = Number(e);
  return Number.isFinite(n) ? n : 0;
}

async function postForm(
  fetchLike: FetchLike,
  path: string,
  params: Record<string, string | number>,
  cookie: string,
): Promise<Record<string, unknown>> {
  const headers: Record<string, string> = {
    "Content-Type": "application/x-www-form-urlencoded",
    "User-Agent": UA,
    Accept: "application/json, text/plain, */*",
    Origin: ORIGIN,
    Referer: BASE,
  };
  if (cookie) headers["Cookie"] = cookie;
  const res = await fetchLike(`${BASE}${path}`, {
    method: "POST",
    headers,
    body: new URLSearchParams(Object.entries(params).map(([k, v]) => [k, String(v)])).toString(),
  });
  const text = await res.text();
  let json: unknown;
  try {
    json = JSON.parse(text);
  } catch {
    throw new DsaSessionError("DSA OJ 返回非 JSON（会话可能已失效），请在设置页重新登录");
  }
  return (json ?? {}) as Record<string, unknown>;
}

/** 会话是否有效（`user.php` checklogin）；网络/解析失败也视为无效（保守） */
export async function dsaCheckLogin(fetchLike: FetchLike, cookie: string): Promise<boolean> {
  try {
    const body = await postForm(fetchLike, "user.php", { action: "checklogin" }, cookie);
    if (errorCode(body) !== 0) return false;
    const v = body["islogin"];
    return v === true || v === 1 || v === "1" || v === "true";
  } catch {
    return false;
  }
}

/**
 * `endDate` 容错解析（20.1：格式不确定）→ 毫秒；无法识别返回 NaN。
 * 支持：10/13 位时间戳、ISO 带时区（Z / ±HH:MM）、`YYYY-MM-DD[ T]HH:MM[:SS]`、
 * `YYYY/MM/DD ...`（无时区按**本地时间**解析，与 Tyche 同口径）。
 */
export function parseDsaDate(raw: unknown): number {
  if (typeof raw === "number" && Number.isFinite(raw)) return raw > 1e12 ? raw : raw * 1000;
  if (typeof raw !== "string") return NaN;
  const s = raw.trim();
  if (!s) return NaN;
  // 纯数字串：10 位 = 秒，13 位 = 毫秒
  if (/^\d{10,13}$/.test(s)) {
    const n = Number(s);
    return s.length <= 10 ? n * 1000 : n;
  }
  // 显式时区 → 绝对时刻，交给 Date.parse
  if (/(?:Z|[+-]\d{2}:?\d{2})$/i.test(s)) {
    const p = Date.parse(s);
    return Number.isNaN(p) ? NaN : p;
  }
  // 无时区：按本地时间解析（站点标注 UTC+8；本应用面向校内用户）
  const m = /^(\d{4})[-/](\d{1,2})[-/](\d{1,2})(?:[T ](\d{1,2}):(\d{2})(?::(\d{2}))?)?/.exec(s);
  if (m) {
    return new Date(+m[1]!, +m[2]! - 1, +m[3]!, +(m[4] ?? 0), +(m[5] ?? 0), +(m[6] ?? 0)).getTime();
  }
  const p = Date.parse(s);
  return Number.isNaN(p) ? NaN : p;
}

/** 毫秒时间戳 → "YYYY-MM-DD HH:MM"（本地时区） */
function fmtLocal(ms: number): string {
  const d = new Date(ms);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

export function createDsaSource(cred: DsaCred, fetchLike: FetchLike, days: number): HomeworkSource {
  const cookie = (cred.cookie ?? "").trim();
  return {
    id: "dsa",
    name: "DSA OJ",
    async fetch(): Promise<ExternalHomework[]> {
      if (!(await dsaCheckLogin(fetchLike, cookie))) {
        throw new DsaSessionError();
      }
      const coursesBody = await postForm(fetchLike, "course.php", { action: "usercourses", type: 1 }, cookie);
      if (errorCode(coursesBody) !== 0) {
        throw new DsaSessionError(`DSA OJ 课程列表请求失败（error=${errorCode(coursesBody)}），会话可能已失效`);
      }
      const courses = Array.isArray(coursesBody["courseList"])
        ? (coursesBody["courseList"] as Array<Record<string, unknown>>)
        : [];
      const limit = Date.now() + (days > 0 ? days : 30) * 86400000;
      const out: ExternalHomework[] = [];
      for (const c of courses) {
        const cid = c["courseId"] ?? c["course_id"] ?? c["id"];
        if (cid === undefined || cid === null) continue;
        const courseName = String(c["name"] ?? "DSA 课程");
        // 逐课程隔离：单门课失败只跳过
        try {
          const info = await postForm(fetchLike, "course.php", { action: "courseinfo", course_id: String(cid) }, cookie);
          if (errorCode(info) !== 0) continue;
          const infoCourses = Array.isArray(info["courseList"])
            ? (info["courseList"] as Array<Record<string, unknown>>)
            : [];
          const infoCourse = (infoCourses[0] ?? {}) as Record<string, unknown>;
          const assignments = Array.isArray(infoCourse["assignmentList"])
            ? (infoCourse["assignmentList"] as Array<Record<string, unknown>>)
            : [];
          for (const a of assignments) {
            const aid = a["id"] ?? a["assignmentId"];
            if (aid === undefined || aid === null) continue;
            const ms = parseDsaDate(a["endDate"] ?? a["deadline"] ?? a["endTime"]);
            if (!Number.isFinite(ms) || ms > limit) continue;
            out.push({
              id: `dsa-${cid}-${aid}`,
              source: "dsa",
              courseName,
              title: String(a["name"] ?? a["title"] ?? "作业"),
              deadline: fmtLocal(ms),
              kind: "homework",
              url: `${BASE}course.php?course_id=${encodeURIComponent(String(cid))}`,
              // 提交状态语义未确认（20.1）：保守 false，待真机联调补判定
              submitted: false,
            });
          }
        } catch {
          /* 单门课失败跳过（会话失效在入口 checklogin 统一判定） */
        }
      }
      return out;
    },
  };
}
