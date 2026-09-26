/**
 * 外部作业源（荷塘雨课堂 / TUOJ / Tyche）统一类型。
 *
 * 设计约束（见 docs/外部作业源-需求与实现方案.md 5.2）：
 * - core 层只做**只读**拉取：不依赖 DOM / localStorage；
 * - 网络一律走宿主注入的 `FetchLike`（desktop 传 universalFetch，即 Tauri 传输层，
 *   无 CORS、可显式透传 Cookie 头）；
 * - 凭据由 desktop 层从 localStorage 读出后注入，core 不碰存储。
 *
 * 服务端地址（base URL）**一律硬编码**在各源文件里，凭据结构不再暴露服务器字段。
 */
import type { FetchLike, HttpClient } from "../http.js";

export type ExtHwSourceId = "yuketang" | "tuoj" | "tuojClassic" | "tyche" | "dsa";

/** TUOJ 系（共用同一套客户端与清华统一认证漫游，仅 base/id/name 不同） */
export type TuojSourceId = "tuoj" | "tuojClassic";

/** 源展示名（UI 徽标 / 设置页统一口径） */
export const SOURCE_NAMES: Record<ExtHwSourceId, string> = {
  yuketang: "雨课堂",
  tuoj: "TUOJ（AI 版）",
  tuojClassic: "TUOJ（经典版）",
  tyche: "Tyche",
  dsa: "DSA OJ",
};

/** 源大类：`courseware` = 课程平台（雨课堂，人人可用）；
 *  `oj` = OJ 评测平台（按个人情况，不是每个 THUer 都有账号）。 */
export type ExtHwCategory = "courseware" | "oj";

/** 源 → 大类注册表（信息架构元数据；**不参与**凭据存储与拉取链路）。
 *  新增源只在此登记 category，设置页即可按大类自动归组。 */
export const SOURCE_CATEGORIES: Record<ExtHwSourceId, ExtHwCategory> = {
  yuketang: "courseware",
  tuoj: "oj",
  tuojClassic: "oj",
  tyche: "oj",
  dsa: "oj",
};

/** 大类展示名（设置页分组标题） */
export const SOURCE_CATEGORY_NAMES: Record<ExtHwCategory, string> = {
  courseware: "雨课堂",
  oj: "OJ 平台",
};

export interface ExternalHomework {
  /** 源内稳定唯一 id，用于 React key / 去重（不含 `ext:` 前缀） */
  id: string;
  source: ExtHwSourceId;
  courseName: string;
  title: string;
  /** 统一为 "YYYY-MM-DD HH:MM"（本地时区） */
  deadline: string;
  kind: "homework" | "exam";
  /** 详情链接（可空；三源均按 id/classroom 拼） */
  url?: string;
  /** 是否已提交（**真实判定**：三源各自查提交状态得出）。
   *  查询失败 / 无法判定（如雨课堂「试卷」类叶子无权限）时**保守为 false**。 */
  submitted: boolean;
  /** 已提交的题目数（可选，仅雨课堂有精确数据） */
  submittedCount?: number;
  /** 题目总数（可选，仅雨课堂有精确数据） */
  totalCount?: number;
  /** 是否已批改（R16 21.1；仅雨课堂能判定，其余源缺省 = 未批改，保守）。
   *  雨课堂作业：已提交且不存在「已作答但未批改」的题；试卷：已提交且已出分。 */
  graded?: boolean;
  /** 是否旁听课堂（雨课堂 courses/list `role===6`；role 5=正式、未知 role 不标，保守） */
  audited?: boolean;
  /** 得分（仅已提交且已出分/已批改时设置，避免误导性显示为 0 分）：
   *  考试 = /v/exam/cover 的 result.score（R9）；已批改作业 = 已批改题 my_score 合计（R20-B3） */
  score?: number;
  /** 卷面满分（与 score 成对出现）：考试 = /v/exam/cover 的 total_score；
   *  已批改作业 = 题面 content.score 合计（R20-B3；题面分值全缺失时不设） */
  totalScore?: number;
  /** R20-B2：雨课堂作业详情参数 leaf_type_id（get_exercise_list 路径段；仅 yuketang 源设置，
   *  其余源恒缺省）。移动端原生详情页（YktAssignmentDetailPage）据此拉整卷明细。 */
  leafTypeId?: string;
  /** R20-B2：雨课堂 classroom_id（与 leafTypeId 成对出现；仅 yuketang 源设置） */
  classroomId?: string;
}

export interface HomeworkSource {
  id: ExtHwSourceId;
  /** 展示名：雨课堂 / TUOJ / Tyche */
  name: string;
  /** 拉取；失败必须 throw，由调用方隔离（单源失败不影响其他源） */
  fetch(): Promise<ExternalHomework[]>;
}

/** 组装后的源：在基础源上附带大类元数据（由 createExternalSources 按
 *  `SOURCE_CATEGORIES` 登记，设置页据此归组；不影响拉取链路）。 */
export interface RegisteredHomeworkSource extends HomeworkSource {
  category: ExtHwCategory;
}

/** 凭据（由 desktop 层从 localStorage 读出后注入；core 不碰存储） */
export interface ExtHwCreds {
  /** 登录后拼好的会话 Cookie；`phone` 仅用于设置页回填 */
  yuketang?: { cookie: string; uvId?: string; phone?: string };
  /** 登录后拼好的会话 Cookie；`username` 仅用于设置页回填。
   *  `via`: "cas" = 清华统一认证漫游（会话在 HttpClient 的 jar 里，cookie 可空）；
   *         "password" = TUOJ 账号密码登录。 */
  tuoj?: TuojCreds;
  /** 经典 TUOJ（oj.cs.tsinghua.edu.cn）：同 AI 版结构（复用同一客户端）。 */
  tuojClassic?: TuojCreds;
  /** DSA OJ（dsa.cs.tsinghua.edu.cn）：邮箱 + 密码登录，会话 Cookie；
   *  `username`（邮箱）仅用于设置页回填。 */
  dsa?: { cookie: string; username?: string };
  /** 登录后拼好的会话 Cookie；Basic 头已硬编码，不在此暴露。
   *  R21-A：`password` = 「记住密码」勾选后保存的 Tyche 登录口令（**明文参数，只存在于
   *  本结构内存态**；落盘走 desktop 的 AES-GCM 信封 `onethu.exthw.v1`，与既有凭据同路——
   *  信封整体加密，不存在明文落盘）。会话失效（status=login / 401 / 跳登录页）时
   *  desktop 用 username+password 静默自动重登一次；未记住（缺省）则保持旧行为=手动。 */
  tyche?: { cookie: string; username?: string; password?: string };
  /** 只保留未来 N 天（默认 30）；已过期的仍保留（属"未提交"） */
  days?: number;
}

/** TUOJ 系凭据（AI 版 / 经典版共用） */
export interface TuojCreds {
  cookie: string;
  username?: string;
  via?: "cas" | "password";
}

/** 组装三源（只组装已配置 cookie / 已漫游的源），并附上 `category` 大类元数据 */
export type CreateExternalSources = (deps: {
  creds: ExtHwCreds;
  fetchLike: FetchLike;
  /** 带 CookieJar 的 core HttpClient（TUOJ 的清华统一认证漫游会话在 jar 里） */
  http?: HttpClient;
}) => RegisteredHomeworkSource[];
