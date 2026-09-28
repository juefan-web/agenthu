/**
 * Tyche（清华程序在线评测，内网）只读客户端。
 *
 * 实测（2026-09-18）：
 * - 用户 GET user/UserFetchSetting
 * - 课程组 GET group/GroupList → { groupList: [{ gid, name }] }
 * - 组详情+作业 GET group/ShowGroup?gid=42 → { group: { gid, name, tasks: [...] } }
 *   任务字段：{ tid, title, startTime, endTime, judgeEndTime, description, restricted }
 * - 鉴权**两层**：`Authorization: Basic base64("cs:thuc++")` **且** Cookie（JSESSIONID/username/uid）
 * - DDL = judgeEndTime || endTime，形如 "2026-09-27T16:00:00"（**无时区**）
 *   → 必须按**本地时间**解析（直接 new Date 会当 UTC，差 8 小时）
 * - 会话失效 → 响应 {"status":"login"}
 * - R19 27.2b 实测（gid=42 tid=1406，有效 Cookie 探测定稿）：
 *   `GET task/Status` → `{ status:"success", submissionCount, page, submissionList:[…] }`，
 *   每条提交 `{ sid, pid, tid, gid, uid, name, language, codeLength, time, memory,
 *   score, result, outdated, secret, submitedTime }`——`pid`=题目、`score`=该次提交得分
 *   （0/100）、`result`=判题结果（实测 2=通过 / 9=错误），同一 pid 可有多条历史提交；
 *   `group.tasks[]` 本身**不带得分**（仅 tid/gid/title/description/时间/mode 等元数据），
 *   故「已批改 / 得分」只能从 `submissionList` 按 pid 取最新一条汇总（见 fetchTycheStatus）。
 * ⚠️ 服务端地址与 Basic 头均硬编码，凭据不再携带 base
 */
import type { FetchLike } from "../http.js";
import type { ExternalHomework, HomeworkSource } from "./types.js";

export const BASE = "http://166.111.236.164:6080/tyche";
/** 外层 Basic 认证（写死，不向用户暴露） */
const DEFAULT_BASIC = "cs:thuc++";
const UA =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/79.0.3945.88 Safari/537.36";

interface TycheCred {
  cookie: string;
}

/* ── R21-A：Tyche 会话失效错误（可静默自动重登的唯一触发类型） ──
 * 实测（2026-09-20 真连侦查，见 docs §29.1）：会话失效有三种表现——
 * ① 响应 `{"status":"login"}`（GroupList / ShowGroup / task/Status 均如此，HTTP 200）；
 * ② HTTP 401/403（外层 Basic 网关拒绝）；
 * ③ 返回非 JSON（登录页 HTML / 网关跳转）。
 * 三者都归一为 TycheSessionError，编排层（exthw/index.ts）只对它触发自动重登；
 * 其余错误（网络断、HTTP 5xx、字段异常）不重登，保持原样上抛。 */
export class TycheSessionError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "TycheSessionError";
  }
}

/** 是否 Tyche 会话失效错误（含子类；其他错误一律 false） */
export function isTycheSessionError(e: unknown): e is TycheSessionError {
  return e instanceof TycheSessionError;
}

/** 无时区的本地日期时间串 → 毫秒（"2026-09-27T16:00:00" 按本地时间，绝不按 UTC） */
function parseLocalDateTime(s: string): number {
  const t = s.trim();
  const m = /^(\d{4})-(\d{1,2})-(\d{1,2})(?:[T ](\d{1,2}):(\d{2})(?::(\d{2}))?)?$/.exec(t);
  if (!m) {
    const p = Date.parse(t);
    return Number.isNaN(p) ? NaN : p;
  }
  return new Date(+m[1]!, +m[2]! - 1, +m[3]!, +(m[4] ?? 0), +(m[5] ?? 0), +(m[6] ?? 0)).getTime();
}

/** 毫秒时间戳 → "YYYY-MM-DD HH:MM"（本地时区） */
function fmtLocal(ms: number): string {
  const d = new Date(ms);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

/** Basic 头：原始 "user:pass" 现场 base64；已带 "Basic " 前缀或已是 base64 的原样保留 */
export function basicHeader(raw: string): string {
  const v = (raw ?? "").trim() || DEFAULT_BASIC;
  if (/^basic\s+/i.test(v)) return v;
  if (v.includes(":")) return `Basic ${BufferLike.base64(v)}`;
  return `Basic ${v}`;
}

/** 免依赖 base64（core 不能假设 Buffer 可用；纯 ASCII 输入） */
const BufferLike = {
  base64(s: string): string {
    const g = globalThis as { btoa?: (x: string) => string; Buffer?: { from: (x: string) => { toString: (e: string) => string } } };
    if (typeof g.btoa === "function") return g.btoa(s);
    if (g.Buffer) return g.Buffer.from(s).toString("base64");
    throw new Error("当前环境缺少 base64 编码能力");
  },
};

async function getJson(fetchLike: FetchLike, url: string, headers: Record<string, string>): Promise<Record<string, unknown>> {
  const res = await fetchLike(url, { method: "GET", headers });
  if (res.status === 401 || res.status === 403) {
    // R21-A：401/403 = 会话/网关鉴权失效 → 会话错误（可自动重登）
    throw new TycheSessionError(`Tyche 鉴权失败（HTTP ${res.status}），请检查 Basic / Cookie（校外需 WebVPN）`);
  }
  const body = await res.text();
  let json: unknown;
  try {
    json = JSON.parse(body);
  } catch {
    // R21-A：非 JSON = 登录页 HTML / 网关跳转（「跳登录页」特征）→ 会话错误
    throw new TycheSessionError("Tyche 返回非 JSON（会话可能已失效，被跳到登录页）");
  }
  const obj = (json ?? {}) as Record<string, unknown>;
  // R21-A：`status:"login"` = 接口未登录特征（实测会话失效的唯一稳定标志）→ 会话错误
  if (obj["status"] === "login") throw new TycheSessionError("Tyche 会话已失效（status=login），请在设置页更新 Cookie");
  return obj;
}

/**
 * 查单个作业（task）的提交与批改状态：`GET task/Status?tid={tid}&gid={gid}`（**不带 all=true**）。
 * 实测：不带 `all=true` 时只返回**当前用户**的提交（`submissionList[].name` = 自己，
 * `uid` = 自己）；带 `all=true` 则返回全组。故 `submissionCount > 0` → 已提交。
 * ⚠️ 不用 `task/ProblemStatus`：其实测返回 sid/uid/submitedTime 全为 null、
 *    result/score 恒定（与是否提交无关），**不是**用户维度的提交状态。
 *
 * 已批改判定（R19 27.2b 定稿）：
 * 1. 按 `pid` 分组，每组取 `submitedTime` 最新的一条（并列取 `sid` 最大）；
 * 2. `graded = submissionCount > 0` 且**每个 pid 的最新提交都带数字 score**；
 *    `result` 若为 0/1 视为判题中（探测未观测到该值，保守排除并注释）；
 * 3. `score = Σ 各 pid 最新 score`；`totalScore = 100 × pid 数`（Tyche 每题满分 100，实测佐证）。
 *    score/totalScore 仅 `graded` 时透出（沿用 R9 约定：未出分不显示 0 分误导）。
 */
interface TycheStatusResult {
  submitted: boolean;
  submittedCount?: number;
  /** 是否已批改（判定失败保守 false） */
  graded: boolean;
  /** 各题最新得分之和（仅 graded 时给） */
  score?: number;
  /** 满分 = 100 × 题数（仅 graded 时给） */
  totalScore?: number;
}

/** 提交时间比较：a 是否比 b 更新。`submitedTime` 两者均可解析为数字则按数值比
 *  （兼容毫秒时间戳形态），否则按字符串比（实测 "YYYY-MM-DD HH:MM:SS" 同格式
 *  字典序即时间序）；时间并列 / 缺失时取 `sid` 大者（27.2b 定稿）。 */
function isNewerSubmission(a: Record<string, unknown>, b: Record<string, unknown>): boolean {
  const num = (v: unknown): number =>
    typeof v === "number" && Number.isFinite(v)
      ? v
      : typeof v === "string" && v.trim() !== "" && Number.isFinite(Number(v))
        ? Number(v)
        : NaN;
  const na = num(a["submitedTime"]);
  const nb = num(b["submitedTime"]);
  if (Number.isFinite(na) && Number.isFinite(nb) && na !== nb) return na > nb;
  const sa = typeof a["submitedTime"] === "string" ? (a["submitedTime"] as string).trim() : "";
  const sb = typeof b["submitedTime"] === "string" ? (b["submitedTime"] as string).trim() : "";
  if (sa && sb && sa !== sb) return sa > sb;
  const ia = num(a["sid"]);
  const ib = num(b["sid"]);
  if (Number.isFinite(ia) && Number.isFinite(ib) && ia !== ib) return ia > ib;
  return false;
}

/** 由 submissionList 汇总已批改 / 得分（规则见 fetchTycheStatus 注释；失败保守 false） */
function judgeTycheGraded(submissionCount: number, list: Array<Record<string, unknown>>): Pick<TycheStatusResult, "graded" | "score" | "totalScore"> {
  // 未提交（含 submissionCount 缺失回退 list.length 后仍为 0）→ 谈不上已批改
  if (!(submissionCount > 0)) return { graded: false };
  // 按 pid 分组，取每题最新一条提交
  const latest = new Map<string, Record<string, unknown>>();
  for (const it of list) {
    if (!it || typeof it !== "object") continue;
    const pid = it["pid"];
    if (pid === undefined || pid === null) continue;
    const key = String(pid);
    const cur = latest.get(key);
    if (cur === undefined || isNewerSubmission(it, cur)) latest.set(key, it);
  }
  if (latest.size === 0) return { graded: false };
  let score = 0;
  for (const it of latest.values()) {
    // 每题最新提交都必须带数字 score，否则保守视为未批改
    const s = it["score"];
    if (typeof s !== "number" || !Number.isFinite(s)) return { graded: false };
    // result 0/1 = 判题中（探测未观测到该值，保守排除：有分也当未判完）
    const r = it["result"];
    if (r === 0 || r === 1) return { graded: false };
    score += s;
  }
  return { graded: true, score, totalScore: 100 * latest.size };
}

async function fetchTycheStatus(
  fetchLike: FetchLike,
  base: string,
  headers: Record<string, string>,
  gid: unknown,
  tid: unknown,
): Promise<TycheStatusResult> {
  const st = await getJson(
    fetchLike,
    `${base}/task/Status?tid=${encodeURIComponent(String(tid))}&gid=${encodeURIComponent(String(gid))}`,
    headers,
  );
  const cnt = st["submissionCount"];
  const list = Array.isArray(st["submissionList"]) ? (st["submissionList"] as Array<Record<string, unknown>>) : [];
  const count = typeof cnt === "number" && Number.isFinite(cnt) ? cnt : list.length;
  const gradedInfo = judgeTycheGraded(count, list);
  return {
    submitted: count > 0,
    submittedCount: count > 0 ? count : undefined,
    ...gradedInfo,
  };
}

export function createTycheSource(cred: TycheCred, fetchLike: FetchLike, days: number): HomeworkSource {
  const base = BASE;
  const headers = {
    Authorization: basicHeader(DEFAULT_BASIC),
    Cookie: (cred.cookie ?? "").trim(),
    "User-Agent": UA,
    Accept: "application/json, text/plain, */*",
  };
  return {
    id: "tyche",
    name: "Tyche",
    async fetch(): Promise<ExternalHomework[]> {
      const groupsBody = await getJson(fetchLike, `${base}/group/GroupList`, headers);
      const groups = Array.isArray(groupsBody["groupList"])
        ? (groupsBody["groupList"] as Array<Record<string, unknown>>)
        : [];
      const limit = Date.now() + (days > 0 ? days : 30) * 86400000;
      const out: ExternalHomework[] = [];
      for (const g of groups) {
        const gid = g["gid"];
        if (gid === undefined || gid === null) continue;
        const groupName = String(g["name"] ?? "Tyche 课程");
        // 逐课程组隔离：单个失败只跳过
        try {
          const detail = await getJson(fetchLike, `${base}/group/ShowGroup?gid=${gid}`, headers);
          const group = (detail["group"] ?? {}) as Record<string, unknown>;
          const tasks = Array.isArray(group["tasks"])
            ? (group["tasks"] as Array<Record<string, unknown>>)
            : [];
          for (const t of tasks) {
            const tid = t["tid"];
            if (tid === undefined || tid === null) continue;
            const raw = t["judgeEndTime"] ?? t["endTime"];
            if (typeof raw !== "string" || !raw.trim()) continue;
            const ms = parseLocalDateTime(raw);
            if (!Number.isFinite(ms)) continue;
            if (ms > limit) continue;
            // 提交/批改状态（仅对时间窗内的 task 查）；失败只跳过（保守 false）。
            // R21-A：会话失效必须上抛（否则 status=login 只会静默变成「未提交」，
            // 自动重登永远不被触发）；其余错误仍吞掉。
            let status: TycheStatusResult = { submitted: false, graded: false };
            try {
              status = await fetchTycheStatus(fetchLike, base, headers, gid, tid);
            } catch (e) {
              if (isTycheSessionError(e)) throw e;
              /* 状态查询失败：保守保持未提交、未批改 */
            }
            const hw: ExternalHomework = {
              id: `tyche-${gid}-${tid}`,
              source: "tyche",
              courseName: groupName,
              title: String(t["title"] ?? "作业"),
              deadline: fmtLocal(ms),
              kind: "homework",
              url: `${base}/#!html/Task.html&tid=${tid}`,
              submitted: status.submitted,
            };
            if (status.submittedCount !== undefined) hw.submittedCount = status.submittedCount;
            // R19 27.2：已批改判定 + 得分（score/totalScore 仅 graded 时透出，
            // 沿用 R9 约定：未出分不显示 0 分误导）
            hw.graded = status.graded;
            if (status.graded) {
              hw.score = status.score;
              hw.totalScore = status.totalScore;
            }
            out.push(hw);
          }
        } catch (e) {
          // R21-A：单课程组失败跳过；但会话失效必须冒泡（触发自动重登）
          if (isTycheSessionError(e)) throw e;
          /* 单课程组失败跳过 */
        }
      }
      return out;
    },
  };
}
